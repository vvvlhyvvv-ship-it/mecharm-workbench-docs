"""顶栏模式与状态组件（02 设计方案 §3 ＋ §1 顶栏）。

三个独立 QWidget：
  ModeBadge        [仿真]蓝 / [联动]绿，互斥常显——用户任何时刻知道模型动是真是假
  OnlineLight      OPC UA 在线灯：绿在线 / 灰离线（T02 阶段无通讯，默认离线）
  WorkModeSelector 工作模式五选一（G16，2026-09-15 定）：声明当前所挂多功能臂，
                   决定有效轴子集；初始“未选定”，切换需二次确认，确认后广播“结果作废”。

颜色/字号一律走 app.theme 的全局 QSS（按动态属性 badge/online 选择），本模块不写内联样式。
外壳（shell）只消费这里的信号负责置灰与发消息，业务清空动作由后续单接线。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QLabel, QMessageBox, QWidget

# 五种工作模式（02 §3 工作模式行原文）；语义＝当前所挂多功能臂。
WORK_MODES: tuple[str, ...] = (
    "打磨臂",
    "氧化皮吸附臂",
    "脱模剂喷涂臂",
    "氧化皮破碎臂",
    "玻璃垫放置臂",
)
UNSELECTED = "未选定"


class ModeBadge(QLabel):
    """模式徽标：仿真（算出来的）/ 联动（跟实机同步）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_mode("sim")

    def set_mode(self, mode: str) -> None:
        """mode ∈ {'sim','live'}；非法值按 sim 处理（外壳态不应崩）。"""
        live = mode == "live"
        self.setProperty("badge", "live" if live else "sim")
        self.setText("联动" if live else "仿真")
        self.style().unpolish(self)
        self.style().polish(self)


class OnlineLight(QLabel):
    """OPC UA 在线灯：绿在线 / 灰离线（颜色+文字双通道）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_online(False)

    def set_online(self, online: bool) -> None:
        self.setProperty("online", "true" if online else "false")
        self.setText("● 在线" if online else "● 离线")
        self.style().unpolish(self)
        self.style().polish(self)


class WorkModeSelector(QComboBox):
    """工作模式下拉（G16）。

    信号：
      committed(str)  某模式生效（首次选定或确认切换后）——shell 据此解锁步骤②-⑤
      switched(str)   发生了“切换”（从一个已选模式换到另一个）——shell 据此广播结果作废
    """

    committed = Signal(str)
    switched = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._guard = False
        self._previous_mode: str | None = None  # 当前已生效模式（None=未选定）
        self.addItem(UNSELECTED, None)
        for name in WORK_MODES:
            self.addItem(name, name)
        self.setCurrentIndex(0)
        self.currentIndexChanged.connect(self._on_change)

    def current_mode(self) -> str | None:
        """当前所选工作模式名；未选定返回 None。"""
        return self.currentData()

    def _on_change(self, index: int) -> None:
        if self._guard or index <= 0:
            return
        prev = self._previous_mode
        name = self.itemData(index)
        if prev is None:
            self._previous_mode = name
            self.committed.emit(name)
            return
        if prev == name:
            return
        if not self._confirm_switch(prev, name):
            self._revert_to(prev)
            return
        self._previous_mode = name
        self.switched.emit(name)
        self.committed.emit(name)

    def _confirm_switch(self, prev: str, name: str) -> bool:
        box = QMessageBox(self)
        box.setWindowTitle("切换工作模式")
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(f"切换工作模式将清空当前点位与路径，继续？\n（{prev} → {name}）")
        box.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def _revert_to(self, name: str) -> None:
        idx = self.findData(name)
        self._guard = True
        self.setCurrentIndex(idx if idx >= 0 else 0)
        self._guard = False
