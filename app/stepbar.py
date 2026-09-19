"""顶栏五步进度条（02 设计方案 §1：步骤条即导航；02 V2.0 起范式切换）。

⚠️ **T13 起退役为薄壳（99 台账 L-7，⛔ 不是 git rm）**：导航职责移交 `app/tabshell.py` 三页签；
本件保留 `STEP_LABELS` 与 `StepBar` 类，shell 仍实例化 `self.stepbar` 但**不加入任何布局**（界面上
不可见）——`mark_completed()`／`step_clicked` 信号／`_completed` 供 `app/checkctl.py`／`pathctl.py`／
`sendctl.py`、`tools/e2e_rig.py` 与冻结取证脚本（evidence/T07、T08）照常使用。步骤完成态改由页签
徽标＋页内四步流水线指示（T14）表达；step1–5 的 `STEP_LABELS` 引用由 T14/T15/T16 各自清理，
最后清理者（或指挥方）删件。

三态：当前步高亮 / 未达置灰不可跳 / 完成可回看。对外只暴露：
  set_step_enabled(n, bool)  开关某步是否可达（置灰↔可点）
  set_current(n)             设当前步（高亮）
  mark_completed(n)          标记某步完成（变为可回看）
  step_clicked(int) 信号     用户点了某步（仅可达步会触发）

n 一律 1-based（①=1 … ⑤=5），与 02 文案的步骤序号一致。
颜色/字号来自 app.theme 的全局 QSS（按动态属性 state 选择），本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

STEP_LABELS: tuple[str, ...] = ("①导入", "②选点", "③路径", "④校核", "⑤下发")


class StepBar(QWidget):
    """五步条；置灰/高亮/回看逻辑在此，业务接线由 shell 负责。"""

    step_clicked = Signal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StepBar")
        self._count = len(STEP_LABELS)
        self._enabled = [True] + [False] * (self._count - 1)  # 初始仅①可达
        self._completed = [False] * self._count
        self._current = 1
        self._buttons: list[QPushButton] = []
        self._build()
        self._refresh()

    def _build(self) -> None:
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 0, 8, 0)
        layout.setSpacing(8)
        for i, label in enumerate(STEP_LABELS, start=1):
            btn = QPushButton(label)
            btn.setProperty("step", "true")
            btn.setToolTip(label)
            btn.clicked.connect(lambda _=False, n=i: self._on_click(n))
            self._buttons.append(btn)
            layout.addWidget(btn)
        layout.addStretch(1)

    def _on_click(self, n: int) -> None:
        if self._enabled[n - 1]:
            self.step_clicked.emit(n)

    def _refresh(self) -> None:
        """按 enabled/current/completed 重算每个按钮的 state 属性并复刷样式。"""
        for i, btn in enumerate(self._buttons, start=1):
            if not self._enabled[i - 1]:
                state = "off"
            elif i == self._current:
                state = "current"
            elif self._completed[i - 1]:
                state = "done"
            else:
                state = "todo"
            btn.setProperty("state", state)
            btn.setEnabled(self._enabled[i - 1])
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def set_step_enabled(self, n: int, enabled: bool) -> None:
        """开关第 n 步（1-based）是否可达；置灰即不可点。"""
        self._check_range(n)
        self._enabled[n - 1] = enabled
        self._refresh()

    def set_current(self, n: int) -> None:
        """设当前步并高亮；当前步自动置为可达。"""
        self._check_range(n)
        self._current = n
        self._enabled[n - 1] = True
        self._refresh()

    def mark_completed(self, n: int) -> None:
        """标记第 n 步完成（变为可回看态）。"""
        self._check_range(n)
        self._completed[n - 1] = True
        self._refresh()

    def current_step(self) -> int:
        return self._current

    def _check_range(self, n: int) -> None:
        if not 1 <= n <= self._count:
            raise ValueError(f"步骤号超出范围 1..{self._count}: {n}")
