"""comm.opcua_client.reconnect —— 链路态判定与自动重连（契约 §9.1 步骤 7 ＋ §10）。

两级降级，阈值来源不同、**都不写死毫秒数**：

- **STALE**＝心跳丢失但会话还在。阈值＝``HEARTBEAT_LOSS_CYCLES × 配置的 publish_interval_ms``，即
  §9.1 步骤 7 的「200 ms（3 个周期）」——周期改了阈值自动跟着改。处置＝界面告警"数据过期"并停止姿态跟随。
- **OFFLINE**＝判离线，进重连。T09 完成标准第 4 条要求「断 simulator 后 **5 s 内**判离线」，故阈值取
  **4.5 s**（判定条件是无回读时长**大于**阈值，取 5.0 会必然落在 5 s 之外；契约未给这个数，做成
  ``offline_after_s`` 参数，调用方可收紧）。处置＝§10 指数退避重连（0.5 s 起、封顶 30 s），
  恢复后**重新读取全部状态**，不假设回到断线前。

判据只看「距上次收到任何 datachange 的时长」，**不看会话对象是否报错**：simulator 进程被硬杀时 TCP 可能
长时间静默，只有本地计时器能保证 5 s 内判离线。降级期间 ``last_frame`` 原样保留、**绝不外推**（§9.3-③）。
"""

from __future__ import annotations

import asyncio
import enum
import logging
import time
from collections.abc import Awaitable, Callable

log = logging.getLogger(__name__)

HEARTBEAT_LOSS_CYCLES = 3    # §9.1 步骤 7：心跳丢失＝3 个发布周期
# T09 完成标准第 4 条：断 simulator 后 **5 s 内**判离线。判据是「无回读时长 > 本阈值」且看门狗每
# WATCHDOG_TICK_S 自检一次，故阈值取 5.0 会让判定必然落在 5 s **之外**——收到 4.5 s，留 0.5 s 给
# 自检步进与调度余量（实测判定落在 4.5–4.7 s）。契约未给这个数，故做成 offline_after_s 参数。
OFFLINE_AFTER_S = 4.5
WATCHDOG_TICK_S = 0.1        # 自检周期，须远小于 OFFLINE_AFTER_S，否则判定粒度不够
RECONNECT_BASE_S = 0.5       # §10：指数退避起点
RECONNECT_MAX_S = 30.0       # §10：指数退避最长 30 s
BACKOFF_FACTOR = 2.0         # 退避倍率：0.5→1→2→4→…→封顶 RECONNECT_MAX_S


class LinkState(enum.Enum):
    """链路态。``value`` 为可直接进日志／桥消息的短名（不是上屏文案，上屏文案归 T02）。"""

    ONLINE = "online"
    STALE = "stale"
    OFFLINE = "offline"


class LinkWatchdog:
    """按「多久没收到回读」降级链路态，并在 OFFLINE 时驱动重连。

    本类不认识 OPC UA：``reconnect`` 与 ``on_state`` 由调用方（Session）注入，故它既能配真链路、
    也能在单测里用假回调直接验两级阈值，不必起 Server。
    """

    def __init__(self, *, stale_after_s: float, offline_after_s: float,
                 reconnect: Callable[[], Awaitable[None]],
                 on_state: Callable[[LinkState], None],
                 tick_s: float = WATCHDOG_TICK_S) -> None:
        self._stale_after_s = stale_after_s
        self._offline_after_s = offline_after_s
        self._reconnect = reconnect
        self._on_state = on_state
        self._tick_s = tick_s
        self._last_rx = time.monotonic()
        self._task: asyncio.Task | None = None
        self._state = LinkState.OFFLINE
        self.stopped = False

    @property
    def state(self) -> LinkState:
        return self._state

    @property
    def seconds_since_rx(self) -> float:
        return time.monotonic() - self._last_rx

    def touch(self) -> None:
        """收到任何回读即调此（由 ReadbackBuffer 的 on_rx 回调驱动）。"""
        self._last_rx = time.monotonic()

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run(), name="opcua-link-watchdog")

    async def stop(self) -> None:
        self.stopped = True
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def report(self, state: LinkState) -> None:
        """状态**变化**时才回调（每 100 ms 自检一次，不去重会把上层日志刷满）。"""
        if state is self._state:
            return
        self._state = state
        log.info("链路状态 → %s", state.value)
        self._on_state(state)

    async def _run(self) -> None:
        while not self.stopped:
            await asyncio.sleep(self._tick_s)
            age = self.seconds_since_rx
            if age > self._offline_after_s:
                self.report(LinkState.OFFLINE)
                await self._reconnect_loop()
            elif age > self._stale_after_s:
                self.report(LinkState.STALE)
            else:
                self.report(LinkState.ONLINE)

    async def _reconnect_loop(self) -> None:
        """退避重连直到成功或看门狗被停。成功后把新鲜度基准归零，否则下一轮立刻又判离线。"""
        delay = RECONNECT_BASE_S
        while not self.stopped:
            log.warning("链路离线（%.2f s 无回读），%.1f s 后重连", self.seconds_since_rx, delay)
            await asyncio.sleep(delay)
            try:
                await self._reconnect()
            except Exception as caught:      # 重连必须吞掉一切异常继续退避，否则看门狗任务就死了
                log.warning("重连失败：%s: %s", type(caught).__name__, caught)
                delay = min(delay * BACKOFF_FACTOR, RECONNECT_MAX_S)
                continue
            self._last_rx = time.monotonic()
            self.report(LinkState.ONLINE)
            log.info("链路已恢复，全部状态已重读")
            return
