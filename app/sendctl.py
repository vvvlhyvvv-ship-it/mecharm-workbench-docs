"""app.sendctl —— 步骤⑤「下发 PLC」的编排总成，兼 T10 全部壳侧接线的**安装处**（卡片步骤①②③④）。

**为什么要有这一件，以及为什么由 `app/checkctl.py` 安装它而不是 `app/shell.py`**：派单卡 §4(a) 点名
`app/shell.py` 正好 300 行＝04 §4.5-① 上限的**零余量**，⛔ 不得把业务内联进去；可它又是唯一能一次拿到
badge／light／workmode／bridge 的装配处。两难的解法是把「装配」本身也外置：本件的 `install_send_flow`
从 `MainWindow` 的**公开属性**取齐协作者、就地构造 linkctl＋livectl＋本控制器并接完线，checkctl 只加一行
调它——下发本就是它 `send_path()` 的下一棒（禁发双阻断过了 → 交本件），语义上顺。⇒ **shell.py 零改动**。

职责边界（⛔ 本件不算几何、不打包字节、不碰 asyncio）：
  组装下发块 → `app/sendseg.py`（纯函数）   握手与 asyncio 宿主 → `app/linkctl.py`
  回读投影与频率角标 → `app/livectl.py`     右栏⑤页的可见状态 → `app/steps/step5_send.py`
本件只做**编排**：把那四件的信号接到⑤页／状态栏／步骤条，并按契约 §9.1 推进五段进度。

⚠️ 两处**卡片没写死、本件自行裁定**的判断题（派单卡 §0 授权，依此报备）：
  ① 何时开始跟随：本件在阶段 4（执行中）**自动开**跟随。卡片只写「…→五段进度→执行」，未定时机；取阶段 4
     是因为 §9.1 步 7 的 20 Hz 回读从 PLC 转运行态那一刻才有意义，等 ST_DONE 再开就漏掉整个起步段。
  ② 跟随**不**随 ST_DONE 自动停：链路还在、回读还在，停了就把徽标丢回[仿真]而屏幕上摆着实测位姿（02 §3
     要求徽标让人任何时刻知道模型动是真是假）。要停由操作员点[暂停跟随]，或路径作废时 `livectl` 自己停。
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication

from app.linkctl import STAGES, LinkController
from app.livectl import LiveController
from app.sendseg import SendSegError, build_segments, describe_request
from comm.opcua_client import SPEED_OVERRIDE_FULL, LinkState
from core.collision import CollisionResult

log = logging.getLogger(__name__)

# 五段进度的两个关键段号（由 `linkctl.STAGES` 反查 ⛔ 不写死序号：那边改文案，这里自动跟着走）
_ASSEMBLE = STAGES.index("组装下发块") + 1     # 阶段 1：纯计算，不过 linkctl，由本件自己标
_FOLLOW_AT = STAGES.index("执行中") + 1        # 阶段 4：起自动跟随（裁定① 见模块 docstring）
_LAST = len(STAGES)

# 链路态 → ⑤页链路行的（人话, 颜色语义）。顶栏在线灯与「模型冻结」那句由 `livectl` 负责，⛔ 两处不重复。
_LINK_TEXT = {
    LinkState.ONLINE: ("链路在线：回读正常（端点见[查看日志]）", "ok"),
    LinkState.STALE: ("链路变陈：已超过约 3 个发布周期没收到回读，模型冻结在最后一帧有效位姿", "warn"),
    LinkState.OFFLINE: ("链路已断（离线）：模型冻结在最后一帧有效位姿，⛔ 不外推不跳飞；通讯层在自动重连", "deny"),
}
_UP_TEXT = "已连接本机 PLC 模拟器 {endpoint}（⛔ 只提供本机自环通道，连真机属现场联调单）"
_DOWN_TEXT = "已断开：本机没有 PLC 通道（下发与跟随都不可用）"
_DONE_TELL = "轨迹完成：模型停在实测终点。跟随仍在进行，要改点位请先点[暂停跟随]"


class SendController(QObject):
    """下发编排。对外只三个入口：`send()`（checkctl 确认之后）、`request_note()`（确认弹窗的小字）、
    `shutdown()`（退出收摊）；其余全是把 linkctl／livectl 的信号投影到⑤页与状态栏。"""

    def __init__(self, panel, statusbar, stepbar, pathctl, workmode, link, live,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._pane = panel.step5
        self._statusbar, self._stepbar = statusbar, stepbar
        self._pathctl, self._workmode = pathctl, workmode
        self._link, self._live = link, live
        self._stage = 0            # 0＝没有下发在途（`_on_failed` 据此决定要不要画失败段）
        self._drop_note = ""       # 最近一次越界丢帧的人话（计数行常态刷新时要带上，见 `_on_counted`）
        self._wire()

    def _wire(self) -> None:
        pane = self._pane
        pane.connect_requested.connect(self._link.start)
        pane.disconnect_requested.connect(self.shutdown)
        pane.follow_requested.connect(self._live.start)
        pane.unfollow_requested.connect(self._live.stop)
        pane.halt_requested.connect(self.halt)
        self._link.stage.connect(self._on_stage)
        self._link.said.connect(self._say)
        self._link.failed.connect(self._on_failed)
        self._link.up.connect(self._on_up)
        self._link.done.connect(self._on_done)
        self._link.link_state.connect(self._on_link_state)
        self._live.changed.connect(self._on_follow_changed)
        self._live.counted.connect(self._on_counted)
        self._live.dropped.connect(self._on_dropped)

    # --- 协作者的公开读取口（取证／e2e 只读；⛔ 不让它们去挖 `_link`／`_live` 私有名）---- #
    @property
    def link(self) -> LinkController:
        return self._link

    @property
    def live(self) -> LiveController:
        return self._live

    # --- 链路与停机 --------------------------------------------------------- #
    def shutdown(self) -> None:
        """[断开] 与退出收摊共用（`aboutToQuit` 也接它）：先停跟随再停链路，幂等。

        顺序不可反：跟随还开着就关掉会话，`livectl` 会在一个已关的链路上等下一帧，界面上看不出区别、日志里
        却是一片重连告警。⛔ 不停循环线程就退出＝QThread 被销毁时还在跑（Qt 会直接 abort）。
        """
        self._live.stop("已断开链路")
        self._link.stop()

    def halt(self) -> None:
        """[停止运动]＝§9.2 的软件主动停止（置 CMD_STOP → PLC 减速停 → 等 ACK_STOP_DONE）。

        ⛔ 不停跟随：停下之后的实测位置仍要照实显示，那正是操作员要确认的「真停在这儿了」。
        """
        self._link.abort()

    # --- 下发（卡片步骤①：确认弹窗之后 → 写段＋命令字 → 五段进度 → 执行）----------- #
    def send(self, result: CollisionResult) -> bool:
        """checkctl 的禁发双阻断与操作员确认都过了 ⇒ 组装下发块并起握手。返回是否已受理。

        入口两道前置检查与 `linkctl.send` 里的在途锁**重复**，是有意的：那边是权威（防两个 SeqID 交错），
        这边只为把「点了没反应」变成红条人话（02 §2 禁静默失败）。同 T08 双阻断的思路。
        """
        if not self._link.is_up:
            return self._refuse("还没连接 PLC 模拟器，无法下发：先点[连接本机模拟器]")
        if self._link.is_busy:
            return self._refuse("上一次下发还在途，⛔ 不叠加第二次请求：等它完成或失败后再发")
        segments = self._pathctl.segments()
        cfg = self._pathctl.kinematics()[0]
        mode = self._workmode.current_mode() or ""
        self._pane.reset()
        self._drop_note = ""
        self._stage = _ASSEMBLE
        self._pane.set_stage(_ASSEMBLE, f"组装下发块：{len(segments)} 段（工作模式「{mode or '未选定'}」）")
        try:
            path = build_segments(segments, cfg, mode)
        except SendSegError as exc:
            return self._fail(_ASSEMBLE, str(exc))
        self._pane.finish_stage(_ASSEMBLE, f"下发块已组装：{len(path)} 段（槽位与倍率见确认弹窗的请求值）")
        self._on_counted(*self._live.stats())   # reset() 把计数清了，这里还原成真值（跟随未停时不为零）
        self._pane.set_busy(True)
        self._link.send(path, SPEED_OVERRIDE_FULL, self._audit(result, path, mode))
        return True

    def request_note(self) -> str:
        """确认弹窗里的**请求值小字**（卡片步骤①）：把真要写进 PLC 的数逐条摊开给操作员核。

        弹窗归 `app/checkctl.py`（那是 T08 的禁发第②条），数值归本件 ⇒ 由 checkctl 经 `request_note` 钩子
        取用。组装不出下发块时返回人话原因而不是抛出去——弹窗里出现 traceback 等于没给操作员看。
        """
        cfg = self._pathctl.kinematics()[0]
        mode = self._workmode.current_mode() or ""
        endpoint = self._link.endpoint or "（还没连接：下发会先被拒，请先点[连接本机模拟器]）"
        try:
            path = build_segments(self._pathctl.segments(), cfg, mode)
            return describe_request(path, cfg, mode, SPEED_OVERRIDE_FULL, endpoint)
        except SendSegError as exc:
            return f"⛔ 下发块组装不出来：{exc}"

    def _audit(self, result: CollisionResult, path, mode: str) -> str:
        """§9.1 步 9 的审计行：何时／哪条轨迹／结果／发给谁。「谁」本期只有软件自身 ⇒ 记会话端点（接入登录
        体系后由上层把操作者传进来，⛔ 不臆造身份；口径同 `comm` 的 `Session.run`）。只落日志 ⛔ 不上屏。"""
        return (f"{time.strftime('%Y-%m-%dT%H:%M:%S')} 端点 {self._link.endpoint}｜工作模式 "
                f"{mode or '未选定'}｜{len(path)} 段｜倍率 {SPEED_OVERRIDE_FULL:g}%｜校核结论 "
                f"{result.verdict}｜路径指纹 {result.path_hash}")

    # --- linkctl 的信号 → ⑤页与状态栏 ---------------------------------------- #
    def _on_stage(self, stage: int, text: str) -> None:
        self._stage = stage
        self._pane.set_stage(stage, text)
        if stage == _FOLLOW_AT and not self._live.following:
            self._live.start()      # 裁定①：进「执行中」即自动跟随（模块 docstring）

    def _on_done(self, ok: bool) -> None:
        """一次下发收尾。`linkctl` 在 finally 里发它 ⇒ 成败都到，忙态一定会解开。

        失败时**不**在这里画失败段：`failed` 那条信号排在后面到，画两遍会把阶段号写错。
        """
        self._pane.set_busy(False)
        self._stage = 0
        if ok:
            self._pane.all_done(_DONE_TELL)
            self._stepbar.mark_completed(_LAST)     # 红线④：走完即标完成（同 T07 标③、T08 标④）
            self._say("下发完成：五段握手全部走完，模型已按实测回读停在终点")

    def _on_failed(self, text: str) -> None:
        """异常 → 红条＋原因码＋[查看日志]（卡片步骤④ 第二例）。文字由 `linkctl.tell()` 转好 ⛔ 本件不改写。"""
        log.warning("下发／联动异常：%s", text)
        if self._stage:                 # 没在下发途中的失败（连不上、停不下来）⛔ 不乱画五段进度
            self._pane.fail_stage(self._stage, text)
        self._pane.show_error(text)
        self._pane.set_busy(False)
        self._say(text)

    def _refuse(self, text: str) -> bool:
        """受理前就拦下的：红条＋日志 ⛔ 不动五段进度（还没开始，画个失败段等于凭空多一次下发记录）。"""
        log.warning("下发未受理：%s", text)
        self._pane.show_error(text)
        self._say(text)
        return False

    def _fail(self, stage: int, text: str) -> bool:
        log.warning("下发失败（阶段 %d/%d）：%s", stage, _LAST, text)
        self._pane.fail_stage(stage, text)
        self._pane.show_error(text)
        self._say(text)
        self._stage = 0
        return False

    def _on_up(self, on: bool) -> None:
        self._pane.set_up(on, _UP_TEXT.format(endpoint=self._link.endpoint) if on else _DOWN_TEXT)

    def _on_link_state(self, state: object) -> None:
        text, tone = _LINK_TEXT.get(state, (f"链路状态未识别（{state!r}），按异常处理", "warn"))
        self._pane.set_link(text, tone)

    # --- livectl 的信号 → ⑤页 ------------------------------------------------ #
    def _on_follow_changed(self) -> None:
        """跟随态变了（卡片步骤③ 模式互斥）：驱动源行与按钮可用性一并刷，计数行还原一次真值。"""
        self._pane.set_follow(self._live.following)
        self._on_counted(*self._live.stats())

    def _on_counted(self, accepted: int, dropped: int) -> None:
        """计数行常态刷新。带上最近一次丢帧原因：`counted` 每批都发、`dropped` 只在丢帧时发，不带就会被
        紧接着的常态刷新抹掉（卡片步骤④ 第三例的可见证据不能一闪就没）。"""
        self._pane.set_counts(accepted, dropped, self._drop_note)

    def _on_dropped(self, dropped: int, note: str) -> None:
        """越界丢帧（卡片步骤④ 第三例）：记原因并立刻刷计数行。⛔ 不另立计数，两个数都取 `livectl.stats()`。"""
        self._drop_note = note
        self._on_counted(self._live.stats()[0], dropped)

    def _say(self, msg: str) -> None:
        self._statusbar.log(msg)


def install_send_flow(win, checkctl) -> SendController:
    """T10 的接线总成：在**已装配好的主窗**上装齐三件并接完线（为什么在这里装见模块 docstring）。

    调用时机有硬约束：必须在 shell 构造完 pathctl 之后（`livectl` 要后连 `Bridge.received` 才写得住角标的
    两个数，见 `app/livectl.py` 模块 docstring），且在 checkctl 的 `__init__` 末尾（那时 `win.badge`／
    `win.light`／`win.panel`／`win.stepbar` 都已存在，而 `win.checkctl` 还没赋上 ⇒ 故 checkctl 显式传进来）。
    """
    link = LinkController(win.pathctl, win)
    live = LiveController(win.panel, win.bridge, win.statusbar, win.badge, win.light,
                          win.workmode, win.pathctl, link, win)
    send = SendController(win.panel, win.statusbar, win.stepbar, win.pathctl, win.workmode,
                          link, live, win)
    checkctl.send_confirmed.connect(send.send)
    checkctl.request_note = send.request_note
    QApplication.instance().aboutToQuit.connect(send.shutdown)
    return send
