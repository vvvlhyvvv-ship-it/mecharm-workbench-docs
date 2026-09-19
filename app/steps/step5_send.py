"""app.steps.step5_send —— 执行控制·下发业务页（T10 卡片步骤①③④；T15 执行控制组化，02 V2.0 §2.3）。

单一职责＝**视图**：链路态、握手五段进度、异常红条、跟随控制、帧与越界计数、四枚执行命令与倍率／执行
偏好。判定与真值一律在别处——门禁在 `app/checkctl.py`（T08 双阻断，本页把主按钮与旁注以 `send_btn`／
`send_note` 属性名交回给它），握手在 `app/linkctl.py`，联动在 `app/livectl.py`，段适配在
`app/sendseg.py`。本页 ⛔ 不算几何、⛔ 不持机台参数、⛔ 不自造结论措辞；用户意图经信号回灌控制器。

**替换掉 T02 的占位页**：`app/panel.py` 自己的 docstring 写明「真下发通道由 T10 接入时替换整页」⇒
本页暴露同名属性，`panel.py` 只做一行改指，T08 的门禁代码零改动。T15 起本页改排为路径仿真页签的
「② 执行控制 · 下发」区（`app/sim_tab.py` 嵌入），确认弹窗＋五段进度＋红条语义一字不改地迁入。

五段进度 ↔ 契约 §9.1 九步的对应表在 `app/linkctl.py::STAGES` 处（此处只投影，⛔ 不重复定义）。
颜色 ⛔ 禁散写色值：一律取 `app.theme.TOKENS` 且必须用动态属性 `tone` 走 QSS 选择器——⛔ 不用
`setPalette`（全局 QSS 一旦给了 color，调色板就被忽略，T10 已实测）。状态一律「颜色＋图标＋文字」
三通道（02 §4／招标 16(3)③）：图标 ○待／▶进行中／●完成／⛔失败。
⚠️ **按钮可用性的权威在控制器**：`_refresh()` 只是把 (链路, 跟随, 在途, 门禁, 暂停) 投影成可用性；
真正拦住「重复下发」的是 `app/linkctl.py` 的在途锁 ⇒ ⛔ 不把 T08 的判定搬进视图。
"""

from __future__ import annotations

from collections import deque

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (QComboBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit,
                               QPushButton, QVBoxLayout, QWidget)

from app.linkctl import STAGES

_IDLE, _RUN, _DONE, _FAIL = "idle", "run", "done", "fail"
_ICON = {_IDLE: "○", _RUN: "▶", _DONE: "●", _FAIL: "⛔"}
_TONE = {_IDLE: "dim", _RUN: "accent", _DONE: "ok", _FAIL: "deny"}
_HISTORY_MAX = 300          # [查看日志] 留这么多条人话（够查一次下发全程，⛔ 不无界攒）
_LINK_DOWN = "未连接：本机还没有 PLC 通道（下发与跟随都不可用）"
_SOURCE_LIVE = "当前驱动源：[联动] PLC 实测回读——点位编辑与步骤③已锁定，要改点请先[暂停跟随]"
_SOURCE_SIM = "当前驱动源：[仿真] 本机算出来的位姿（步骤③的播放动画同属此态）"
_PAUSED_TELL = "⏸ 已暂停：PLC 置暂停态（软件只发脉冲命令，见到状态位即清命令字）——点[▶ 继续]恢复"
_OVERRIDES = (25, 50, 75, 100)   # 倍率档（SpeedOverride 合法域内的常用档；真值取 currentData）
_PREFERS = ("连续", "逐段")       # 执行偏好（Δ-1：⛔ 不叫手动/半自动/全自动，模式归 PLC）


class Step5Pane(QWidget):
    """执行控制·下发页。信号＝用户意图；状态一律由控制器灌入（本页只投影、不计算）。"""

    connect_requested = Signal()
    disconnect_requested = Signal()
    follow_requested = Signal()
    unfollow_requested = Signal()
    halt_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    reset_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderCard")
        self._history: deque[str] = deque(maxlen=_HISTORY_MAX)
        self._up = self._following = self._busy = self._gate = self._paused = False
        self._build()
        self.reset()
        self._refresh()

    # --- 构建 --------------------------------------------------------------- #
    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(8)
        self._link = self._line("dim", _LINK_DOWN)
        self._conn = self._button("连接本机模拟器", self.connect_requested)
        self._disc = self._button("断开", self.disconnect_requested)
        link_row = QHBoxLayout()
        link_row.addWidget(self._conn, 1)
        link_row.addWidget(self._disc)
        self._resume_btn = self._button("▶ 继续", self.resume_requested)
        self._pause_btn = self._button("⏸ 暂停", self.pause_requested)
        self._halt_btn = self._button("⏹ 停止", self.halt_requested)
        self._reset_btn = self._button("⟲ 复位到起点", self.reset_requested)
        self._override = QComboBox()
        self._override.addItems([f"{value}%" for value in _OVERRIDES])
        self._override.setCurrentIndex(len(_OVERRIDES) - 1)   # 默认 100%＝现下发口径，不悄悄改速度
        self._prefer = QComboBox()
        self._prefer.addItems(_PREFERS)
        param_row = QHBoxLayout()
        for text, widget in (("倍率", self._override), ("执行偏好", self._prefer)):
            param_row.addWidget(QLabel(text))
            param_row.addWidget(widget)
        self._paused_line = self._line("warn")
        self._paused_line.setVisible(False)
        self._stages = [self._line("dim") for _ in STAGES]
        self._stage_note = self._line("dim")
        self._err = self._line("deny")
        self._err.setVisible(False)
        self._err_btn = self._button("查看日志", self.show_log)
        self._err_btn.setVisible(False)
        self._source = self._line("dim", _SOURCE_SIM)
        self._counts = self._line("dim")
        self._follow_btn = self._button("开始跟随", self.follow_requested)
        self._unfollow_btn = self._button("暂停跟随", self.unfollow_requested)
        move_row = QHBoxLayout()
        for widget in (self._follow_btn, self._unfollow_btn):
            move_row.addWidget(widget)
        self.send_note = self._line("dim")           # T08 门禁写人话原因的那一行（属性名不可改）
        self.send_btn = QPushButton("⇩ 下发执行")     # T08 门禁置灰的那个主按钮（属性名不可改）
        self.send_btn.setProperty("role", "primary")
        self.send_btn.setEnabled(False)
        cmd_row = QHBoxLayout()
        for widget in (self.send_btn, self._resume_btn, self._pause_btn, self._halt_btn, self._reset_btn):
            cmd_row.addWidget(widget)
        box.addLayout(cmd_row)
        box.addLayout(param_row)
        box.addWidget(self._paused_line)
        box.addWidget(self.send_note)
        box.addWidget(self._link)
        box.addLayout(link_row)
        box.addWidget(self._rule("握手进度（契约 §9.1）"))
        for label in self._stages:
            box.addWidget(label)
        box.addWidget(self._stage_note)
        box.addWidget(self._err)
        box.addWidget(self._err_btn)
        box.addStretch(1)
        box.addWidget(self._rule("实时联动（回读驱动模型）"))
        box.addLayout(move_row)
        box.addWidget(self._source)
        box.addWidget(self._counts)

    @staticmethod
    def _rule(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName("PaneTitle")
        return label

    @staticmethod
    def _line(tone: str, text: str = "") -> QLabel:
        """一行可换行的着色文字；`tone` 是 theme.py 的动态属性值 ⛔ 不是调色板（见模块 docstring）。"""
        label = QLabel(text)
        label.setObjectName("PlaceholderBody")
        label.setWordWrap(True)
        label.setProperty("tone", tone)
        return label

    @staticmethod
    def _button(text: str, slot) -> QPushButton:
        button = QPushButton(text)
        button.clicked.connect(slot)
        return button

    def _repaint(self, label: QLabel, tone: str) -> None:
        """换 tone 后必须 unpolish/polish，否则 QSS 不重算（theme.py 的铁律）。"""
        label.setProperty("tone", tone)
        label.style().unpolish(label)
        label.style().polish(label)

    # --- 控制器灌入：链路 ---------------------------------------------------- #
    def set_up(self, on: bool, text: str = "") -> None:
        """链路可用性（`text` 非空即顺手写链路行）。连上＝绿、没连＝灰：「未连接」是正常待机态
        而不是错误（错误一律走红条），⛔ 不用红色。"""
        self._up = on
        if text:
            self.set_link(text, "ok" if on else "dim")
        self._refresh()

    def set_link(self, text: str, tone: str) -> None:
        self._link.setText(text)
        self._repaint(self._link, tone)
        self.remember(text)

    # --- 控制器灌入：握手五段进度 --------------------------------------------- #
    def reset(self) -> None:
        """一次下发的开头：五段全回「待」、进度说明与红条清空、计数归零（⛔ 不留上一轮的痕迹）。"""
        for index in range(len(self._stages)):
            self._paint_stage(index, _IDLE)
        self._stage_note.setText("")
        self.clear_error()
        self._paused_line.setVisible(False)   # 上一轮的暂停提示一并清（按钮态由 _refresh 重算）
        self.set_counts(0, 0, "")

    def set_stage(self, stage: int, text: str = "") -> None:
        """把第 `stage` 段（1-based）标为**进行中**、其前的标为完成、其后的标为待。"""
        for index in range(len(self._stages)):
            state = _DONE if index + 1 < stage else (_RUN if index + 1 == stage else _IDLE)
            self._paint_stage(index, state)
        self._note(stage, text, "accent")

    def finish_stage(self, stage: int, text: str = "") -> None:
        """把第 `stage` 段标为**完成**（走完五段后控制器逐段调它，或直接调 `all_done`）。"""
        self._paint_stage(stage - 1, _DONE)
        self._note(stage, text, "ok")

    def all_done(self, text: str = "") -> None:
        for index in range(len(self._stages)):
            self._paint_stage(index, _DONE)
        self._note(len(self._stages), text, "ok")

    def fail_stage(self, stage: int, text: str) -> None:
        """把第 `stage` 段标为**失败**（⛔ 不改它之前那些段的完成态：走到哪一步失败要说得出来）。"""
        self._paint_stage(stage - 1, _FAIL)
        self._note(stage, f"失败：{text}", "deny")

    def _note(self, stage: int, text: str, tone: str) -> None:
        if not text:
            return
        self._stage_note.setText(f"[阶段 {stage}/{len(self._stages)}] {text}")
        self._repaint(self._stage_note, tone)
        self.remember(f"[阶段{stage}] {text}")

    def _paint_stage(self, index: int, state: str) -> None:
        label = self._stages[index]
        label.setText(f"{_ICON[state]} {index + 1}. {STAGES[index]}")
        self._repaint(label, _TONE[state])

    # --- 控制器灌入：异常红条与日志 ------------------------------------------- #
    def show_error(self, text: str) -> None:
        """红条（卡片步骤④：PLC 拒绝→红条＋原因码＋[查看日志]）。文字由控制器给，⛔ 本页不改写。"""
        self._err.setText(f"⛔ {text}")
        self._err.setVisible(True)
        self._err_btn.setVisible(True)
        self.remember(f"⛔ {text}")

    def clear_error(self) -> None:
        self._err.setText("")
        self._err.setVisible(False)
        self._err_btn.setVisible(False)

    def remember(self, line: str) -> None:
        """往[查看日志]的历史里追加一条（有界）。⛔ 状态栏只显示最新一条，追查得靠这份历史。"""
        if line:
            self._history.append(line)

    def history(self) -> tuple[str, ...]:
        return tuple(self._history)

    def show_log(self) -> None:
        """[查看日志]：只读全文弹窗（用 QPlainTextEdit 而非消息框折叠区——离屏取证要能读到全文）。"""
        box = QDialog(self)
        box.setWindowTitle("下发与联动日志")
        box.resize(720, 420)
        layout = QVBoxLayout(box)
        view = QPlainTextEdit("\n".join(self._history) or "（还没有日志）")
        view.setReadOnly(True)
        close = QPushButton("关闭")
        close.clicked.connect(box.accept)
        layout.addWidget(view)
        layout.addWidget(close)
        box.exec()

    # --- 控制器灌入：跟随、计数与忙态 ------------------------------------------ #
    def set_follow(self, on: bool) -> None:
        """跟随态（卡片步骤③ 模式互斥）：驱动源那一行写明现在是[联动]还是[仿真]，⛔ 不只靠顶栏徽标。"""
        self._following = on
        self._source.setText(_SOURCE_LIVE if on else _SOURCE_SIM)
        self._repaint(self._source, "ok" if on else "dim")
        self.remember(self._source.text())
        self._refresh()

    def set_counts(self, accepted: int, dropped: int, note: str = "") -> None:
        """帧计数与**越界丢帧**计数（卡片步骤④第三例的可见证据）；丢过帧即整行变红。"""
        text = f"已采用 {accepted} 帧 · 已丢弃 {dropped} 帧"
        self._counts.setText(f"{text}（{note}）" if note else text)
        self._repaint(self._counts, "deny" if dropped else "dim")

    def set_busy(self, on: bool) -> None:
        """一次下发在途／结束（⛔ 能不能发不在此判——那属 `linkctl` 在途锁与 T08 门禁）。"""
        self._busy = on
        self._refresh()

    def set_paused(self, on: bool) -> None:
        """PLC 暂停态（`status` 的 ST_PAUSED 位，控制器从回读帧投影）。"""
        if on != self._paused:
            self._paused = on
            self._paused_line.setText(_PAUSED_TELL)
            self._paused_line.setVisible(on)
            self.remember(_PAUSED_TELL if on else "已恢复：PLC 清暂停态，继续执行")
            self._refresh()

    def override_pct(self) -> float:
        return float(self._override.currentText().rstrip("%") or _OVERRIDES[-1])   # §9.1 步 1 倍率

    def preference(self) -> str:
        # 执行偏好（软件侧，Δ-1 的「连续/逐段」——语义说明在 _PREFERS 常量处）
        return self._prefer.currentText()

    def set_gate(self, on: bool) -> None:
        """T08 禁发门禁的镜像（`checkctl._refresh_gate` 追加一行调它）：本页据此在忙态结束后还原按钮。"""
        self._gate = on
        self._refresh()

    def _refresh(self) -> None:
        self._conn.setEnabled(not self._up and not self._busy)
        self._disc.setEnabled(self._up and not self._busy)
        self._follow_btn.setEnabled(self._up and not self._following)
        self._unfollow_btn.setEnabled(self._following)
        self._pause_btn.setEnabled(self._up and self._busy and not self._paused)
        self._resume_btn.setEnabled(self._up and self._busy and self._paused)
        self._halt_btn.setEnabled(self._up and self._busy)
        self._reset_btn.setEnabled(self._up and not self._busy)
        self.send_btn.setEnabled(self._gate and not self._busy)
