"""模式与状态组件（02 V2.0 §3；T13 迁右栏改造）。

三个件：
  ModeBadge        [仿真]蓝 / [联动]绿，互斥常显——用户任何时刻知道模型动是真是假（T13 起住顶栏灯组）
  OnlineLight      链路灯：在线绿/离线灰（T02 起）＋可选实测 Hz 文案「● 实时 N Hz」（T13，蓝图 §3.3-6）
  WorkModeSelector 五臂选择列表（G16，2026-09-15 定）：声明当前所挂多功能臂、决定有效轴子集；
                   T13 由顶栏下拉迁为右栏「多功能臂 · 工作头」面板的①–⑤行列表（裁决见 01 蓝图
                   §3.6），模式名自 machine.yaml ``modes`` 读出（⛔ 不在代码里写死臂名/轴名）。
                   选定/作废语义原样：初始「未选定」，切换需二次确认，确认后广播 committed/switched。

对外接口（与旧 QComboBox 版兼容处仅保留控制器在用的部分）：``current_mode()``＋
``committed(str)``／``switched(str)``；``select_row(i)``＝程序化点第 i 行（0-based，e2e 走真控件路径）。
颜色/字号一律走 app.theme 的全局 QSS（按动态属性 badge/online/sel 选择），本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QLabel, QMessageBox, QVBoxLayout, QWidget

from core.config import REPO_ROOT, MachineConfig, load_machine

UNSELECTED = "未选定"
_MODES_YAML = REPO_ROOT / "config" / "machine.yaml"


def _mode_names(cfg: MachineConfig | None) -> tuple[str, ...]:
    """臂名清单：优先调用方给的 cfg，缺省自 machine.yaml 读（单一来源 ⛔ 不写死）。"""
    src = cfg or load_machine(str(_MODES_YAML))
    return tuple(m.name for m in src.modes)


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
    """链路灯：颜色+文字双通道。在线且给过实测频率 ⇒ 「● 实时 N Hz」；无频率 ⇒ 「● 在线」；
    离线 ⇒ 「● 离线」（ livectl 仍按单参 set_online(bool) 调，行为不变）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._hz: float | None = None
        self.set_online(False)

    def set_online(self, online: bool, hz: float | None = None) -> None:
        """在线态由链路回调驱动；hz 缺省沿用上次的实测值（None＝尚无 ⇒ 只写「在线」）。"""
        if hz is not None:
            self._hz = hz
        self._online = online
        self._refresh()

    def set_hz(self, hz: float | None) -> None:
        """实测回读频率（T13 顶栏 Hz 计供给）；None＝停测 ⇒ 回落「在线」文案。"""
        self._hz = hz
        if hasattr(self, "_online"):
            self._refresh()

    def _refresh(self) -> None:
        text = "● 离线" if not self._online else (
            f"● 实时 {self._hz:.1f} Hz" if self._hz is not None else "● 在线")
        self.setProperty("online", "true" if self._online else "false")
        self.setText(text)
        self.style().unpolish(self)
        self.style().polish(self)


class WorkModeSelector(QWidget):
    """五臂选择列表（G16）。行＝编号①–⑤＋臂名，当前行前缀 ★（选中态属性 sel）。

    信号（语义与旧下拉一致）：
      committed(str)  某模式生效（首次选定或确认切换后）——shell 据此解锁取点区
      switched(str)   发生了「切换」（从一个已选模式换到另一个）——shell 据此广播结果作废
    """

    committed = Signal(str)
    switched = Signal(str)

    def __init__(self, cfg: MachineConfig | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._names = _mode_names(cfg)
        self._guard = False
        self._previous_mode: str | None = None  # 当前已生效模式（None=未选定）
        self._rows: list[_Row] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        for index, name in enumerate(self._names, start=1):
            row = _Row(index - 1, f"{_CIRCLED[index - 1]} {name}")
            row.setProperty("sel", "false")
            row.setToolTip(f"设为主工作头（{name}）")
            row.picked.connect(self._on_pick)
            self._rows.append(row)
            box.addWidget(row)
        self._repaint()

    def current_mode(self) -> str | None:
        """当前已生效的工作模式名；未选定返回 None。"""
        return self._previous_mode

    def select_row(self, index: int) -> None:
        """程序化「点」第 index 行（0-based；越界忽略）——与真点击同一条受理链。"""
        if 0 <= index < len(self._rows):
            self._on_pick(index)

    def _on_pick(self, index: int) -> None:
        if self._guard:
            return
        name = self._names[index]
        prev = self._previous_mode
        if prev is None:
            self._previous_mode = name
            self._repaint()
            self.committed.emit(name)
            return
        if prev == name:
            return
        if not self._confirm_switch(prev, name):
            return                                    # 不换：保持原行，无信号
        self._previous_mode = name
        self._repaint()
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

    def _repaint(self) -> None:
        for index, row in enumerate(self._rows):
            on = self._names[index] == self._previous_mode
            row.setText(f"★ {_CIRCLED[index]} {self._names[index]}" if on
                        else f"{_CIRCLED[index]} {self._names[index]}")
            row.setProperty("sel", "true" if on else "false")
            row.style().unpolish(row)
            row.style().polish(row)


# ①–⑤ 编号（演示稿 lrow 的圈号；不足五位按臂数自然截断）
_CIRCLED = ("①", "②", "③", "④", "⑤", "⑥", "⑦", "⑧", "⑨")


class _Row(QLabel):
    """可点行：按下即发 picked(行号)（QLabel 没有 clicked，鼠标按下就是「点」）。"""

    picked = Signal(int)

    def __init__(self, index: int, text: str) -> None:
        super().__init__(text)
        self._index = index
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def mousePressEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        if event.button() == Qt.MouseButton.LeftButton:
            self.picked.emit(self._index)
        super().mousePressEvent(event)
