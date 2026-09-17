"""app.linkctl —— OPC UA 会话的壳侧宿主：asyncio 循环跑在独立 QThread，跨界只走 Qt 信号。

**为什么要有这一层**：`comm` 全链是 asyncio（`connect()`／`Session.load()` 都是协程），壳是 Qt 事件循环；
依赖表里**没有** qasync／quamash（`environment.yml` 与 `requirements.lock.txt` 对本单只读，⛔ 自行装包属
派单卡 §5 禁项）⇒ 唯一接法是把 asyncio 循环放进一条自己的线程，两边各转各的。先例＝
`app/steps/step1_import.py` 的 `ImportWorker(QThread)`（那边扛的是 OCC 导入的重活）。

线程纪律（本件的复杂度全在这里）：
  - `on_frames`／`on_state` 由 asyncua 在**循环线程**里同步调用 ⇒ 回调体内 ⛔ 不碰任何 QWidget、⛔ 不碰
    主线程的状态，只 `Signal.emit(...)`（跨线程自动排队到主线程执行）。
  - 主线程要驱动会话 ⇒ 一律经 `submit()`（`asyncio.run_coroutine_threadsafe`），⛔ 不在主线程 await。
  - 停机顺序固定：关会话（协程、幂等）→ 关模拟器 → 停循环 → 等线程退出。反序会把 asyncua 的任务留在
    已关闭的循环上，表现为退出时刷一屏 `Event loop is closed`。

⛔ **只连 127.0.0.1 的本机模拟器**（D-6：Q 回执冻结前禁连真 PLC，联调归现场 S-7/S-8）。故本件**不提供**
「连真机」入口：`start()` 恒在进程内起 `comm.simulator.PlcSimulator` 再连它，端口向系统要空闲的（免与
常驻模拟器抢 4840，手法同 `tools/comm_selftest_kit.py::free_endpoint`，但 ⛔ 不 import tools——app 层
不得依赖工具层）。真机接入属现场单，届时把 `start()` 的「起模拟器」两步删掉即可，调用方形态不变。

握手五段进度（卡片步骤①）与契约 §9.1 九步的对应，见 `STAGES` 常量处的表。
"""

from __future__ import annotations

import asyncio
import logging
import socket
import threading
from collections.abc import Coroutine, Sequence

from PySide6.QtCore import QObject, QThread, Signal

from comm.opcua_client import LinkState, Rejected, connect
from comm.opcua_client.write import Segment
from comm.simulator import PlcSimulator
from core.config.schema import MachineConfig

log = logging.getLogger(__name__)

LOOP_READY_S = 10.0        # 事件循环线程起不来的判定门槛（软件启动时序，非机台参数）
HOST = "127.0.0.1"         # D-6：只许本机自环

# 五段进度 ↔ 契约 §9.1 九步（步 7 的 20 Hz 回读由订阅持续承担，不占一段）：
#   1 组装下发块        ＝ 本层之前的 `app/sendseg.build_segments`（纯计算，无 I/O）
#   2 写出并请求装载    ＝ 步 1–2（`Session.load` 内含 `write_segments`＋SeqID+1＋置 CMD_LOAD）
#   3 PLC 校验并接受    ＝ 步 3–4（`load` 正常返回即 ACK_LOAD_OK 且 SeqID 回显一致；NG 抛 Rejected）
#   4 执行中            ＝ 步 5–7（`Session.start` → ACK_START_OK → ST_RUNNING，段序随回读帧走）
#   5 轨迹完成          ＝ 步 8–9（`Session.wait_done` 等 ST_DONE；审计行由调用方给出、本层落日志）
STAGES: tuple[str, ...] = ("组装下发块", "写出下发块并请求装载", "PLC 校验并接受", "执行中", "轨迹完成")


class LinkError(Exception):
    """链路侧失败：消息即人话（可直上屏）。comm 的异常另由 `tell()` 转人话。"""


def tell(exc: BaseException) -> str:
    """异常 → 人话＋**原因码**（卡片步骤④「PLC 拒绝→红条＋原因码」）。

    原因码＝契约 §6.4 的 `AlarmWord` 位（十六进制原值），中文说明由 `Rejected.reasons` 给（comm 层已按
    `ALARM_TEXT` 译好）。⛔ 不把 traceback 塞给操作员，也 ⛔ 不吞原因码——报警字为 0 时照 comm 的口径
    明说「PLC 未给出原因位」，⛔ 不替它猜原因。
    """
    if isinstance(exc, Rejected):
        return f"{exc}｜原因码 AlarmWord=0x{exc.alarm:04x}"
    if isinstance(exc, asyncio.CancelledError):
        return "本次请求已被取消（停机或链路重建）"
    return f"{type(exc).__name__}：{exc}"


def free_endpoint() -> str:
    """向系统要一个空闲端口拼成 endpoint（仍限 127.0.0.1，D-6）。"""
    with socket.socket() as probe:
        probe.bind((HOST, 0))
        return f"opc.tcp://{HOST}:{probe.getsockname()[1]}"


class _LoopThread(QThread):
    """承载 asyncio 事件循环的线程。`loop` 属性会等到循环真的转起来才返回（免竞态提交）。"""

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._up = threading.Event()

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """⚠️ 先等就绪事件、后取 `_loop`：反过来写（`_loop is None or not _up.wait(...)`）会**短路**——`submit()`
        紧跟 `start()` 调、主线程几乎必然先到，于是 `_loop` 还没赋上就抛「线程没就绪」，看着像线程起不来、其实是
        判据写反了（T10 实测踩过）。`run()` 先赋 `_loop` 再 `_up.set()` ⇒ 事件一到 `_loop` 必非空。"""
        if not self._up.wait(LOOP_READY_S):
            raise LinkError(f"事件循环线程在 {LOOP_READY_S:g} s 内没有就绪，无法连接或下发")
        return self._loop

    def run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._up.set()
        try:
            self._loop.run_forever()
        finally:
            _drain(self._loop)
            self._loop.close()
            asyncio.set_event_loop(None)

    def halt(self) -> None:
        """从主线程停循环（`call_soon_threadsafe` 是跨线程唯一安全入口）。"""
        if self._loop is not None and self._up.is_set():
            self._loop.call_soon_threadsafe(self._loop.stop)


def _drain(loop: asyncio.AbstractEventLoop) -> None:
    """停循环后清掉残留任务：asyncua 的订阅／重连任务不取消就会在 close 时报「任务被销毁但仍挂起」。"""
    pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
    for task in pending:
        task.cancel()
    if pending:
        loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))


class LinkController(QObject):
    """会话宿主。信号一律在主线程消费；⛔ 槽函数之外不得直接读本对象的会话状态（那属循环线程）。"""

    frames = Signal(object)        # list[Frame]：一帧或一批回读（联动跟随的数据源）
    link_state = Signal(object)    # LinkState：ONLINE／STALE／OFFLINE（顶栏在线灯＋联动冻结）
    stage = Signal(int, str)       # (阶段号 2..5, 人话)；阶段 1 由调用方自己标（纯计算，不过本层）
    said = Signal(str)             # 人话日志 → 状态栏
    failed = Signal(str)           # 人话异常 → 右栏红条（含原因码）
    up = Signal(bool)              # 会话是否可用 → ⑤ 页按钮门禁
    done = Signal(bool)            # 一次下发结束（True＝走完 ST_DONE）→ ⑤ 页收尾＋解「在途」锁

    def __init__(self, pathctl, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pathctl = pathctl          # 只为取**同一份**机台配置（⛔ 不再各自 load_machine）
        self._thread: _LoopThread | None = None
        self._session = None
        self._sim: PlcSimulator | None = None
        self._endpoint = ""
        self._busy = False
        self.done.connect(self._on_done)      # 自连：锁的释放必须在主线程（`_busy` 是主线程读的那一份）

    # --- 状态（只读快照；真值在循环线程，故这里给的是「主线程已知的那一份」）----------- #
    @property
    def endpoint(self) -> str:
        return self._endpoint

    @property
    def is_up(self) -> bool:
        return self._session is not None and not self._session.closed

    @property
    def is_busy(self) -> bool:
        """一次下发在途 ⇒ 禁重复下发（两个 SeqID 交错会让 PLC 侧的段块与序号对不上）。"""
        return self._busy

    # --- 起停 --------------------------------------------------------------- #
    def start(self) -> None:
        """起本机模拟器并连它（人话进度经 `said`／`up`）。已连上则什么都不做（幂等）。"""
        if self.is_up:
            self.said.emit(f"已经连着了（{self._endpoint}），不必重复连接")
            return
        cfg = self._config()
        if cfg is None:
            return
        self._endpoint = free_endpoint()
        if self._thread is None or not self._thread.isRunning():
            self._thread = _LoopThread(self)      # 复用还活着的线程：上次连接失败后重试点[连接]是常路，
            self._thread.start()                  # 每次新建就会把旧线程漏成孤儿（stop 只停最新那一条）
        self.submit(self._open(cfg, self._endpoint), what="连接 PLC 模拟器")

    def _config(self) -> MachineConfig | None:
        """机台配置取自步骤③已绑定的那一份；没绑定即人话报错 ⛔ 不自己再 load 一份（两份会走偏）。"""
        cfg = self._pathctl.kinematics()[0]
        if cfg is None:
            self.failed.emit("机台配置还没载入：先在步骤③点[生成路径]，再回步骤⑤连接")
            return None
        return cfg

    async def _open(self, cfg: MachineConfig, endpoint: str) -> None:
        """循环线程内：起模拟器 → 连会话。回读与链路态都转成信号，⛔ 不在这里碰界面。"""
        sim = PlcSimulator(cfg, endpoint)
        await sim.start()
        self._sim = sim
        session = await connect(endpoint, cfg, on_frames=self._rx_frames, on_state=self._rx_state)
        self._session = session
        self.up.emit(True)
        self.said.emit(f"已连接本机 PLC 模拟器 {endpoint}（发布周期 {cfg.opcua.publish_interval_ms:g} ms"
                       f"＝标称 {1000.0 / cfg.opcua.publish_interval_ms:g} Hz）")

    def stop(self) -> None:
        """停机：关会话 → 关模拟器 → 停循环 → 等线程。幂等，且 ⛔ 不把停机期异常抛给操作员。"""
        thread, self._thread = self._thread, None
        if thread is None:
            return
        if self._session is not None:
            try:                    # 同步等：不等就会在循环关掉后漏关 Server，端口留到下次连接才炸
                asyncio.run_coroutine_threadsafe(self._close(), thread.loop).result(LOOP_READY_S)
            except Exception as caught:      # 含「循环没起来」的 LinkError：停机路径一律不冒到界面
                log.warning("停机会话时出错（已忽略）：%s: %s", type(caught).__name__, caught)
        self._session, self._sim, self._busy = None, None, False
        thread.halt()
        thread.wait(int(LOOP_READY_S * 1000))
        self.up.emit(False)
        self.said.emit("已断开 PLC 模拟器，本机回到仿真态")

    async def _close(self) -> None:
        session, sim = self._session, self._sim
        if session is not None:
            await session.close()
        if sim is not None:
            await sim.stop()

    # --- 提交 --------------------------------------------------------------- #
    def submit(self, coro: Coroutine, what: str = "本次操作") -> object:
        """把协程交给循环线程跑；异常一律转成 `failed` 人话（⛔ 不让协程异常静默消失在 future 里）。"""
        try:
            loop = self._thread.loop if self._thread is not None else None
        except LinkError as exc:
            coro.close()
            self.failed.emit(str(exc))
            return None
        if loop is None:
            coro.close()
            self.failed.emit("还没连接 PLC 模拟器：先点[连接本机模拟器]")
            return None

        def _done(future) -> None:            # 跑在循环线程：只发信号，⛔ 不碰界面
            try:
                future.result()
            except Exception as caught:
                log.exception("%s失败", what)
                self.failed.emit(f"{what}失败：{tell(caught)}")

        return asyncio.run_coroutine_threadsafe(coro, loop).add_done_callback(_done)

    # --- 下发（卡片步骤①：写段＋命令字＋五段进度＋执行）---------------------------- #
    def send(self, path: Sequence[Segment], override: float, audit: str) -> None:
        """走 §9.1 的步 1–9（阶段 2–5 经 `stage` 报进度）。⛔ 不用 `Session.run()`：它把四步打包成
        一次调用，界面上就分不出「已装载」与「已启动」——而卡片要的是**五段进度**。审计行由调用方给出
        （它才知道工作模式与路径指纹），本层负责落 `log.info`，与 comm 层 `run()` 的审计同源同格式口径。"""
        if not self.is_up:
            self.failed.emit("还没连接 PLC 模拟器，无法下发：先点[连接本机模拟器]")
            return
        if self._busy:
            self.failed.emit("上一次下发还在途，⛔ 不叠加第二次请求：等它完成或失败后再发")
            return
        self._busy = True
        self.submit(self._handshake(tuple(path), override, audit), what="下发")

    async def _handshake(self, path: tuple[Segment, ...], override: float, audit: str) -> None:
        session = self._session
        ok = False
        try:
            self.stage.emit(2, f"写出下发块并请求装载：{len(path)} 段、倍率 {override:g} %")
            count = await session.load(path, speed_override=override)
            self.stage.emit(3, f"PLC 校验并接受：序号 {session.seq_id} 回显一致，已装载 {count} 段")
            self.stage.emit(4, "已请求启动，等 PLC 转运行态（模型开始跟随实测回读）")
            await session.start()
            frame = await session.wait_done()
            self.stage.emit(5, f"轨迹完成：末段序号 {frame.cur_seg}，模型停在实测终点")
            ok = True
        finally:
            self.done.emit(ok)      # 成败都要解锁「在途」，否则失败一次就再也发不出去
        # 审计行**只落日志**：串里含结论字面与路径指纹（英文／内部编号），而 `said` 是直写状态栏的 ⇒
        # 上屏会撞 02 §4「全中文」。操作员看的完成人话由 `app/sendctl.py` 收到 `done(True)` 时给。
        log.info("审计：%s", audit)

    def abort(self) -> None:
        """§9.2 软件主动停止：置 CMD_STOP → 等 ACK_STOP_DONE。⛔ 不清已装载的段块（那是 CMD_RESET 的事）。"""
        if self._session is None:
            self.failed.emit("还没连接 PLC 模拟器，谈不上停止")
            return
        self.submit(self._stop_motion(), what="停止运动")

    async def _stop_motion(self) -> None:
        await self._session.stop_motion()
        self.said.emit("已请求停止：PLC 确认停在当前点（不再推进段计划）")

    def inject_fault(self, kind: str) -> None:
        """故障注入（卡片步骤④的三用例取证用；⛔ 界面上不给操作员这个按钮，只由自测／e2e 调）。

        必须在循环线程内调：`disconnect` 靠 `asyncio.create_task` 排停机协程（见 `comm/plc_logic.py`）。
        """
        if self._sim is None:
            self.failed.emit("本机模拟器没起着，注入不了故障")
            return
        self.submit(self._inject(kind), what=f"注入故障 {kind}")

    async def _inject(self, kind: str) -> None:
        self._sim.inject_fault(kind)

    # --- 回读与链路态（循环线程 → 主线程，只发信号）------------------------------ #
    def _rx_frames(self, batch: list) -> None:
        self.frames.emit(batch)

    def _rx_state(self, state: LinkState) -> None:
        self.link_state.emit(state)

    def _on_done(self, _ok: bool) -> None:
        """一次下发收尾（主线程）：解「在途」锁。成败都解——失败留着锁就等于永久禁发。"""
        self._busy = False
