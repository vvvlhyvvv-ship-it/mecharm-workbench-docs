"""右栏上下文面板（02 设计方案 §2/§5：内容随步骤切换，T02 阶段全是占位）。

外壳阶段不实现任何业务：五个占位页各显示步骤名 + “功能开发中（TXX）”，
TXX 是将来填充该步的业务单号（①→T05 ②→T06 ③→T07 ④→T08 ⑤→T10）。
每页放一个**禁用**的主按钮占位，用来落地“主按钮 16px 粗体、高≥40px、占右栏整宽”
的视觉硬指标（02 §4），不构成任何取点/路径/碰撞业务。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QFrame,
    QLabel,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.stepbar import STEP_LABELS
from app.steps.step1_import import Step1Pane
from app.steps.step2_pick import Step2Pane

# 步骤②-⑤的将来业务单号与该步主按钮文案；步骤①已是 Step1Pane、步骤②已是 Step2Pane（T06），
# 故本表仅 ③-⑤（T07/T08/T10）仍走占位页；首项 T06 保留作「步骤②已落地为何业务」的对照。
_STEP_META: tuple[tuple[str, str], ...] = (
    ("T06", "命名当前点"),
    ("T07", "生成路径"),
    ("T08", "开始校核"),
    ("T10", "下发 PLC"),
)


class Panel(QWidget):
    """右栏上下文栈；set_step(n) 切换到第 n 步占位页（1-based）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RightPane")
        self._stack = QStackedWidget()
        self.step1 = Step1Pane()
        self.step2 = Step2Pane()
        self._stack.addWidget(self.step1)
        self._stack.addWidget(self.step2)
        for label, (txx, btn_text) in zip(STEP_LABELS[2:], _STEP_META[1:]):
            self._stack.addWidget(self._make_page(label, txx, btn_text))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        title = QLabel("上下文")
        title.setObjectName("PaneTitle")
        layout.addWidget(title)
        layout.addWidget(self._stack, 1)

    def _make_page(self, label: str, txx: str, btn_text: str) -> QWidget:
        card = QFrame()
        card.setObjectName("PlaceholderCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(12)
        name = QLabel(label)
        name.setObjectName("PlaceholderTitle")
        body = QLabel(f"功能开发中（{txx}）")
        body.setObjectName("PlaceholderBody")
        body.setWordWrap(True)
        btn = QPushButton(btn_text)
        btn.setProperty("role", "primary")
        btn.setEnabled(False)  # 占位：业务未接入，禁点
        box.addWidget(name)
        box.addWidget(body)
        box.addStretch(1)
        box.addWidget(btn)
        return card

    def set_step(self, n: int) -> None:
        """切换到第 n 步（1-based）的占位页。"""
        if 1 <= n <= self._stack.count():
            self._stack.setCurrentIndex(n - 1)
