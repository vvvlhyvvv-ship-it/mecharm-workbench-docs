"""comm.simulator —— OPC UA Server 形态的 PLC 模拟器（T09 步骤 1／2／3）。

Q 回执冻结前禁连真 PLC（D-6），故本模块用 asyncua 的 Server 在 **127.0.0.1 自环**里冒充 PLC：收下发块 →
虚拟执行 → 按发布周期回读。它与 ``comm/opcua_client`` 共用同一份协议常量（段布局、命令字位、状态／应答／
报警位），两端不会各写一套走偏。

职责切分（本件实测 404 行、拆一次后仍 322 行，均超 04 §4.5-① 的 300 行上限，故按 §4.5-②③ 的
「去重复→抽函数→拆文件」拆为四件，本件收在 **263 行**——含命令行 ``--config``／``--fault`` 两个自测口子）：

    simulator.py       本件：Server 装配、循环扫描与逐周期 I/O、Windows 计时精度、命令行入口
    plc_nodes.py       地址空间镜像：按 machine.yaml 的 NodeId 字符串建树、上行块 PLC 类型表、形状校验
    plc_logic.py       协议语义：契约 §9.1／§9.2 的 Cmd→Ack、§5.1／§5.2 校验、推进与 DONE、故障注入
    virtual_motion.py  PLC 侧「虚拟执行」的梯形曲线与段计划（§3.2 把插补划给 PLC，故不在客户端侧）

三条口径：
- **节点树全部由 machine.yaml 反推**：``read_nodes``／``write_nodes`` 的 NodeId 字符串逐个 ``from_string``
  建成镜像节点（按 ``"DB"."Var"`` 拆出 DB 名建文件夹），代码里**不出现任何符号名字面量**——改点表只改
  配置文件（T09 完成标准第 5 条）。
- **段长实算不写死**：取 ``write.seg_layout`` 的 ``struct.calcsize``（``v1_2_8axis`` 实测 56 B）；契约 V1.3
  扩槽位后本模块自动跟着变，未冻结的 profile 直接拒启动（``axis_slots_of`` 抛 CommError）。
- **循环扫描而非 Server 内部订阅**：按 ``publish_interval_ms`` 跑「读下发 → 处理命令 → 推进 → 发布」，
  形态对齐真 PLC 的循环 OB，节拍可控可测（完成标准第 3 条的 ≥20 Hz 由此产生）。

**不做的两件事**（均属回执未冻结，做了就是抢答）：
① **软限位／行程校验**——``Pos[i]`` 槽位 ↔ machine.yaml 轴 id 的映射待 `附录 A`／`契约 Q-11`（现配置 22
   轴塞不进契约的 8 槽位），自造映射即越权，已登记为 T09 遗留问题；
② ``ModeMask``／``EnableMask``／``SyncErr``／``Timestamp`` 四节点（契约 §6.1 偏移 76／77／80／84）——
   2026-09-16 G17 裁决「本轮不加」，需要时停下汇报。

段数组 ``seg_array`` 的载荷按 **S7 原生大端**解（同 ``comm/opcua_client/write.py`` 的口径与理由）：它是
不透明 ByteString，Server 无从按 §4.3 自动转字节序，必须自定序；自环两端同码故功能无差。
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import ctypes
import logging
import time
from typing import Any

from asyncua import Server, ua

from comm.opcua_client import MS_PER_S, ST_COMM_OK, ST_IDLE, axis_slots_of, seg_layout
from comm.plc_logic import FAULTS, FAULT_DISCONNECT, FAULT_REJECT, FAULT_TIMEOUT, PlcLogic
from comm.plc_nodes import PUBLISH_NODE_TYPES, NodeMirror
from comm.virtual_motion import Step
from core.config import REPO_ROOT, MachineConfig, load_machine

log = logging.getLogger(__name__)

# 派单卡点名的交付件是本文件，故把混入基类那半边的故障注入种类一并再导出（调用方写
# `from comm.simulator import PlcSimulator, FAULT_DISCONNECT` 即可，不必知道内部拆分）。
__all__ = ["PlcSimulator", "serve", "main", "raise_timer_resolution", "lower_timer_resolution",
           "PUBLISH_NODE_TYPES", "INT32_MAX", "CONFIG_PATH", "TIMER_PERIOD_MS",
           "FAULTS", "FAULT_REJECT", "FAULT_TIMEOUT", "FAULT_DISCONNECT"]

INT32_MAX = 2 ** 31 - 1          # §6.1 Heartbeat 为 DINT：到顶回绕，不让它变负数
CONFIG_PATH = "config/machine.yaml"  # `python -m comm.simulator` 的默认配置（相对仓根）
TIMER_PERIOD_MS = 1              # Windows 计时器分辨率（进程级计时精度，非轴参数；实测依据见下）
RATE_LOG_CYCLES = 200            # 每多少周期打一行自计频率；50 ms 周期下即 10 s 一行（依据见 _scan）


def raise_timer_resolution() -> bool:
    """Windows：把系统计时器精度提到 1 ms，返回是否真的提过（供 ``lower_timer_resolution`` 配对还原）。

    实测依据：不提精度时 50 ms 周期只跑到 **18.91 Hz**，提到 1 ms 后服务端扫描与客户端收帧同为
    **20.10 Hz**——损耗全在 ``asyncio.sleep`` 的计时粒度，不在订阅链。

    ⚠️ 这是**模拟器进程**的局部处置：真 PLC 的循环 OB 由硬件定时器保证，不存在这个问题；客户端侧也不需要
    它（订阅推送由 Server 驱动，客户端只是被动收）。非 Windows 平台没有 ``ctypes.windll``，直接跳过。
    """
    winmm = getattr(getattr(ctypes, "windll", None), "winmm", None)
    if winmm is None:
        return False
    winmm.timeBeginPeriod(TIMER_PERIOD_MS)
    return True


def lower_timer_resolution() -> None:
    """还原计时器精度（与 ``raise_timer_resolution`` 配对；未提过则什么都不做）。"""
    winmm = getattr(getattr(ctypes, "windll", None), "winmm", None)
    if winmm is not None:
        winmm.timeEndPeriod(TIMER_PERIOD_MS)


class PlcSimulator(PlcLogic):
    """冒充 PLC 的 OPC UA Server；协议语义那半边在混入基类 ``PlcLogic``。

    用法：``sim = PlcSimulator(cfg)`` → ``await sim.start()`` → …… → ``await sim.stop()``。
    ``endpoint`` 传空串即用 machine.yaml 里的地址；自测传临时端口，免与常驻模拟器抢 4840——但仍必须是
    127.0.0.1（D-6）。
    """

    def __init__(self, cfg: MachineConfig, endpoint: str = "") -> None:
        super().__init__()
        opcua = cfg.opcua
        self.cfg = cfg
        self.endpoint = endpoint or opcua.endpoint_url
        self.axis_slots = axis_slots_of(opcua.pack_profile)
        self.seg_fmt, self.seg_bytes = seg_layout(self.axis_slots)
        self._period = opcua.publish_interval_ms / MS_PER_S
        self._ns = opcua.ns_index
        self._server = Server()
        self._task: asyncio.Task | None = None
        self._live = False
        self._timer_raised = False
        self._rd: dict[str, list[ua.NodeId]] = {}
        self._wr: dict[str, ua.NodeId] = {}
        self._pos = [0.0] * self.axis_slots
        self._vel = [0.0] * self.axis_slots
        self._status = ST_IDLE | ST_COMM_OK
        self._ack = 0
        self._alarm = 0
        self._seq_id = 0
        self._cur_seg = 0
        self._heartbeat = 0
        self._stalls = 0
        self._plan: tuple[Step, ...] = ()
        self._step = 0
        self._elapsed = 0.0

    # ── 起停与节点树 ──────────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """起 Server → 建镜像节点树 → 起扫描任务。重复调用无效（幂等）。"""
        if self._live:
            return
        await self._server.init()
        self._server.set_endpoint(self.endpoint)
        self._server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        mirror = NodeMirror(self._server, self._ns, self.axis_slots)
        self._rd, self._wr = await mirror.build(self.cfg.opcua.read_nodes,
                                                self.cfg.opcua.write_nodes)
        await self._server.start()
        self._live = True
        self._timer_raised = raise_timer_resolution()
        self._task = asyncio.create_task(self._scan())
        log.info("PLC 模拟器已起 %s：ns=%d，槽位 %d 个，段长实测 %d B，周期 %.0f ms",
                 self.endpoint, self._ns, self.axis_slots, self.seg_bytes, self._period * MS_PER_S)

    async def stop(self) -> None:
        """停扫描 → 关 Server。幂等：断链注入已关过一次，再调不得抛给调用方。"""
        self._live = False
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        with contextlib.suppress(Exception):
            await self._server.stop()
        if self._timer_raised:
            self._timer_raised = False
            lower_timer_resolution()

    # ── 循环扫描与逐周期 I/O ──────────────────────────────────────────────────────────────

    async def _scan(self) -> None:
        """循环 OB：读下发 → 处理命令 → 推进 → 发布，然后睡到**下一个绝对截止时刻**。

        不用「睡满剩余时间」：实测 Windows 下 ``asyncio.sleep`` 每轮都系统性超出若干毫秒，按剩余时间睡会让
        超出逐周期累积——50 ms 周期实测只跑到 18.91 Hz（完成标准第 3 条要 ≥20 Hz）。锚在绝对截止时刻上，
        单次超出会被下一轮自动吸收，平均频率收敛到 ``publish_interval_ms`` 的标称值。

        落后超过一个周期时**重置基准而不补扫**：补扫等于把过去的周期外推回来（与 §9.3-③ 禁外推同源），
        且推进量取实测间隔，位置不会跳变。

        每 ``RATE_LOG_CYCLES`` 个周期打一行**扫描自计频率**（累计周期数 ÷ 本进程单调钟跨度）：客户端那侧的
        测频要经过 asyncua 的批量推送，端点带抖动；本行只用服务端自己的钟，是完成标准第 3 条「≥20 Hz」不受
        推送影响的旁证。**按周期打而非停机时打**：子进程通常被 ``terminate()`` 结束（Windows 下即
        TerminateProcess，不抛 CancelledError），放 finally 里就永远打不出来。
        """
        began_all = last = time.monotonic()
        deadline = last + self._period
        cycles = 0
        while self._live:
            began = time.monotonic()
            try:
                self._handle_cmd(self._read_downlink())
                self._advance(began - last)
                await self._publish()
            except Exception as caught:            # 单周期出错不停机：真 PLC 也不会因一帧坏数据死机
                log.warning("扫描周期出错（已跳过本周期）：%s: %s", type(caught).__name__, caught)
            cycles += 1
            if cycles % RATE_LOG_CYCLES == 0:
                elapsed = time.monotonic() - began_all
                log.info("扫描自计：%d 周期／%.3f s → %.4f Hz（服务端钟，不含推送抖动；落后 %d 次）",
                         cycles, elapsed, cycles / elapsed, self._stalls)
            last = began
            deadline += self._period
            now = time.monotonic()
            if deadline <= now:
                self._stalls += 1
                log.warning("扫描落后 %.0f ms（超出一个周期），重置基准不补扫", (now - deadline) * MS_PER_S)
                deadline = now + self._period
            await asyncio.sleep(deadline - now)

    def _read_downlink(self) -> dict[str, Any]:
        """把 §5.1 的下发块整体读回来——**按 NodeId 读，不按字节偏移**（§3.3）。

        ⚠️ ``Server.read_attribute_value`` 实测是**同步**方法（返回 DataValue），``await`` 它会抛
        TypeError 并让整轮扫描空转；写侧的 ``write_attribute_value`` 才是协程。
        """
        out: dict[str, Any] = {}
        for key, nodeid in self._wr.items():
            out[key] = self._server.read_attribute_value(nodeid).Value.Value
        return out

    async def _publish(self) -> None:
        """把 §6.1 的回读块整体写回地址空间。心跳每周期 +1（§9.1 步骤 7），客户端据此测频率与判新鲜度。"""
        self._heartbeat = (self._heartbeat + 1) % INT32_MAX
        batch = [(nodeid, value, PUBLISH_NODE_TYPES[key])
                 for key, nodeids in self._rd.items() for nodeid, value in
                 zip(nodeids, self._values_of(key))]
        await asyncio.gather(*(self._write_one(*item) for item in batch))

    def _values_of(self, key: str) -> tuple:
        """配置键 → 该键本轮要发布的值（数组键给整列）。键名取自 machine.yaml，不是 PLC 符号名。"""
        if key == "axis_pos":
            return tuple(self._pos)
        if key == "axis_vel":
            return tuple(self._vel)
        scalars = {"status": self._status, "ack": self._ack, "alarm_word": self._alarm,
                   "seq_id": self._seq_id, "cur_seg": self._cur_seg, "heartbeat": self._heartbeat}
        return (scalars[key],)

    async def _write_one(self, nodeid: ua.NodeId, value: Any, vtype: ua.VariantType) -> None:
        await self._server.write_attribute_value(nodeid, ua.DataValue(ua.Variant(value, vtype)))


async def serve(cfg: MachineConfig, endpoint: str = "", fault: str | None = None) -> None:
    """常驻跑模拟器（双进程自测的「PLC 侧进程」）；取消任务或 Ctrl-C 即优雅停机。

    ``fault`` 非空则起来即注入（``tools/comm_selftest.py`` 与 T10 的双进程注入用），省去为了注一次故障
    而另开一条进程内通道。
    """
    sim = PlcSimulator(cfg, endpoint)
    await sim.start()
    if fault is not None:
        sim.inject_fault(fault)
    try:
        while True:
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        log.info("收到取消，停机中")
    finally:
        await sim.stop()


def main(argv: list[str] | None = None) -> int:
    """``python -m comm.simulator [endpoint] [--config PATH] [--fault reject|timeout]``。

    ``--config`` 供换点表演示（完成标准第 5 条：另一份 NodeId 表、代码零改动）；``--fault`` 供双进程注入。
    ``disconnect`` **不进 CLI 选项**：起来即断链等于客户端根本连不上，验不到「运行中断线→5 s 判离线」，
    该种故障只能在进程内 ``inject_fault`` 注（或直接 kill 子进程，自测脚本走的是后者）。
    """
    parser = argparse.ArgumentParser(description="PLC 模拟器（OPC UA Server，仅 127.0.0.1 自环）")
    parser.add_argument("endpoint", nargs="?", default="",
                        help="覆写端点；缺省用 machine.yaml 里 opcua.endpoint_url 的地址")
    parser.add_argument("--config", default=str(REPO_ROOT / CONFIG_PATH), help="machine.yaml 路径")
    parser.add_argument("--fault", choices=(FAULT_REJECT, FAULT_TIMEOUT), default=None,
                        help="起来即注入的故障种类")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s.%(msecs)03d %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S")
    # asyncua 自身在 INFO 级会刷出上百行建树噪声（实测），压到 WARNING 才看得见模拟器的关键日志。
    logging.getLogger("asyncua").setLevel(logging.WARNING)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(serve(load_machine(args.config), args.endpoint, args.fault))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
