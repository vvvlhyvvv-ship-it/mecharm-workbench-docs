"""app.pathctl —— 步骤③「路径生成＋播放动画」的控制器（T07；02 §2 步骤③、03 §3/§5）。

**为什么单列一个文件**：`app/shell.py` 交付时已 285 行，逼近 04 §4.5-① 的「单文件 ≤300 物理行」
上限，路径生成／播放时钟／fps 角标三摊逻辑塞进去必越线。故本件承载业务、shell 只做约十行接线。
本文件名**非** 04 预授权命名，已在 T07 交付汇报里报备并写明此理由。

单向数据流（03 §3）：点位真值只在 `core`（步骤②注入）→ 本件调 `core.path.gen_path` 求段序列 →
段清单灌右栏 `Step3Pane`、ASCII 载荷推视口折线（`path.show`）→ 播放时本件按段**线性插值关节**、
经 `core.path.tool_pose_in_model` 求位姿、`to_column_major` 后上屏（`pose.update`）。
⛔ 前端不算几何、⛔ 不外推、⛔ 不预测下一帧姿态（W-5.7）——插值参数恒钳在 [0,1]。

载荷全 ASCII（03 §5、`app/bridge.py` 用 `ensure_ascii=True` 投递）⇒ `path.show` **不带**中文
`reason`、也不带可被用户改成中文的点名，只发几何与可达标志；人话原因留在右栏（壳内）。

播放时钟间隔是**软件刷新率**、不是机台参数，且 `machine.yaml` 的 `limits` 键由加载器冻结
（`LIMIT_KEYS`）⇒ 无法进配置，只能作本层常量（04 §5.5-① 禁的是**现场参数**硬编码）。
`perf.fps` 是本单为完成标准①（角标记录实测 fps）新定的视口→壳 type，03 §5 未登记 ⇒ 汇报回填。
"""

from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from core.config import REPO_ROOT, ConfigError, MachineConfig, load_machine
from core.kinematics.ik import Chain, derive_chain
from core.kinematics.transform import CoordFrame, axis_swap_frame, to_column_major
from core.path import PathSummary, Segment, gen_path, summarize, tool_pose_in_model

_TICK_MS = 16                     # 播放时钟约 60Hz（软件刷新率，非机台参数；见模块 docstring）
# 同一件事分两种说法（02 §2 步骤③ 禁术语上屏、§4 全中文）：`_FRAME_TELL` 给操作员看，
# ⛔ 不带内部编号；`_FRAME_NOTE` 只进日志，保留可追溯的契约出处。
_FRAME_TELL = "机台坐标系对齐方式尚未配置：本次按「模型与设备同向重合」处理，配置补齐后结果自动跟随"
_FRAME_NOTE = ("模型框→设备框无配置源（契约 §7.1 待确认）：本次按同向重合框处理，"
               "回执到后只改配置、不改代码")

log = logging.getLogger(__name__)


class PathController(QObject):
    """步骤③控制器。信号 `changed()`＝路径可用性变了（shell 据此重算步骤④⑤门禁）。"""

    changed = Signal()

    def __init__(self, panel, bridge, stepbar, statusbar, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._panel = panel
        self._bridge = bridge
        self._stepbar = stepbar
        self._statusbar = statusbar
        self._segments: list[Segment] = []
        self._cfg = None
        self._chain: Chain | None = None
        self._frame = axis_swap_frame({"x": "+x", "y": "+y", "z": "+z"})   # 单位框（见 docstring）
        self._frame_warned = False
        self._elapsed = 0.0
        self._last = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._wire()

    def _wire(self) -> None:
        step3 = self._panel.step3
        step3.generate_requested.connect(self.generate)
        step3.play_requested.connect(self.play)
        step3.pause_requested.connect(self.pause)
        step3.option_changed.connect(self.invalidate)
        step3.log.connect(self._say)
        self._panel.step2.waypoints_changed.connect(self._on_waypoints)
        self._bridge.received.connect(self._on_bridge_msg)
        self._stepbar.step_clicked.connect(self._on_step_clicked)

    # --- 门禁 --------------------------------------------------------------- #
    def ready(self) -> bool:
        """已生成且无阻断段＝可进入步骤④⑤（shell 的 `_refresh_unlock` 读它）。"""
        summary = self._panel.step3.summary()
        return summary is not None and summary.ok

    # --- 供 T08 步骤④取数（对 T07 归属文件的跨归属**追加**，已在 T08 汇报报备）------- #
    def segments(self) -> list[Segment]:
        """当前段序列：T08 校核的数据源（真值仍只在 core，本件只转交 ⛔ 不复制不加工）。"""
        return self._segments

    def kinematics(self) -> tuple[MachineConfig | None, Chain | None, CoordFrame]:
        """(机台配置, 驱动链, 坐标框)：T08 复用**同一份**绑定 ⛔ 不再各自 load_machine。"""
        return self._cfg, self._chain, self._frame

    # --- 生成 --------------------------------------------------------------- #
    def generate(self) -> None:
        """点位序列 → 段序列：灌右栏表＋推视口折线＋（无阻断段时）标记步骤③完成。"""
        points = self._panel.step2.waypoints()
        if len(points) < 2:
            self._panel.step3.set_point_count(len(points))
            self._say(f"点位不足：生成路径至少需要 2 个点位（当前 {len(points)} 个）")
            return
        if not self._bind():
            return
        self._segments = gen_path(points, self._cfg, self._chain, self._frame,
                                  kind=self._panel.step3.kind(),
                                  blending=self._panel.step3.blending())
        summary = summarize(self._segments)
        self._panel.step3.show_segments(self._segments, summary)
        self._show_path(self._segments)
        self._announce(summary)

    def _bind(self) -> bool:
        """首次生成时载入机台配置与驱动链（配置读不到就当场人话报错，⛔ 不塞默认值）。"""
        if self._cfg is not None:
            return True
        try:
            self._cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
            self._chain = derive_chain(self._cfg)
        except (ConfigError, OSError) as exc:
            self._say(f"读不到机台配置，无法生成路径：{exc}")
            return False
        if not self._frame_warned:
            self._frame_warned = True
            self._say(_FRAME_TELL)
            log.warning("%s", _FRAME_NOTE)
        return True

    def _show_path(self, segments: list[Segment]) -> None:
        """推视口折线（全 ASCII 载荷：只发几何与可达标志，⛔ 不发中文原因／点名）。"""
        self._bridge.call_view("path.show", {"segments": [
            {"id": seg.id, "type": seg.type, "length": seg.length_mm, "blocked": seg.blocked,
             "start": [float(v) for v in seg.start_mm], "end": [float(v) for v in seg.end_mm]}
            for seg in segments]})

    def _announce(self, summary: PathSummary) -> None:
        """汇总行已由右栏显示，这里只补状态栏人话日志＋步骤③完成标记＋门禁重算。"""
        blocked = [seg.id for seg in self._segments if seg.blocked]
        if summary.ok:
            self._stepbar.mark_completed(3)
            self._say(f"路径已生成：{summary.describe()}")
        else:
            self._say(f"路径含不可达段（第 {'、'.join(str(i) for i in blocked)} 段）："
                      f"{summary.describe()}")
        self.changed.emit()

    # --- 播放（按段线性插值；⛔ 不外推、⛔ 不预测下一帧 W-5.7）------------------ #
    def play(self) -> None:
        """从第一段起播放；播放中锁定点位编辑与段型改动（02 §2 步骤③）。"""
        if not self._segments or not self.ready():
            return
        self._elapsed = 0.0
        self._last = time.perf_counter()
        self._panel.step3.set_playing(True)
        self._panel.step2.setEnabled(False)
        self._timer.start(_TICK_MS)
        self._say(f"开始播放：{summarize(self._segments).describe()}")

    def pause(self) -> None:
        """暂停（离开步骤③／改点／切模式都会走到这里）：解除点位编辑锁。"""
        if self._halt():
            self._say("已暂停播放")

    def _halt(self) -> bool:
        """停钟＋解除编辑锁；返回本次是否真的从播放态停下来（未播放即 False，免重复日志）。"""
        if not self._timer.isActive():
            return False
        self._timer.stop()
        self._panel.step3.set_playing(False)
        self._panel.step2.setEnabled(True)
        return True

    def _tick(self) -> None:
        """一帧：按 `time.perf_counter()` 的**实测**增量推进时钟，再定位当前段并上屏。"""
        now = time.perf_counter()
        self._elapsed += now - self._last
        self._last = now
        seg, ratio = self._locate(self._elapsed)
        if seg is None:
            self._finish()
            return
        self._emit_pose(seg, ratio)

    def _locate(self, elapsed: float) -> tuple[Segment | None, float]:
        """累计时长定位当前段；返回 (段, 段内进度)。走完全部段 ⇒ (None, 0)。

        段内进度＝`elapsed / duration`，且**只在 `elapsed < duration` 时返回**，故恒在 [0,1)
        内——这就是「不外推」的落点：时钟走到哪算哪，⛔ 绝不用超出段终点的参数去猜下一帧。
        时长为 0 的段（两点重合）无可插值，直接跳过。
        """
        for seg in self._segments:
            if seg.duration_s > 0.0 and elapsed < seg.duration_s:
                return seg, _clamp01(elapsed / seg.duration_s)
            elapsed -= seg.duration_s
        return None, 0.0

    def _emit_pose(self, seg: Segment, ratio: float) -> None:
        """一帧位姿：段内线性插值关节 → `tool_pose_in_model` → 列主序上屏（03 §5）。"""
        joints = _lerp(seg.joints_start, seg.joints_end, ratio)
        pose = to_column_major(tool_pose_in_model(joints, self._chain, self._frame))
        self._bridge.call_view("pose.update", {
            "poses": {self._chain.end_link: [float(v) for v in pose]},
            "seg": seg.id, "ts": time.time()})
        self._panel.step3.set_current(seg.id)

    def _finish(self) -> None:
        self._halt()
        self._panel.step3.set_current(0)
        self._say(f"播放结束：{summarize(self._segments).describe()}")

    # --- 结果作废 ----------------------------------------------------------- #
    def invalidate(self, why: str) -> None:
        """改点／切模式／换段型／F3／新模型 → 路径作废（真清空右栏与视口折线）。"""
        had = bool(self._segments) or self._panel.step3.summary() is not None
        self.pause()
        self._segments = []
        self._panel.step3.clear()
        if had:
            self._show_path([])
            self._say(f"结果作废：{why}——须重新生成路径")
            self.changed.emit()

    def _on_waypoints(self, points: object) -> None:
        """点位列表变化（T06 已推视口标号牌）：刷[生成路径]可用性＋作废已生成路径。"""
        self._panel.step3.set_point_count(len(points))
        self.invalidate("点位已改动")

    def _on_step_clicked(self, n: int) -> None:
        if n != 3 and self._timer.isActive():
            self.pause()                       # 离开步骤③即暂停（不留后台动画耗 CPU）

    def _on_bridge_msg(self, type_: str, data: object) -> None:
        """视口→壳：只认本单新定的 `perf.fps`（实测帧率角标，完成标准①），其余交回 shell。"""
        if type_ != "perf.fps" or not isinstance(data, dict):
            return
        try:
            fps = float(data["fps"])
        except (KeyError, TypeError, ValueError):
            return
        self._statusbar.set_freq(None, fps)    # 数据频率角标归 T09，本单只填画面 fps

    def _say(self, msg: str) -> None:
        self._statusbar.log(msg)


def _clamp01(value: float) -> float:
    """插值参数钳在 [0,1]（W-5.7 禁外推的第二道保险；`_locate` 已保证不越界）。"""
    return 0.0 if value < 0.0 else (1.0 if value > 1.0 else value)


def _lerp(first: dict[str, float], second: dict[str, float], ratio: float) -> dict[str, float]:
    """两套关节目标的**逐轴线性插值**；只有一端给出的轴按该端常值（⛔ 不视为 0）。"""
    out: dict[str, float] = {}
    for key in sorted(set(first) | set(second)):
        if key in first and key in second:
            low, high = first[key], second[key]
        else:
            low = high = first[key] if key in first else second[key]
        out[key] = low + (high - low) * ratio
    return out
