"""comm.plc_logic —— PLC 侧逻辑：命令应答、取值校验、虚拟执行推进、故障注入（T09 模拟器的混入基类）。

从 ``comm/simulator.py`` 拆出（该件实测 404 行，超 04 §4.5-① 的 300 行上限）：那边管**连接与地址空间**
（Server 装配、镜像节点树、循环扫描），本件管**协议语义**（契约 §9.1／§9.2 的 Cmd→Ack、§5.1／§5.2 的取值
校验、§6.2／§6.3／§6.4 的位翻转）。手法与客户端侧一致——``comm/opcua_client/handshake.py`` 也是
``Session`` 的混入基类，两边对称好读。

状态字段（``_pos``／``_status``／``_ack``／``_plan`` …）由 ``PlcSimulator.__init__`` 建立，本件只读写不
声明；``TYPE_CHECKING`` 块里补注解仅为静态检查看得见形状，运行时不产生任何约束。

⚠️ **命令字按脉冲语义消费（§9.3-②）**：只在 ``Cmd != 0`` 时动作，``Cmd`` 归零即清 ``Ack``——契约未定谁清
Ack，本模拟器选在归零时清，保证每轮脉冲从干净状态起；真机口径以 PLC 侧实现为准。

⚠️ **禁外推（§9.3-③）**：``_advance`` 只在段计划时长内取曲线值，跑完即钳在终点，绝不预测下一段或倒推。
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

from comm.opcua_client import (ACK_HOME_DONE, ACK_LOAD_NG, ACK_LOAD_OK, ACK_RESET_DONE,
                               ACK_START_NG, ACK_START_OK, ACK_STOP_DONE, ALARM_RANGE, BLEND_EXACT,
                               BLEND_SMOOTH, CMD_HOME, CMD_LOAD, CMD_PAUSE, CMD_RESET, CMD_RESUME,
                               CMD_START, CMD_STOP, MOTION_ABS, MOTION_REL, SEG_CIRC, SEG_LIN,
                               SEG_PTP, SEG_SLOTS, SPEED_OVERRIDE_FULL, SPEED_OVERRIDE_MIN,
                               ST_ALARM, ST_DONE, ST_HOMED, ST_IDLE, ST_PAUSED, ST_READY,
                               ST_RUNNING, unpack_segments)
from comm.virtual_motion import Step, build_plan

if TYPE_CHECKING:
    from asyncua import Server

log = logging.getLogger(__name__)

# 故障注入种类（T09 完成标准第 4 条与异常路径自测用）。
FAULT_REJECT, FAULT_TIMEOUT, FAULT_DISCONNECT = "reject", "timeout", "disconnect"
FAULTS = (FAULT_REJECT, FAULT_TIMEOUT, FAULT_DISCONNECT)


class PlcLogic:
    """``PlcSimulator`` 的协议语义半边。单独实例化无意义（没有地址空间可读写）。"""

    if TYPE_CHECKING:                      # 运行时由 PlcSimulator.__init__ 建立，此处仅供静态检查
        cfg: Any
        axis_slots: int
        seg_bytes: int
        _live: bool
        _server: Server
        _pos: list[float]
        _vel: list[float]
        _status: int
        _ack: int
        _alarm: int
        _seq_id: int
        _cur_seg: int
        _plan: tuple[Step, ...]
        _step: int
        _elapsed: float

    def __init__(self) -> None:
        self._fault: str | None = None
        self._fault_left = 0
        self._fault_alarm = ALARM_RANGE
        self._cmd_prev = 0

    # ── 命令处理（契约 §9.1／§9.2） ───────────────────────────────────────────────────────

    def _handle_cmd(self, dl: Mapping[str, Any]) -> None:
        """消费一个扫描周期里的命令字，**按上升沿触发**（真 PLC 的 R_TRIG 口径）。

        ⚠️ 不能按电平触发：§9.3-② 的脉冲语义是「软件置位 → 收到应答后清零」，而清零最快也要一个扫描
        周期才回到这里，故同一位必然被连扫两轮以上。实测按电平触发时一次「启动」被执行两遍——第二遍因
        ``ST_READY`` 已被第一遍清掉而回 ``ACK_START_NG``（日志 ``启动被拒：Status=0x80``），客户端整轮
        握手白跑。沿触发后一轮命令只作用一次，与真机行为一致。
        """
        cmd = int(dl["cmd"] or 0)
        edge = cmd & ~self._cmd_prev
        self._cmd_prev = cmd
        if cmd == 0:
            self._ack = 0
            return
        if self._fault == FAULT_TIMEOUT and self._fault_left > 0:
            self._fault_left -= 1        # 吞掉应答：模拟 PLC 忙／链路半死，客户端应触发 2 s 超时
            log.info("故障注入 timeout：本周期吞掉应答（剩余 %d 次）", self._fault_left)
            return
        self._seq_id = int(dl["seq_id"] or 0)      # §6.1 SeqID＝回显软件写入的序号
        if edge & CMD_LOAD:
            self._on_load(dl)
        if edge & CMD_START:
            self._on_start()
        if edge & CMD_STOP:
            self._halt(ACK_STOP_DONE)
        if edge & CMD_PAUSE:
            self._status |= ST_PAUSED
        if edge & CMD_RESUME:
            self._status &= ~ST_PAUSED
        if edge & CMD_RESET:
            self._alarm, self._ack = 0, ACK_RESET_DONE
            self._status = (self._status & ~(ST_ALARM | ST_DONE | ST_PAUSED)) | ST_IDLE
        if edge & CMD_HOME:
            # 不建模回零轨迹：§7.5 的机械零点定义与回零开关位置均待确认，猜轨迹即越权。
            self._ack, self._status = ACK_HOME_DONE, self._status | ST_HOMED

    def _on_load(self, dl: Mapping[str, Any]) -> None:
        """§9.1 步骤 1–4：校验 → 通过置 READY＋ACK_LOAD_OK；不通过置 ALARM＋NG＋报警位（§6.4）。"""
        alarm = self._validate(dl)
        if self._fault == FAULT_REJECT and self._fault_left > 0:
            self._fault_left -= 1
            alarm |= self._fault_alarm   # 故障注入：给客户端「被拒＋原因位」，而不是让它干等超时
        if alarm:
            self._alarm |= alarm
            self._ack |= ACK_LOAD_NG
            self._status = (self._status & ~ST_READY) | ST_ALARM
            log.info("装载被拒：AlarmWord=%#06x", self._alarm)
            return
        count = int(dl["seg_count"] or 0)
        self._plan = build_plan(unpack_segments(dl["seg_array"], self.axis_slots, count),
                                self._pos, float(dl["speed_override"] or 0.0), self.cfg.limits)
        self._step, self._elapsed, self._cur_seg = 0, 0.0, 0
        self._status = (self._status & ~ST_DONE) | ST_READY
        self._ack |= ACK_LOAD_OK
        log.info("装载通过：%d 段，总时长 %.3f s，段长 %d B", count, self._total_span(),
                 self.seg_bytes)

    def _validate(self, dl: Mapping[str, Any]) -> int:
        """§5.1／§5.2 的取值范围与载荷长度校验，返回报警位（0＝通过，命中 ``ALARM_RANGE`` 数据越界）。

        ⚠️ **软限位与行程不在此校验**：``Pos[i]`` 槽位 ↔ machine.yaml 轴 id 的映射待 `附录 A`／
        `契约 Q-11` 回执（现配置 22 轴塞不进契约的 8 槽位），自造映射即越权，已登记为 T09 遗留问题。
        """
        count = int(dl["seg_count"] or 0)
        override = float(dl["speed_override"] or 0.0)
        payload = dl["seg_array"] or b""
        if not 1 <= count <= SEG_SLOTS or \
                not SPEED_OVERRIDE_MIN <= override <= SPEED_OVERRIDE_FULL or \
                len(payload) != self.seg_bytes * SEG_SLOTS:
            return ALARM_RANGE
        for seg in unpack_segments(payload, self.axis_slots, count):
            if seg.seg_type not in (SEG_PTP, SEG_LIN, SEG_CIRC) or \
                    seg.motion_mode not in (MOTION_ABS, MOTION_REL) or \
                    seg.blend_mode not in (BLEND_EXACT, BLEND_SMOOTH) or \
                    not all(math.isfinite(value) for value in seg.pos):
                return ALARM_RANGE
        return 0

    def _on_start(self) -> None:
        """§9.1 步骤 5–6：未就绪／报警中一律拒启动（``ACK_START_NG``），就绪才转 RUNNING。

        不以 ``ST_HOMED`` 为前置：§7.5 的零点定义待确认，模拟器无权替真机定「未回零不得启动」。
        """
        if not (self._status & ST_READY) or self._status & ST_ALARM or not self._plan:
            self._ack |= ACK_START_NG
            self._status &= ~ST_RUNNING
            log.info("启动被拒：Status=%#04x，AlarmWord=%#06x，已装载 %d 段",
                     self._status, self._alarm, len(self._plan))
            return
        self._ack |= ACK_START_OK
        self._status = (self._status & ~(ST_READY | ST_DONE | ST_IDLE)) | ST_RUNNING
        self._step, self._elapsed, self._cur_seg = 0, 0.0, 0
        log.info("启动：%d 段，预计 %.3f s", len(self._plan), self._total_span())

    def _halt(self, ack_bit: int) -> None:
        """§9.2：``CMD_STOP`` → 立即停在当前点（不建模减速段，模拟器口径）→ ``ACK_STOP_DONE``。"""
        self._status = (self._status & ~(ST_RUNNING | ST_PAUSED | ST_READY)) | ST_IDLE
        self._plan, self._vel = (), [0.0] * self.axis_slots
        self._ack |= ack_bit

    # ── 虚拟执行推进 ──────────────────────────────────────────────────────────────────────

    def _advance(self, dt: float) -> None:
        """推进虚拟执行：按上轮实测周期走曲线，到点切下一段；走完置 DONE 并钳在终点（禁外推）。"""
        if not (self._status & ST_RUNNING) or self._status & ST_PAUSED or not self._plan:
            return
        self._elapsed += dt
        while self._step < len(self._plan) and self._elapsed >= self._plan[self._step].duration:
            self._elapsed -= self._plan[self._step].duration
            self._step += 1
        if self._step >= len(self._plan):
            self._finish()
            return
        self._cur_seg = self._step            # §6.1 CurSeg：本模拟器按 0 起算的段序回读
        for slot, (position, speed) in enumerate(self._plan[self._step].sample(self._elapsed)):
            self._pos[slot], self._vel[slot] = position, speed

    def _finish(self) -> None:
        """轨迹正常结束：钳在终点、速度归 0、清 RUNNING、置 DONE（§6.2 bit4）。"""
        last = self._plan[-1]
        for slot, (position, _) in enumerate(last.sample(last.duration)):
            self._pos[slot], self._vel[slot] = position, 0.0
        self._cur_seg = len(self._plan) - 1
        self._status = (self._status & ~ST_RUNNING) | ST_DONE
        log.info("轨迹结束：%d 段跑完，终点 %s", len(self._plan),
                 [round(value, 3) for value in self._pos])

    def _total_span(self) -> float:
        """已装载计划的总时长（秒），只为日志可读——不写死任何工艺数字。"""
        return sum(step.duration for step in self._plan)

    # ── 故障注入 ──────────────────────────────────────────────────────────────────────────

    def inject_fault(self, kind: str, *, alarm: int = ALARM_RANGE, cycles: int = 1) -> None:
        """注入故障：``reject``（下次装载给 NG＋报警位）／``timeout``（吞应答）／``disconnect``（停 Server）。

        ⚠️ 须在事件循环内调用（``disconnect`` 靠 ``create_task`` 排停机协程）。``cycles`` 只对前两种有效。
        """
        if kind not in FAULTS:
            raise ValueError(f"故障种类 {kind!r} 不在 {'／'.join(FAULTS)} 内")
        self._fault, self._fault_left, self._fault_alarm = kind, cycles, alarm
        log.info("注入故障 %s（alarm=%#06x，cycles=%d）", kind, alarm, cycles)
        if kind == FAULT_DISCONNECT:
            asyncio.create_task(self._drop_link())

    async def _drop_link(self) -> None:
        """断链：先停扫描再关 Server——客户端应在 5 s 内判离线（T09 完成标准第 4 条）。"""
        self._live = False
        await self._server.stop()
        log.info("已停机（模拟断链）")
