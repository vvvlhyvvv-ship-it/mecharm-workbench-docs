"""comm.opcua_client.handshake —— 契约 §9.1 的九步握手（``Session`` 的混入基类）。

九步与本模块方法的对应（逐步可追，防口径漂移）：

| §9.1 步 | 谁做 | 落在哪 |
|---|---|---|
| 1 写 ``Seg[]``／``SegCount``／``SpeedOverride`` | SW | ``write_segments`` |
| 2 ``SeqID``+1、置 ``CMD_LOAD``（500 ms、重试 3 次） | SW | ``load`` → ``_write`` |
| 3 校验轴数／范围／软限位／倍率合法性 | PLC | 模拟器侧（``comm/simulator.py``） |
| 4 读 ``ACK_LOAD_OK``／``NG``（2 s） | SW | ``load`` → ``_pulse``；NG 抛 ``LoadRejected`` 带原因码 |
| 5 清 ``CMD_LOAD``、置 ``CMD_START``（500 ms） | SW | ``start`` → ``_pulse`` |
| 6 读 ``ACK_START_OK``（2 s） | SW | ``start`` |
| 7 20 Hz 读 ``Pos``／``Vel``／``CurSeg``（心跳 200 ms） | SW | 订阅＋看门狗（subscribe.py／reconnect.py） |
| 8 PLC 置 ``ST_DONE``、清 ``ST_RUNNING`` | PLC | ``wait_done`` 等它 |
| 9 清 ``CMD_START``、写审计日志 | SW | ``run``（清位由脉冲语义在 ``_pulse`` 里做到） |

**为什么用混入而不是自由函数**：握手要读写「一次会话」的状态（下发节点句柄、回读快照、唤醒事件、
当前 SeqID），拆成自由函数就得把这些逐个当形参传，把一份内聚状态摊成五六个参数。故**按职责切文件、
按混入合类**：``Session(Handshake)`` 运行时仍是一个类，``session.load(path)`` 的调用形态不变。
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING

from asyncua.ua.uaerrors import UaError

from comm.opcua_client.errors import (AckTimeout, CommError, LoadRejected, SeqMismatch,
                                      StartRejected)
from comm.opcua_client.subscribe import (ACK_LOAD_NG, ACK_LOAD_OK, ACK_RESET_DONE, ACK_START_NG,
                                         ACK_START_OK, ACK_STOP_DONE, ST_DONE, ST_PAUSED, Frame,
                                         ReadbackBuffer)
from comm.opcua_client.write import (CMD_LOAD, CMD_PAUSE, CMD_RESET, CMD_RESUME, CMD_START,
                                     CMD_STOP, SEG_SLOTS, SEQ_ID_MAX, SPEED_OVERRIDE_FULL,
                                     SPEED_OVERRIDE_MIN, WRITE_NODE_TYPES, Segment,
                                     pack_segments)

log = logging.getLogger(__name__)

WRITE_TIMEOUT_S = 0.5        # §9.1 步骤 2/5：写入超时
WRITE_RETRIES = 3            # §9.1 步骤 2：重试 3 次，仍失败→报错并停止
ACK_TIMEOUT_S = 2.0          # §9.1 步骤 4/6：等应答超时
DONE_TIMEOUT_S = 60.0        # §9.1 步骤 8：等 ST_DONE（契约未给值，取自测批最长段的宽裕上限）


class Handshake:
    """契约 §9.1 的九步握手。依赖 ``Session.__init__`` 建立的下列属性（在此声明，使契约可见）。"""

    if TYPE_CHECKING:
        axis_slots: int
        endpoint: str
        _wr: dict[str, object]
        _buffer: ReadbackBuffer
        _notify: asyncio.Event
        _seq_id: int

    async def _write(self, key: str, value: object) -> None:
        """写一个下发节点：超时 ``WRITE_TIMEOUT_S``、重试 ``WRITE_RETRIES`` 次后报错（§9.1 步骤 2）。

        节点句柄一律按 NodeId 取（§3.3「按符号名访问，不按字节偏移直接读写」），``key`` 是 machine.yaml
        的键名，类型取自 ``WRITE_NODE_TYPES``——本方法不认任何 PLC 符号名。
        """
        variant, node = WRITE_NODE_TYPES[key], self._wr[key]
        for attempt in range(1, WRITE_RETRIES + 1):
            try:
                await asyncio.wait_for(node.write_value(value, varianttype=variant), WRITE_TIMEOUT_S)
                return
            except (asyncio.TimeoutError, OSError, UaError) as caught:
                log.warning("写 %s 第 %d/%d 次失败：%s: %s", key, attempt, WRITE_RETRIES,
                            type(caught).__name__, caught)
        raise CommError(f"写 {key} 连续 {WRITE_RETRIES} 次超时（§9.1 步骤 2：重试 3 次仍失败即停止）")

    async def _await_bits(self, key: str, mask: int, timeout: float, what: str) -> int:
        """等回读键 ``key`` 的任一指定位出现，返回当时整值；超时抛 ``AckTimeout``。

        顺序必须是「清事件 → 查条件 → 再等」：反过来会漏掉查询与清事件之间到达的那次通知，
        于是明明已应答却白等满一个超时。
        """
        deadline = time.monotonic() + timeout
        while True:
            self._notify.clear()
            value = self._buffer.integer(key)
            if value & mask:
                return value
            left = deadline - time.monotonic()
            if left <= 0:
                raise AckTimeout(f"等 {what} 超时 {timeout} s（§9.1 超时表）")
            try:
                await asyncio.wait_for(self._notify.wait(), left)
            except asyncio.TimeoutError:
                pass

    async def _pulse(self, cmd_bit: int, ok_bit: int, ng_bit: int, step: str,
                     reject: Callable[[int, int], CommError]) -> None:
        """一个「置命令位 → 等应答 → 清命令位」回合（§9.1 步骤 2/4 与 5/6 共用同一形状）。

        §9.3-② 命令字是**脉冲语义**：清零放在 finally，超时／被拒也照清——留着置位会把 PLC 卡在
        「命令长期有效」的非法态，比报错更难查。
        """
        try:
            await self._write("cmd", cmd_bit)
            ack = await self._await_bits("ack", ok_bit | ng_bit, ACK_TIMEOUT_S, f"{step}应答")
            if ack & ng_bit:
                raise reject(self._buffer.integer("alarm_word"), self._seq_id)
        finally:
            await self._write("cmd", 0)

    async def write_segments(self, path: Sequence[Segment], *,
                             speed_override: float = SPEED_OVERRIDE_FULL) -> int:
        """§9.1 步骤 1：写 ``Seg[]``、``SegCount``、``SpeedOverride``（**只写数据，不动命令字**）。

        ``path`` 即 ``core/path.py::gen_path`` 的产物形态（T07 落地后直接接上）。返回写入的段数。
        段数组按 G17 裁决打成单个 ByteString 一次写（理由见 write.py 模块 docstring）。
        """
        if not 1 <= len(path) <= SEG_SLOTS:
            raise ValueError(f"段数 {len(path)} 应在 1–{SEG_SLOTS}（§5.1 SegCount 取值范围）")
        if not SPEED_OVERRIDE_MIN <= speed_override <= SPEED_OVERRIDE_FULL:
            raise ValueError(f"速度倍率 {speed_override} 应在 {SPEED_OVERRIDE_MIN}–"
                             f"{SPEED_OVERRIDE_FULL} %（§5.1）")
        await self._write("seg_array", pack_segments(path, self.axis_slots))
        await self._write("seg_count", len(path))
        await self._write("speed_override", speed_override)
        return len(path)

    async def load(self, path: Sequence[Segment], *,
                   speed_override: float = SPEED_OVERRIDE_FULL) -> int:
        """§9.1 步骤 1–4：写数据 → SeqID+1 并置 CMD_LOAD → 等 ACK_LOAD_OK/NG → 校 SeqID 回显。"""
        count = await self.write_segments(path, speed_override=speed_override)
        self._seq_id = 0 if self._seq_id >= SEQ_ID_MAX else self._seq_id + 1   # §5.1：0–32767 循环
        await self._write("seq_id", self._seq_id)
        await self._pulse(CMD_LOAD, ACK_LOAD_OK, ACK_LOAD_NG, "装载", LoadRejected)
        echoed = self._buffer.integer("seq_id")
        if echoed != self._seq_id:
            raise SeqMismatch(f"PLC 回显 SeqID={echoed} ≠ 写入 {self._seq_id}"
                              f"（§10：拒绝本次结果，重新同步）")
        return count

    async def start(self) -> None:
        """§9.1 步骤 5–6：置 CMD_START → 等 ACK_START_OK（未就绪／未回零／报警中则 NG）。"""
        await self._pulse(CMD_START, ACK_START_OK, ACK_START_NG, "启动", StartRejected)

    async def wait_done(self, timeout: float = DONE_TIMEOUT_S) -> Frame:
        """§9.1 步骤 8：等 ST_DONE，返回**按当时快照新出的一帧**（供上层核对 CurSeg 与实际位置）。

        ST_DONE 是 ``status`` 的变化、不触发帧节拍（节拍取 heartbeat），故此处主动出一帧。快照未收齐
        就报错——§9.3-③ 禁外推，也不许拿上一帧顶替「完成时刻的实际位置」。
        """
        await self._await_bits("status", ST_DONE, timeout, "ST_DONE")
        frame = self._buffer.emit()
        if frame is None:
            raise CommError("回读快照未收齐，无法给出 ST_DONE 时刻的实际位置（§9.3-③ 禁外推）")
        return frame

    async def stop_motion(self) -> None:
        """§9.2 软件主动停止：置 CMD_STOP → PLC 减速停止 → 等 ACK_STOP_DONE。"""
        await self._pulse(CMD_STOP, ACK_STOP_DONE, 0, "停止", StartRejected)

    async def reset(self) -> None:
        """§5.3 CMD_RESET：清报警、回待机 → 等 ACK_RESET_DONE（注入异常后复位重试用）。"""
        await self._pulse(CMD_RESET, ACK_RESET_DONE, 0, "复位", StartRejected)

    async def _await_bits_cleared(self, key: str, mask: int, timeout: float, what: str) -> int:
        """等回读键 ``key`` 的指定位**全部清零**；形状照抄 ``_await_bits``（清事件→查条件→再等），
        只把判据换成 ``not (value & mask)``——那边的判据表达不了「等清零」（蓝图 §6.2 授权新增）。"""
        deadline = time.monotonic() + timeout
        while True:
            self._notify.clear()
            value = self._buffer.integer(key)
            if not (value & mask):
                return value
            left = deadline - time.monotonic()
            if left <= 0:
                raise AckTimeout(f"等 {what} 超时 {timeout} s（§9.1 超时表）")
            try:
                await asyncio.wait_for(self._notify.wait(), left)
            except asyncio.TimeoutError:
                pass

    async def pause(self) -> None:
        """§5.3 CMD_PAUSE：置位 → 等 ``status`` 的 ST_PAUSED 出现 → 清命令位。

        ⚠️ 暂停/继续**没有专属 ACK 位**（ACK 表只有 LOAD/START/STOP/RESET/HOME）⇒ 只能等 ``status``
        字；超时走现成 ``AckTimeout``（§9.1 超时表口径，⛔ 不造新错误类型）。清零放 finally——
        超时/被拒也照清（§9.3-② 脉冲语义，同 ``_pulse`` 铁律：留着置位会把 PLC 卡在非法态）。"""
        try:
            await self._write("cmd", CMD_PAUSE)
            await self._await_bits("status", ST_PAUSED, ACK_TIMEOUT_S, "ST_PAUSED")
        finally:
            await self._write("cmd", 0)

    async def resume(self) -> None:
        """§5.3 CMD_RESUME：等 ``status`` 的 ST_PAUSED **清零**（铁律同 ``pause``）。"""
        try:
            await self._write("cmd", CMD_RESUME)
            await self._await_bits_cleared("status", ST_PAUSED, ACK_TIMEOUT_S, "ST_PAUSED 清零")
        finally:
            await self._write("cmd", 0)

    async def run(self, path: Sequence[Segment], *, speed_override: float = SPEED_OVERRIDE_FULL,
                  done_timeout: float = DONE_TIMEOUT_S) -> Frame:
        """走完 §9.1 的九步（步骤 7 的 20 Hz 回读由订阅持续承担，不在此处）。

        步骤 9 补**审计日志**（谁／何时／哪条轨迹／结果）。「谁」在本期只有软件自身，故记会话端点；
        接入登录体系后由上层把操作者传进来，此处不臆造身份。
        """
        count = await self.load(path, speed_override=speed_override)
        await self.start()
        frame = await self.wait_done(done_timeout)
        log.info("审计：%s SeqID=%d 于 %s 下发 %d 段、倍率 %.1f%% → ST_DONE（CurSeg=%d）",
                 self.endpoint, self._seq_id, time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
                 count, speed_override, frame.cur_seg)
        return frame
