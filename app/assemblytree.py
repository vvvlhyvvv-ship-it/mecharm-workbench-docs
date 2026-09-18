"""左栏装配树（T05 建树；T13 挂入页签＋工具行，裁决 6）。

两个件：
  AssemblyTree     树本体（QTreeWidget，T05 语义原样：单击 selected／双击 focused 携叶子 id）；
                   T13 增**选中记忆**：``selected_ids()``＝最近点选的叶子 id（「删除选中」用）、
                   ``selected_group_ids()``＝其顶层组的叶子 id（「删除整组」用；顶层零件＝自身）。
  AssemblyTreePane 装配树页签体：工具行＝「删除选中（未选中 disabled，演示稿同位）／删除整组／
                   清空全部模型（二次确认，``_ask`` 可替身）」＋「选中件装配」三选/绑定到/应用/解除
                   **按演示稿位置渲染但一律禁用**＋「待后续版本」（Δ-9：``pose.update`` 按连杆名
                   下发装不下任意导入件、``length_mm`` 全占位 0.0 ⇒ 推期 3，裁决 6）。
                   动作只发高层信号（delete_selected/delete_group/clear_all），删除的几何重建在
                   core.geometry 纯函数、失效接线在 wiring（本控件不碰桥/不碰 core）。
颜色/字号走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QMessageBox, QPushButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

LATER_NOTE = "待后续版本"
CLEAR_TITLE = "清空全部模型"
# 每个 item 的 data 槽：节点 id 与「是否装配」。
_ROLE_ID = Qt.ItemDataRole.UserRole
_ROLE_ASSY = Qt.ItemDataRole.UserRole + 1


class AssemblyTree(QTreeWidget):
    """装配树控件。信号 selected(list[int]) / focused(list[int]) 均携带叶子零件 id 列表。"""

    selected = Signal(object)
    focused = Signal(object)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setHeaderLabels(["零件 / 装配"])
        self._last_item: QTreeWidgetItem | None = None
        self.itemClicked.connect(self._on_click)
        self.itemDoubleClicked.connect(self._on_dblclick)

    def populate(self, nodes: list[dict]) -> None:
        """用 tree_payload 的嵌套 dict 重建树（先清空）；建完展开顶层两级。"""
        self.clear()
        self._last_item = None
        self._add_level(nodes, None)
        self.expandToDepth(1)

    def _add_level(self, nodes: list[dict], parent: QTreeWidgetItem | None) -> None:
        for n in nodes:
            item = QTreeWidgetItem(parent if parent is not None else self)
            item.setText(0, str(n.get("name", "")))
            item.setData(0, _ROLE_ID, int(n.get("id", -1)))
            item.setData(0, _ROLE_ASSY, bool(n.get("is_assembly", False)))
            self._add_level(n.get("children", []) or [], item)

    def _on_click(self, item: QTreeWidgetItem, _col: int) -> None:
        self._last_item = item
        ids = self._leaf_ids(item)
        if ids:
            self.selected.emit(ids)

    def _on_dblclick(self, item: QTreeWidgetItem, _col: int) -> None:
        ids = self._leaf_ids(item)
        if ids:
            self.focused.emit(ids)

    def selected_ids(self) -> list[int]:
        """最近点选的叶子 id（无点选/已清空 ⇒ 空表；「删除选中」的数据源）。"""
        return self._leaf_ids(self._last_item) if self._last_item is not None else []

    def selected_group_ids(self) -> list[int]:
        """最近点选节点所属**顶层组**的叶子 id（顶层零件＝自身；「删除整组」的数据源）。"""
        item = self._last_item
        if item is None:
            return []
        while item.parent() is not None:
            item = item.parent()
        return self._leaf_ids(item)

    def _leaf_ids(self, item: QTreeWidgetItem) -> list[int]:
        """叶子零件 → 自身 id；装配节点 → 其全部 descendant 叶子 id（递归收集）。"""
        if not item.data(0, _ROLE_ASSY):
            return [int(item.data(0, _ROLE_ID))]
        ids: list[int] = []
        for i in range(item.childCount()):
            ids.extend(self._leaf_ids(item.child(i)))
        return ids


class AssemblyTreePane(QWidget):
    """装配树页签体：工具行＋Δ-9 禁用行＋树。删除动作交外壳（core 纯函数重建＋失效机制）。"""

    delete_selected = Signal(object)     # list[int]：最近点选的叶子 id
    delete_group = Signal(object)        # list[int]：顶层组叶子 id
    clear_all = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.tree = AssemblyTree()
        self._del_sel = QPushButton("删除选中")
        self._del_sel.setEnabled(False)          # 演示稿同位：未选中即禁用
        self._del_sel.clicked.connect(
            lambda: self.delete_selected.emit(self.tree.selected_ids()))
        self._del_grp = QPushButton("删除整组")
        self._del_grp.clicked.connect(
            lambda: self.delete_group.emit(self.tree.selected_group_ids()))
        self._clear = QPushButton(CLEAR_TITLE)
        self._clear.clicked.connect(self._on_clear)
        tools = QHBoxLayout()
        tools.setSpacing(6)
        for btn in (self._del_sel, self._del_grp, self._clear):
            tools.addWidget(btn)
        tools.addStretch(1)
        bind_row, apply_row = self._build_mate_rows()
        box = QVBoxLayout(self)
        box.setContentsMargins(8, 8, 8, 8)
        box.setSpacing(6)
        box.addLayout(tools)
        box.addLayout(bind_row)
        box.addLayout(apply_row)
        box.addWidget(self.tree, 1)
        self.tree.selected.connect(self._on_tree_selected)

    # --- Δ-9：选中件装配（渲染但一律禁用，期 3 启用） ---------------------------- #
    def _build_mate_rows(self) -> tuple[QHBoxLayout, QHBoxLayout]:
        pick = QComboBox()
        pick.addItems(("固定（锁在世界坐标）", "关节绑定（跟随某轴）", "自由（不约束）"))
        pick.setEnabled(False)
        pick.setToolTip(LATER_NOTE)
        bind_label = QLabel("绑定到")
        bind = QComboBox()
        bind.setEnabled(False)
        bind.setToolTip(LATER_NOTE)
        apply_btn = QPushButton("应用")
        release = QPushButton("解除")
        for btn in (apply_btn, release):
            btn.setEnabled(False)
            btn.setToolTip(LATER_NOTE)
        row1 = QHBoxLayout()
        row1.addWidget(QLabel("选中件装配"))
        row1.addWidget(pick, 1)
        row2 = QHBoxLayout()
        row2.addWidget(bind_label)
        row2.addWidget(bind, 1)
        row2.addWidget(apply_btn)
        row2.addWidget(release)
        return row1, row2

    def _on_tree_selected(self, ids: list) -> None:
        self._del_sel.setEnabled(bool(ids) and self.tree.topLevelItemCount() > 0)

    def _on_clear(self) -> None:
        if self._ask(f"{CLEAR_TITLE}将删除视口内的全部模型，并作废当前路径与校核结果。继续？"):
            self.clear_all.emit()

    def _ask(self, text: str) -> bool:
        """二次确认（清空类动作）。e2e 以替身覆盖本方法（离屏无真操作员，判据核原文）。"""
        box = QMessageBox(self)
        box.setWindowTitle(CLEAR_TITLE)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setText(text)
        box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        box.setDefaultButton(QMessageBox.StandardButton.No)
        return box.exec() == QMessageBox.StandardButton.Yes

    def refresh_buttons(self) -> None:
        """场景变化（导入/删除/清空）后按树与选中态复算按钮；无模型时删除钮一律禁用。"""
        has_model = self.tree.topLevelItemCount() > 0
        self._del_sel.setEnabled(has_model and bool(self.tree.selected_ids()))
        self._del_grp.setEnabled(has_model)
