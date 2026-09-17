"""右栏上下文面板（02 设计方案 §2/§5：内容随步骤切换）。

本模块只做**装页与切页**，⛔ 不含任何业务：五步的业务页各在自己文件里
（①`app/steps/step1_import.py` ②`step2_pick.py` ③`step3_path.py` ④`step4_check.py` ⑤`step5_send.py`），
控制器在 `app/pathctl.py`／`app/checkctl.py`／`app/sendctl.py`。

`send_btn`／`send_note` 两个属性名照旧交回给 `app.checkctl` 做**禁发门禁**（T08 卡片步骤 5 的第一条拦截）；
T10 起它们指向 `Step5Pane` 上的同名控件，门禁代码零改动。
"""

from __future__ import annotations

from PySide6.QtWidgets import (
    QLabel,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from app.steps.step1_import import Step1Pane
from app.steps.step2_pick import Step2Pane
from app.steps.step3_path import Step3Pane
from app.steps.step4_check import Step4Pane
from app.steps.step5_send import Step5Pane


class Panel(QWidget):
    """右栏上下文栈；set_step(n) 切换到第 n 步（1-based）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("RightPane")
        self._stack = QStackedWidget()
        self.step1 = Step1Pane()
        self.step2 = Step2Pane()
        self.step3 = Step3Pane()
        self.step4 = Step4Pane()
        self.step5 = Step5Pane()
        for page in (self.step1, self.step2, self.step3, self.step4, self.step5):
            self._stack.addWidget(page)
        self.send_btn = self.step5.send_btn      # T08 门禁置灰的那个主按钮（属性名不可改）
        self.send_note = self.step5.send_note    # T08 门禁写人话原因的那一行（属性名不可改）
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(8)
        title = QLabel("上下文")
        title.setObjectName("PaneTitle")
        layout.addWidget(title)
        layout.addWidget(self._stack, 1)

    def set_step(self, n: int) -> None:
        """切换到第 n 步（1-based）的业务页。"""
        if 1 <= n <= self._stack.count():
            self._stack.setCurrentIndex(n - 1)
