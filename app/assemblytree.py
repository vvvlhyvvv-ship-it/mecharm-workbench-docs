"""app.assemblytree —— 左栏装配树（T05；02 §2 步骤①「左栏装配树两级折叠」）。

数据来自 core.geometry 的 ``Assembly.tree_payload()``（嵌套 dict：id/name/is_assembly/children）。
交互（T05 步骤5）：单击零件/装配 → 发 selected(leaf_ids)（shell 转 hl.set 高亮）；
双击 → 发 focused(leaf_ids)（shell 转 hl.set+focus 相机飞到）。点装配节点时高亮其全部
叶子零件（mesh 按叶子 node_id 建，装配节点本身无网格）。

本控件**只做树展示与选择信号**，不碰桥、不做几何判定（那是 core 与 shell 的职责）。
颜色/字号走 app.theme 全局 QSS（QTreeWidget 选择器），本模块不写内联样式。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

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
        self.itemClicked.connect(self._on_click)
        self.itemDoubleClicked.connect(self._on_dblclick)

    def populate(self, nodes: list[dict]) -> None:
        """用 tree_payload 的嵌套 dict 重建树（先清空）；建完展开顶层两级。"""
        self.clear()
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
        ids = self._leaf_ids(item)
        if ids:
            self.selected.emit(ids)

    def _on_dblclick(self, item: QTreeWidgetItem, _col: int) -> None:
        ids = self._leaf_ids(item)
        if ids:
            self.focused.emit(ids)

    def _leaf_ids(self, item: QTreeWidgetItem) -> list[int]:
        """叶子零件 → 自身 id；装配节点 → 其全部 descendant 叶子 id（递归收集）。"""
        if not item.data(0, _ROLE_ASSY):
            return [int(item.data(0, _ROLE_ID))]
        ids: list[int] = []
        for i in range(item.childCount()):
            ids.extend(self._leaf_ids(item.child(i)))
        return ids
