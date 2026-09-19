"""app.plc_preview —— PLC 输出预览模态（T17；01 蓝图 §3.8，演示稿画面 09）。

主窗覆盖层（手法同 ``app/pop_import.ImportPopup``）：顶部红色用途声明条**两行**（``ui.yaml``
第 1、2 串逐字，蓝图 §6.3）＋头（「PLC 工步数据表」＋程序名/生成时刻＋✕）＋KPI 六格（弦高
容差/掉头保护恒「待定」——未定口径如实呈现）＋**工步表 10 列**（工步/段号/动作/X/Y/Z/速度/
ProcessStep/OPC UA 变量/备注；干涉段行红字＝三通道之色；备注列速度处恒「估算值」，铁律 2）
＋页脚（第 3 串逐字＋复制当前表／导出 CSV／关闭）。数据**只灌** ``PlcOutArea`` 生成的同一份
结果（⛔ 不另算一遍）；导出/复制按钮转调输出区同源动作。圆角 8px＝§4-C 模态档，QSS 以
string.Template 从 TOKENS 渲染局部样式表（红条色由 deny 令牌现场派生 rgba）。

⚠️ 本件是 T17 的**预案外增件**（派单卡增件清单只预声明了 ``app/plc_out.py``）：输出区＋模态
合并为一件实测 413 行，去重复与抽函数已尽、再压只能删 docstring（反作弊条款禁）⇒ 按
04 §4.5-②③ 的处理顺序拆件，先例＝T07 ``pathctl.py``／T08 ``checkctl.py``（均为 300 行帽
逼出的拆件、收单追认）；反扩边界＝只覆盖本件，不构成「app/ 可自由拆件」先例。
"""

from __future__ import annotations

from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QKeySequence, QShortcut
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.plc_out import LATER_NOTE, _dim, _repaint
from app.theme import TOKENS
from core.process import STEPS_HEAD, ProcessStep, VarRow, budget

MODAL_NOTE_FMT = "工步数据 {n} 行 · 变量映射 {m} 条（导出 CSV 为全量，UTF-8 BOM，Excel 直接打开）"
_KPI_KEYS = ("工步数", "变量条数", "ProcessStep 预算", "编排方式", "弦高容差", "掉头保护")

_QSS = Template("""
    #PlcMask { background-color: rgba(6, 9, 12, 170); }
    #PlcCard { background-color: $bg_card; border: 1px solid $border2; border-radius: ${r_modal}px; }
    #PlcScope { background-color: $scope_bg; border-bottom: 1px solid $scope_line; }
    #PlcScope QLabel { color: $deny; }
    #PlcTitle { font-weight: 600; }
    #PlcFoot { background-color: $bg_panel; border-top: 1px solid $border; }
""")


def _rgba(hex_color: str, alpha: int) -> str:
    """``#rrggbb`` → Qt 样式表 rgba() 串（红条色由 deny 令牌派生，不散写色值字面量）。"""
    value = int(hex_color.lstrip("#"), 16)
    return f"rgba({value >> 16}, {(value >> 8) & 0xFF}, {value & 0xFF}, {alpha})"


class PlcPreview(QWidget):
    """PLC 输出预览模态（演示稿画面 09；遮罩点击／✕／Esc／关闭均可关，全程同一实例）。"""

    def __init__(self, win, area, parent: QWidget | None = None) -> None:
        super().__init__(win if parent is None else parent)
        self.setObjectName("PlcMask")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)   # QWidget 画 QSS 背景开关
        self._win, self._area = win, area
        self.setVisible(False)
        self.setStyleSheet(_QSS.substitute({
            **TOKENS, "scope_bg": _rgba(TOKENS["deny"], 30), "scope_line": _rgba(TOKENS["deny"], 130)}))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.hide)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        card = QFrame()
        card.setObjectName("PlcCard")
        card.setFixedWidth(min(980, max(640, win.width() - 48)))
        card.setLayout(self._build_body())
        center.addWidget(card)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(1)

    def _build_body(self) -> QVBoxLayout:
        """红条两行（第 1/2 串）＋头（标题＋程序/生成时刻＋✕）＋KPI 六格＋工步表＋页脚三钮。"""
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(0)
        box.addWidget(self._build_scope())
        box.addLayout(self._build_head())
        body = QVBoxLayout()
        body.setContentsMargins(14, 10, 14, 10)
        body.setSpacing(8)
        body.addLayout(self._build_kpis())
        body.addWidget(self._build_table(), 1)
        self._modal_note = _dim("")
        self._modal_note.setWordWrap(True)
        body.addWidget(self._modal_note)
        box.addLayout(body, 1)
        box.addWidget(self._build_foot())
        return box

    def _build_scope(self) -> QFrame:
        """顶部红色用途声明条两行（＝``ui.yaml`` 第 1、2 串，蓝图 §6.3 逐字）。"""
        scope = QFrame()
        scope.setObjectName("PlcScope")
        srow = QVBoxLayout(scope)
        srow.setContentsMargins(14, 8, 14, 8)
        srow.setSpacing(2)
        self._decl = []
        for key in ("plc_declare_top", "plc_declare_table"):
            line = QLabel(getattr(self._win.ui, key))
            line.setWordWrap(True)
            self._decl.append(line)
            srow.addWidget(line)
        return scope

    def _build_head(self) -> QHBoxLayout:
        """标题行：PLC 工步数据表＋程序名/生成时刻＋✕。"""
        head = QHBoxLayout()
        head.setContentsMargins(14, 8, 14, 8)
        head.setSpacing(8)
        title = QLabel("PLC 工步数据表")
        title.setObjectName("PlcTitle")
        self._meta = _dim("")
        close = QPushButton("✕")
        close.setFixedWidth(26)
        close.clicked.connect(self.hide)
        head.addWidget(title)
        head.addWidget(self._meta, 1)
        head.addWidget(close)
        return head

    def _build_kpis(self) -> QHBoxLayout:
        """KPI 六格（值由 show_preview 灌真值；弦高容差/掉头保护恒「待定」）。"""
        self._kpi: dict[str, QLabel] = {}
        kpis = QHBoxLayout()
        for key in _KPI_KEYS:
            value = QLabel("—")
            value.setProperty("mono", "true")
            self._kpi[key] = value
            col = QVBoxLayout()
            col.addWidget(_dim(key))
            col.addWidget(value)
            col.setContentsMargins(0, 0, 0, 0)
            host = QWidget()
            host.setLayout(col)
            kpis.addWidget(host, 1)
        return kpis

    def _build_table(self) -> QTableWidget:
        """工步表 10 列（表头＝core.process.STEPS_HEAD；内容自适应＋备注列吃余量）。"""
        self._table = QTableWidget(0, len(STEPS_HEAD))
        self._table.setHorizontalHeaderLabels(STEPS_HEAD)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        header = self._table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(STEPS_HEAD) - 1, QHeaderView.ResizeMode.Stretch)
        self._table.setMinimumHeight(260)
        return self._table

    def _build_foot(self) -> QFrame:
        """页脚：第 3 串逐字＋复制当前表/导出 CSV（转调输出区同源动作）/关闭。"""
        foot = QFrame()
        foot.setObjectName("PlcFoot")
        frow = QHBoxLayout(foot)
        frow.setContentsMargins(14, 8, 14, 8)
        frow.setSpacing(8)
        self._foot_note = _dim(getattr(self._win.ui, "plc_declare_footer"))
        self._foot_note.setWordWrap(True)
        again = QPushButton("复制当前表")
        again.clicked.connect(self._area._on_copy)
        export = QPushButton("导出 CSV")
        export.setProperty("role", "primary")
        export.clicked.connect(self._area._on_export)
        shut = QPushButton("关闭")
        shut.clicked.connect(self.hide)
        frow.addWidget(self._foot_note, 1)
        for btn in (again, export, shut):
            frow.addWidget(btn)
        return foot

    def show_preview(self, data: dict) -> None:
        """灌同一份生成结果（⛔ 不另算一遍）并显示；干涉段行红字（三通道之色）。"""
        steps: list[ProcessStep] = data["steps"]
        rows: list[VarRow] = data["vars"]
        result = self._win.checkctl._result
        bad = {case.seg_id for case in result.cases} if result else set()
        used, limit = budget(steps, limit=data["limit"])
        kpi = {"工步数": str(len(steps)), "变量条数": str(len(rows)),
               "ProcessStep 预算": f"{used} / {limit}", "编排方式": data["mode"],
               "弦高容差": LATER_NOTE, "掉头保护": LATER_NOTE}
        for key, text in kpi.items():
            self._kpi[key].setText(text)
        self._meta.setText(f"程序：{data['name']} · 生成 {data['ts']}")
        self._modal_note.setText(MODAL_NOTE_FMT.format(n=len(steps), m=len(rows)))
        self._table.setRowCount(0)
        red = QColor(TOKENS["deny"])
        for step in steps:
            row = self._table.rowCount()
            self._table.insertRow(row)
            x, y, z = step.pos_mm
            cells = (str(step.no), str(step.seg_no), step.action, f"{x:.1f}", f"{y:.1f}",
                     f"{z:.1f}", f"{step.speed_mm_s:g}", str(step.process_step),
                     step.variable, step.note)
            for col, value in enumerate(cells):
                item = QTableWidgetItem(value)
                if step.seg_no in bad:
                    item.setForeground(red)
                self._table.setItem(row, col, item)
        self.setGeometry(self._win.rect())
        self.raise_()
        self.setVisible(True)
        _repaint(self._table)
