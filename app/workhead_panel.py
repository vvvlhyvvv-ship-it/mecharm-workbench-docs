"""右栏常驻面板①：多功能臂 · 工作头（01 蓝图 §3.6-1；T13）。

五臂列表＝嵌入的 ``WorkModeSelector``（G16 语义原样：未选定→切换二次确认→committed/switched，
外观迁为①–⑤行、★＝当前主工作头）。参数行口径（§1-1 无数据禁造值）：
  行程范围＝该模式 ``axes[].travel`` 汇总的**真值**（直线轴/回转轴各自取并集，单位分列）；
  额定负载／末端形式＝``modes[]`` 实测只有 ``id``/``name``/``axes`` 三键 ⇒ **恒显「—」**（演示稿的
  1 200 kg／夹钳 TOOL-01 是演示数据，Δ-6 ⛔ 禁上屏）；「特写跟随 TCP」期 3（Δ-7 禁用＋如实提示）。
颜色/字号走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtWidgets import (QGridLayout, QLabel, QPushButton, QVBoxLayout, QWidget)

from app.mode import WorkModeSelector
from core.config import MachineConfig

DASH = "—"
LATER_NOTE = "待后续版本"


class WorkheadPanel(QWidget):
    """工作头面板。``selector`` 由外壳构造传入（控制器构造期就要用它的引用）。"""

    def __init__(self, selector: WorkModeSelector, cfg: MachineConfig,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._cfg = cfg
        self._selector = selector
        title = QLabel("多功能臂 · 工作头")
        title.setObjectName("PaneTitle")
        self.current_badge = QLabel("未选定")
        self.current_badge.setProperty("tone", "dim")
        self.rows = selector._rows                     # e2e/收单读行原文（选择器自己的行控件）
        self.travel_label = QLabel(DASH)
        self.load_label = QLabel(DASH)
        self.tip_label = QLabel(DASH)
        self.load_label.setToolTip("modes 未含额定负载字段（machine.yaml），回执前如实显示「—」")
        self.tip_label.setToolTip("modes 未含末端形式字段（machine.yaml），回执前如实显示「—」")
        self.tcp_btn = QPushButton("特写跟随 TCP")
        self.tcp_btn.setEnabled(False)
        self.tcp_btn.setToolTip(LATER_NOTE)
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(2)
        for r, (key, lab) in enumerate((("行程范围", self.travel_label),
                                        ("额定负载", self.load_label),
                                        ("末端形式", self.tip_label))):
            key_label = QLabel(key)
            key_label.setProperty("tone", "dim")
            grid.addWidget(key_label, r, 0)
            grid.addWidget(lab, r, 1)
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 8, 10, 8)
        box.setSpacing(8)
        head = QVBoxLayout()
        head.setSpacing(0)
        head.addWidget(title)
        head.addWidget(self.current_badge)
        box.addLayout(head)
        box.addWidget(selector)
        box.addLayout(grid)
        box.addWidget(self.tcp_btn)
        box.addStretch(1)
        selector.committed.connect(lambda _name: self.refresh())
        self.refresh()

    def refresh(self) -> None:
        """按当前已生效模式回填参数行；未选定 ⇒ 全「—」。"""
        mode = self._selector.current_mode()
        self.current_badge.setText("未选定" if mode is None else f"当前主工作头：{mode}")
        self.current_badge.setProperty("tone", "dim" if mode is None else "accent")
        self.travel_label.setText(self._travel_summary(mode))
        self.travel_label.setToolTip("按该模式各轴 travel 汇总（machine.yaml，占位回执前非实测）")

    def _travel_summary(self, mode: str | None) -> str:
        if mode is None:
            return DASH
        axes = [self._cfg.axes[a] for m in self._cfg.modes
                if m.name == mode for a in m.axes]
        parts = []
        for kind, unit in (("prismatic", "mm"), ("revolute", "°")):
            spans = [a.travel for a in axes if a.type == kind]
            if spans:
                lo = min(min(s) for s in spans)
                hi = max(max(s) for s in spans)
                parts.append(f"直线轴 {lo:g}–{hi:g} {unit}" if kind == "prismatic"
                             else f"回转轴 {lo:g}–{hi:g} {unit}")
        return " · ".join(parts) if parts else DASH
