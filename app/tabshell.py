"""左栏三页签容器（01 蓝图 §3.4；T13）。

页签头高 36px（theme ``tab_h``）：装配树(件数)｜编程(工步数)｜路径仿真(干涉数)；徽标一律
**真实内核值、无则 0**（Δ-6 禁演示数字），由外壳按 ``set_badge`` 回填。页签体：装配树＝
``AssemblyTreePane``（工具行见那件）；编程＝``prog_tab.ProgTab``；路径仿真＝``sim_tab.SimTab``
——**两件的 import 类名固定**，T14/T15 重写其内部即可换体，⛔ 不回改本件（挂点预埋，T13 卡
步骤 8-②）。导航职责自 StepBar 移交至此（StepBar 退役为薄壳，99 台账 L-7）。
颜色/字号走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from app.assemblytree import AssemblyTreePane
from app.prog_tab import ProgTab
from app.sim_tab import SimTab
from app.theme import TOKENS

TITLES = (("tree", "装配树"), ("prog", "编程"), ("sim", "路径仿真"))
_KEYS = tuple(k for k, _ in TITLES)


class TabShell(QWidget):
    """三页签；switch_to 切页、set_badge 写徽标。``switched(str)``＝当前页 key 变化。"""

    switched = Signal(str)

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("LeftPane")
        self.tree_pane = AssemblyTreePane()
        self.prog = ProgTab(panel)                   # 暂挂初版（T14 重写换体）
        self.sim = SimTab(panel)                     # 暂挂初版（T15 重写换体）
        self._current = "tree"
        self._tabs: dict[str, QPushButton] = {}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        bar = QWidget()
        bar.setFixedHeight(int(TOKENS["tab_h"]))
        row = QHBoxLayout(bar)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(0)
        for key, title in TITLES:
            btn = QPushButton(f"{title} 0")
            btn.setProperty("step", "true")          # 复用 theme 的步骤钮三态样式（选中=青底）
            btn.setCheckable(True)
            btn.clicked.connect(lambda _=False, k=key: self.switch_to(k))
            self._tabs[key] = btn
            row.addWidget(btn)
        self._stack = QStackedWidget()
        self._stack.addWidget(self.tree_pane)        # index 与 TITLES 序一致
        self._stack.addWidget(self.prog)
        self._stack.addWidget(self.sim)
        box.addWidget(bar)
        box.addWidget(self._stack, 1)
        self.switch_to("tree")

    @property
    def tree(self):
        """装配树本体（外壳连 selected/focused 用；T05 语义原样）。"""
        return self.tree_pane.tree

    def current(self) -> str:
        return self._current

    def switch_to(self, key: str) -> None:
        self._current = key
        self._stack.setCurrentIndex(_KEYS.index(key))
        for k, btn in self._tabs.items():
            on = k == key
            btn.setChecked(on)
            btn.setProperty("state", "current" if on else "todo")
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        self.switched.emit(key)

    def set_badge(self, key: str, count: int) -> None:
        title = dict(TITLES)[key]
        self._tabs[key].setText(f"{title} {max(count, 0)}")

    def badge_text(self, key: str) -> str:
        """徽标原文（e2e 读操作员可见的那一份）。"""
        return self._tabs[key].text().rsplit(" ", 1)[-1]
