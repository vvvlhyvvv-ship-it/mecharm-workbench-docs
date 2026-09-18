"""路径仿真页签体·暂挂初版（T13；**T15 重排中**——本件整体重写换体，tabshell 不回改）。

暂挂形态＝右栏旧步骤④–⑤页（step4_check／step5_send）纵向堆叠＋**干涉清单空容器挂点**
（T16 填：按设备归并清单＋干涉对明细；本件只留容器与注释，⛔ 不做占位假表）。step4 三态卡
暂挂其中——T16 退役吸收，T15 重写时不迁入（T13 卡步骤 8-③）。执行控制组、时间轴、KPI 行、
轨迹清单表归 T15。
"""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QScrollArea, QVBoxLayout, QWidget

LATER_NOTE = "T15 重排中：本页暂挂旧步骤④–⑤页"
CLASH_HOOK = "T16 挂点：干涉清单区（按设备归并＋干涉对明细）——本容器届时由 T16 填充"


class SimTab(QWidget):
    """路径仿真页签体（暂挂初版）。构造签名 ``SimTab(panel)`` 固定——T15 换体仍从 panel 取业务页。"""

    def __init__(self, panel, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        note = QLabel(LATER_NOTE)
        note.setProperty("tone", "dim")
        clash = QLabel("干涉清单 · 待接入")
        clash.setProperty("tone", "dim")
        clash.setToolTip(CLASH_HOOK)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        stack = QWidget()
        box = QVBoxLayout(stack)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(8)
        box.addWidget(note)
        box.addWidget(panel.step4)                   # 三态卡：T16 退役吸收（T15 重写不迁入）
        panel.step4.show()                           # 摘自 Panel 的栈页带着隐藏态，须显式复显
        box.addWidget(panel.step5)
        panel.step5.show()
        box.addWidget(clash)                         # 空容器挂点（T16）
        box.addStretch(1)
        scroll.setWidget(stack)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
