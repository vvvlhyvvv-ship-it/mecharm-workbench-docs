"""编程页签体·暂挂初版（T13；**T14 重排中**——本件整体重写换体，tabshell 不回改）。

暂挂形态＝右栏旧步骤①–③页（step1_import／step2_pick／step3_path）纵向堆叠进滚动区：
五步向导的右栏页原样搬进来，业务接线（imported/waypoints_changed/set_mode …）在 shell/wiring，
**语义零改动**——「五臂选定锁取点区」仍由 step2.set_mode 内部锁定（G16，挂点变、锁不变）。
成形（四步流水线指示、点位表/步骤/段清单、CSV/JSON 存取、三维导入浮层）归 T14。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

LATER_NOTE = "T14 重排中：本页暂挂旧步骤①–③页"


class ProgTab(QWidget):
    """编程页签体（暂挂初版）。构造签名 ``ProgTab(panel)`` 固定——T14 换体仍从 panel 取业务页。"""

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        note = QLabel(LATER_NOTE)
        note.setProperty("tone", "dim")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        stack = QWidget()
        box = QVBoxLayout(stack)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(8)
        box.addWidget(note)
        for page in (panel.step1, panel.step2, panel.step3):
            box.addWidget(page)
            page.show()                    # 摘自 Panel 的 QStackedWidget 时带着隐藏态，须显式复显
        box.addStretch(1)
        scroll.setWidget(stack)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
