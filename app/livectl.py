"""app.livectl —— 步骤⑤「实时联动跟随」：回读帧 → 关节值 → fk → 视口，外加频率角标与模式互斥。

单向数据流（03 §3）：实测位置的真值只在 PLC（经 `comm` 的 `Frame` 上抛）⇒ 本件只做三件事：`raw_to_eng`
换工程值（契约 §7.4）→ 交 `core.path.tool_pose_in_model` 求位姿 → `to_column_major` 后 `pose.update` 上屏。
⛔ 本层不算几何、⛔ 不存第二份真值、⛔ 不外推。

**插值落点**（卡片步骤② 写「渲染端线性插值到 60fps」，本件放在壳侧；理由与 T07 已获追认的那条同源）：
`view/js/path.js`（T07 已验收件、对本单只读）已把 `pose.update` 的投影与 rAF 出帧全包了，再在视口里加一层
插值既要改它、又得在桥上多传一份位姿。故本件用一个 ≈60 Hz 的 `QTimer` 在**最近两帧实测数据之间**线性插值
（参数恒钳在 [0,1]）后推 `pose.update`，视口照旧逐帧投影 ⇒ 屏幕上仍是连续运动，而结构上**不可能外推**：时钟
走过最新一帧就停在最新一帧（滞后 ≤1 个发布周期）⛔ 绝不用超出已知数据的参数猜下一帧（W-5.7／§9.3-③）。

**角标频率**（卡片步骤②）：实测 Hz 由回读帧的到达时刻算（窗口 1 s），与视口报来的画面 fps 一并写进底部
角标。变黄阈值＝标称频率的 1/2（标称由 `machine.yaml` 的 `publish_interval_ms` 算出，现值 50 ms ⇒ 20 Hz
⇒ 阈值 10 Hz，与卡片同数）⛔ 不写死 10：改发布周期，阈值自动跟着改。

⚠️ **角标两个数的写入方**：`statusbar.set_freq(hz, fps)` 是**整体替换**（T02 件、只许追加接线）⇒ 画面 fps 由
`app/pathctl.py` 写、数据 Hz 由本件写；两处都连 `Bridge.received` 而本件**后连**（`install_send_flow` 晚于 shell
构造 pathctl）⇒ 同一次发射内写在后、两个数都留得住。这是 Qt「按连接顺序派发」的保证，由
`tools/e2e_smoke.py` 的 **G5 判据**钉住：角标原文里数据 Hz 与画面 fps 必须**同时**在场，
少任一个就是接线顺序被改坏了（本件后连的那条前提没了）。
"""

from __future__ import annotations

import logging
import time
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QLabel

from app.sendseg import SendSegError, slot_axes
from comm.opcua_client import LinkState
from comm.opcua_client.subscribe import Frame
from core.config.schema import MachineConfig
from core.kinematics.fk import raw_to_eng
from core.kinematics.limits import Violation, check_limits
from core.kinematics.transform import to_column_major
from core.path import tool_pose_in_model

log = logging.getLogger(__name__)

_TICK_MS = 16            # 插值时钟 ≈60 Hz（软件刷新率、非机台参数，同 app/pathctl.py 的口径与理由）
HZ_WINDOW_S = 1.0        # 实测频率统计窗口：够平滑，角标也不至于长时间不跳
HZ_DIVISOR = 2           # 变黄阈值＝标称频率 ÷ 本数（见模块 docstring；⛔ 不写死 10 Hz）
MS_PER_S = 1000.0        # publish_interval_ms → 秒
_ARRIVALS_MAX = 400      # 窗口内最多留这么多个到达时刻（20 Hz×1 s 只用 20 个，余量防长跑无界攒数据）
FREQ_BADGE = "FreqBadge"  # 底部角标的 objectName（T02 定的；本件按名取它置动态属性 ⇒ ⛔ 不改 statusbar）
_LOW_TELL = "数据频率偏低（实测 {hz:.1f} Hz，低于标称 {nominal:.1f} Hz 的一半）：模型仍按实测帧走、⛔ 不外推——请查链路与 PLC 发布周期"


class LiveController(QObject):
    """联动跟随。信号 `changed()`＝跟随态变了（`app/sendctl.py` 据此刷⑤页的驱动源行与按钮可用性）。"""

    changed = Signal()
    dropped = Signal(int, str)      # (累计丢弃帧数, 人话原因)：⑤ 页越界计数行
    counted = Signal(int, int)      # (已采用, 已丢弃)：⑤ 页计数行的常态刷新（丢帧之外也要看得见在收数）

    def __init__(self, panel, bridge, statusbar, badge, light, workmode, pathctl, linkctl,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._panel, self._bridge, self._statusbar = panel, bridge, statusbar
        self._badge, self._light, self._workmode = badge, light, workmode
        self._pathctl, self._linkctl = pathctl, linkctl
        self._following = False
        self._prev: tuple[float, dict[str, float], int] | None = None
        self._next: tuple[float, dict[str, float], int] | None = None
        self._arrivals: deque[float] = deque(maxlen=_ARRIVALS_MAX)
        self._accepted = self._dropped = 0
        self._low_told = False
        self._fps: float | None = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        linkctl.frames.connect(self._on_frames)
        linkctl.link_state.connect(self._on_link_state)
        pathctl.changed.connect(self._on_path_changed)     # 路径作废即停跟随（卡片步骤③ 互斥）
        bridge.received.connect(self._on_bridge_msg)       # ⚠️ 必须最后连：见模块 docstring 的写入顺序

    # --- 跟随态（卡片步骤③：模式互斥）---------------------------------------- #
    @property
    def following(self) -> bool:
        return self._following

    def stats(self) -> tuple[int, int]:
        """(已采用帧数, 已丢弃帧数)：⑤ 页与 e2e 都读它 ⛔ 不另立计数（两处数字必须同源）。"""
        return self._accepted, self._dropped

    def start(self) -> None:
        """开始跟随：模型改由 PLC 实测回读驱动 ⇒ 徽标转[联动]、点位与步骤③控件锁定（互斥）。"""
        if self._following:
            return
        if not self._bind():
            return
        self._pathctl.pause()                 # 先停仿真播放（它会解锁点位编辑），再锁 ⇒ 顺序不可换
        self._following = True
        self._prev = self._next = None
        self._arrivals.clear()
        self._accepted = self._dropped = 0
        self._low_told = False
        self._badge.set_mode("live")
        self._lock_editing(True)
        self._timer.start(_TICK_MS)
        self._say("已开始跟随：模型由 PLC 实测回读驱动（[联动]）。期间不可编辑点位与步骤③——"
                  "要先改点，请先点[暂停跟随]")
        log.info("联动开始：端点 %s，标称 %.1f Hz", self._linkctl.endpoint, self._nominal_hz())
        self.changed.emit()

    def stop(self, why: str = "已暂停跟随") -> None:
        """暂停跟随：回[仿真]态、解除编辑锁。⛔ 不清 `_next`——模型停在最后一帧实测位姿（不跳回零位）。"""
        if not self._following:
            return
        self._following = False
        self._timer.stop()
        self._badge.set_mode("sim")
        self._lock_editing(False)
        self._statusbar.set_freq(None, self._fps)
        self._paint_freq(False)
        self._say(f"{why}：模型停在最后一帧实测位姿，可编辑点位与播放动画（[仿真]）")
        self.changed.emit()

    def _lock_editing(self, on: bool) -> None:
        """联动中禁编辑点位（卡片步骤③）。步骤③整页一并锁：那边的[播放]若可点就会与实测驱动抢同一个
        模型（两种驱动源同时上屏＝看不出错也查不出的假动画），故锁整页而不是只锁一个按钮。"""
        self._panel.step2.setEnabled(not on)
        self._panel.step3.setEnabled(not on)

    def _on_path_changed(self) -> None:
        """路径作废即停跟随：F3／换臂／新模型三处都经 `pathctl.invalidate` 发 `changed`，挂这一个信号就闭合了
        卡片步骤③ 的互斥 ⛔ 不必再动 shell.py（它正贴 300 行上限，理由见 `app/sendctl.py`）。"""
        if self._following:
            self.stop("路径已作废")

    def _bind(self) -> bool:
        """跟随要用的三件（配置／驱动链／坐标框）一律取步骤③绑定的**同一份** ⛔ 不自己再 load。"""
        cfg, chain, frame = self._pathctl.kinematics()
        if cfg is None or chain is None:
            self._say("还不能跟随：先在步骤③点[生成路径]（机台配置与驱动链是那一步绑定的）")
            return False
        try:
            slot_axes(cfg, self._workmode.current_mode() or "")
        except SendSegError as exc:
            self._say(f"还不能跟随：{exc}")
            return False
        return True

    # --- 收帧（主线程：`linkctl` 已把循环线程的回调转成信号）--------------------- #
    def _on_frames(self, batch: object) -> None:
        if not self._following or not isinstance(batch, list):
            return
        for frame in batch:
            self._accept(frame)
        self.counted.emit(self._accepted, self._dropped)   # 每批都刷（_report_hz 窗口不足时会提前返回）
        self._report_hz()

    def _accept(self, frame: Frame) -> None:
        """一帧回读 → 关节值。**越界即整帧丢弃并计数**（卡片步骤④第三例）：把超行程的值喂给 fk，屏幕上
        就是一台飞掉的机床，而操作员会当成真机位置——⛔ 宁可不更新，也不显示一个不可能存在的位姿
        （§9.3-③ 禁外推同源）。判据用 T04 已验收的 `check_limits`（与步骤③生成路径同一把尺子）。"""
        cfg, chain, _ = self._pathctl.kinematics()
        joints = self._joints_of(frame, cfg)
        if joints is None:
            return
        bad = check_limits(joints, cfg)
        if bad:
            self._dropped += 1
            note = self._describe(bad)
            self.dropped.emit(self._dropped, note)
            if self._dropped == 1 or self._dropped % 20 == 0:
                self._say(f"已丢弃第 {self._dropped} 帧越界回读：{note}（模型保持在上一帧有效位姿）")
                log.warning("越界丢帧累计 %d：%s", self._dropped, note)
            return
        self._accepted += 1
        stamp = time.monotonic()
        self._arrivals.append(stamp)
        self._prev, self._next = self._next, (stamp, joints, frame.cur_seg)

    def _joints_of(self, frame: Frame, cfg: MachineConfig) -> dict[str, float] | None:
        """槽位值 → 关节值（键＝轴 id）：`raw_to_eng` 换工程值（契约 §7.4）。槽位序取 `slot_axes`，与
        下发**同一处**定义 ⇒ 写进去的第 i 槽与读回来的第 i 槽必然是同一根轴。"""
        try:
            axes = slot_axes(cfg, self._workmode.current_mode() or "")
        except SendSegError as exc:
            self.stop(f"槽位映射不成立，已停止跟随（{exc}）")
            return None
        pairs = zip(axes, frame.pos)
        return {axis: raw_to_eng(cfg.axes[axis], float(value)) for axis, value in pairs}

    @staticmethod
    def _describe(bad: list[Violation]) -> str:
        """越界项 → 人话（轴号／数值／限值），措辞与 `core.path` 同口径但按 `Violation` 公开字段自组 ⛔ 不 import 私有名。"""
        worst = bad[0]
        low, high = worst.limit
        if worst.kind == "sync":
            return f"双驱 {worst.group} 同步偏差 {worst.value:g} mm 超容差 ±{high:g} mm"
        return (f"轴 {worst.axis_id} 实测 {worst.value:g} {worst.unit} 超行程 "
                f"[{low:g}, {high:g}] {worst.unit}"
                + (f"（另有 {len(bad) - 1} 项）" if len(bad) > 1 else ""))

    # --- 出帧（≈60 Hz 插值时钟）----------------------------------------------- #
    def _tick(self) -> None:
        if self._next is None:
            return                          # 还没收到有效帧：⛔ 不造位姿、不推零矩阵
        self._emit(*self._blend(time.monotonic()))

    def _blend(self, now: float) -> tuple[dict[str, float], int]:
        """在**最近两帧实测数据之间**线性插值；只有一帧时就用那一帧。

        参数＝(now − 新帧到达时刻) ÷ 两帧间隔，恒钳在 [0,1]（间隔为 0 也取 1）：`now` 走过新帧时刻即恒 1 ⇒
        停在最新一帧，这就是「不外推」的落点（与 `app/pathctl.py::_locate` 同一手法）。"""
        stamp, joints, seg = self._next
        if self._prev is None:
            return joints, seg
        before, older, _ = self._prev
        span = stamp - before
        ratio = 1.0 if span <= 0.0 else (now - stamp) / span
        ratio = min(1.0, max(0.0, ratio))          # 钳在 [0,1]：走过最新一帧就停住 ⛔ 不外推
        # 逐轴插值；只在一端出现的轴按该端常值（`get` 的兜底就是这一句，⛔ 不视为 0）
        keys = set(older) | set(joints)
        low = {axis: older.get(axis, joints[axis]) for axis in keys}
        high = {axis: joints.get(axis, older[axis]) for axis in keys}
        return ({axis: low[axis] + (high[axis] - low[axis]) * ratio for axis in keys}, seg)

    def _emit(self, joints: dict[str, float], cur_seg: int) -> None:
        """一帧位姿上屏：fk → `to_column_major` → `pose.update`（03 §5：出前端必经列主序）。"""
        _, chain, frame = self._pathctl.kinematics()
        pose = to_column_major(tool_pose_in_model(joints, chain, frame))
        self._bridge.call_view("pose.update", {
            "poses": {chain.end_link: [float(v) for v in pose]},
            # §6.1 的 CurSeg 由模拟器按 0 起算回读，而段号在壳内是 1-based（`core.path.Segment.id`）
            "seg": cur_seg + 1, "ts": time.time()})

    # --- 角标（卡片步骤②：实测频率＋<10 Hz 变黄＋人话）--------------------------- #
    def _nominal_hz(self) -> float:
        cfg = self._pathctl.kinematics()[0]
        interval = cfg.opcua.publish_interval_ms if cfg is not None else 0.0
        return MS_PER_S / interval if interval > 0.0 else 0.0

    def _report_hz(self) -> None:
        """实测频率＝窗口内到达帧数 ÷ 窗口跨度（用**到达时刻**算，⛔ 不用帧里的时间戳：那是 comm 层的
        单调钟，与本层窗口不同源）。窗口不足两帧时不报——报出来必是假高值（附7-① 那一族）。"""
        if len(self._arrivals) < 2:
            return
        while self._arrivals and self._arrivals[-1] - self._arrivals[0] > HZ_WINDOW_S:
            self._arrivals.popleft()
        if len(self._arrivals) < 2:
            return
        span = self._arrivals[-1] - self._arrivals[0]
        hz = (len(self._arrivals) - 1) / span if span > 0.0 else 0.0
        self._statusbar.set_freq(hz, self._fps)
        nominal = self._nominal_hz()
        low = nominal > 0.0 and hz < nominal / HZ_DIVISOR
        self._paint_freq(low)
        if low and not self._low_told:
            self._low_told = True
            self._say(_LOW_TELL.format(hz=hz, nominal=nominal))
            log.warning("数据频率偏低：实测 %.2f Hz、标称 %.2f Hz", hz, nominal)
        elif not low:
            self._low_told = False

    def _paint_freq(self, low: bool) -> None:
        """角标变黄：按 objectName 取 T02 那个 QLabel 置动态属性（选择器在 theme.py）⛔ 不改它的签名。"""
        badge = self._statusbar.findChild(QLabel, FREQ_BADGE)
        if badge is None:
            return
        badge.setProperty("hz", "low" if low else "normal")
        badge.style().unpolish(badge)
        badge.style().polish(badge)

    def _on_bridge_msg(self, type_: str, data: object) -> None:
        """视口报来的画面 fps：记住并**连数据 Hz 一起**重写角标（`set_freq` 是整体替换，见模块 docstring）。"""
        if type_ != "perf.fps" or not isinstance(data, dict):
            return
        try:
            self._fps = float(data["fps"])
        except (KeyError, TypeError, ValueError):
            return
        if self._following and len(self._arrivals) > 1:
            self._report_hz()
        elif not self._following:
            self._statusbar.set_freq(None, self._fps)

    # --- 链路态（卡片步骤④第一例：断线 → 灯灰＋日志＋模型停住不跳飞）---------------- #
    def _on_link_state(self, state: object) -> None:
        online = state == LinkState.ONLINE
        self._light.set_online(online)
        if online:
            self._say("链路在线：回读正常")
            return
        if state == LinkState.OFFLINE:
            self._say("链路已断（灯灰）：模型保持在最后一帧有效位姿、⛔ 不外推不跳飞；"
                      "重连由通讯层自动重试，恢复后会重新读取全部状态")
            log.warning("链路离线：跟随冻结在最后一帧（已采用 %d 帧、丢弃 %d 帧）",
                        self._accepted, self._dropped)
        else:
            self._say("链路变陈：已超过约 3 个发布周期没收到回读，模型保持在最后一帧有效位姿")

    def _say(self, msg: str) -> None:
        self._statusbar.log(msg)
