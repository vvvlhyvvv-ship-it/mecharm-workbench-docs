"""app.steps.step3_path —— 右栏步骤③「生成路径」业务页（T07；02 §2 步骤③）。

单一职责＝**段清单的视图与播放控制按钮**；段真值（长度／时长／关节目标／是否可达）由
`core.path.gen_path` 算出、经 `app.pathctl` 注入（`show_segments`），本页不自行计算几何、
不持有机台参数（02 §2 禁止事项、03 §3 单向数据流）。用户意图经信号回灌控制器：
`generate_requested`／`play_requested`／`pause_requested`／`option_changed`／`log`。

五件可见元素（02 §2 步骤③＋T07 卡步骤 1／完成标准③）：
  ① 段型下拉「点位型（空程）／轮廓型（作业）」——卡片步骤 1 要求界面可切；⚠️ 02 §2 步骤③ 的
     布局清单里**没有**此控件（登记为文档回填项，本件不擅改 02）
  ② `blending` 复选框，**默认不勾**（＝逐段到达；电Q-8 回执后才切），勾选即人话告警
  ③ [生成路径] 主按钮（16px 粗体、高≥40px、占右栏整宽，02 §4）
  ④ 段清单表 [段号｜起点→终点｜类型｜长度 mm]：单位只在表头标注一次、不逐行重复（02 §4）；
     不可达段红底＋⛔＋原因（颜色／图标／文字三通道），整句原因另在表下红字行显示
  ⑤ 汇总行「共 N 段 · 总长 X m · 预估节拍 Y s」＋[▶播放][⏸暂停]

⛔ **禁止上屏**：关节角／矩阵／插补（02 §2 步骤③）——故表里没有关节列，`Segment.joints_*`
只交给控制器驱动动画。颜色取 `app.theme.TOKENS`（配色唯一真值处，禁散写色值、禁改 theme.py）。
"""

from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from app.stepbar import STEP_LABELS
from app.theme import TOKENS
from core.path import KIND_CONTOUR, KIND_POINT, PathSummary, Segment

_COLS = ("段号", "起点→终点", "类型", "长度 mm")
_KIND_ITEMS = ((KIND_POINT, "点位型（空程快速）"), (KIND_CONTOUR, "轮廓型（作业速度）"))
_TYPE_NAMES = {"JOINT": "点位", "LINE": "直线"}
_EMPTY_HINT = "尚未生成路径：先在步骤②取点，再点[生成路径]"
_BLEND_NOTE = "电Q-8（下发轨迹段格式）未回执，默认逐段到达；开启只改段携带的标志位"
_DENY = QColor(TOKENS["deny"])        # 02 §4 报警红＝视口 loader 的 SEM.deny，同一口径
_ACCENT = QColor(TOKENS["accent"])    # 当前段高亮＝当前步高亮蓝


class Step3Pane(QWidget):
    """右栏步骤③页。信号＝用户意图；数据一律由控制器灌入（本页只投影、不计算）。"""

    generate_requested = Signal()
    play_requested = Signal()
    pause_requested = Signal()
    option_changed = Signal(str)      # 段型／blending 改了 ⇒ 已生成路径作废（带人话原因）
    log = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderCard")
        self._segments: list[Segment] = []
        self._summary: PathSummary | None = None
        self._current = 0             # 播放中的当前段号（1-based；0＝未播放）
        self._playing = False
        self._build()

    # --- 构建 --------------------------------------------------------------- #
    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(10)
        title = QLabel(STEP_LABELS[2])
        title.setObjectName("PlaceholderTitle")
        self._kind = QComboBox()
        for value, text in _KIND_ITEMS:
            self._kind.addItem(text, value)
        self._kind.currentIndexChanged.connect(self._on_option_changed)
        self._blend = QCheckBox("连续过渡（blending，默认关）")
        self._blend.setChecked(False)          # 完成标准③：默认 False
        self._blend.setToolTip(_BLEND_NOTE)
        self._blend.toggled.connect(self._on_blend_toggled)
        self._hint = QLabel(_EMPTY_HINT)
        self._hint.setObjectName("PlaceholderBody")
        self._hint.setWordWrap(True)
        self._btn = QPushButton("生成路径")
        self._btn.setProperty("role", "primary")
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self.generate_requested)
        self._table = self._make_table()
        self._block_line = self._make_line(_DENY)
        self._summary_line = self._make_line(None)
        self._summary_line.setText(_EMPTY_HINT)
        kind_row = QHBoxLayout()
        kind_row.setSpacing(8)
        kind_row.addWidget(QLabel("段型"))
        kind_row.addWidget(self._kind, 1)
        play_row = QHBoxLayout()
        play_row.setSpacing(8)
        self._play = QPushButton("▶ 播放")
        self._pause = QPushButton("⏸ 暂停")
        for widget, slot in ((self._play, self.play_requested), (self._pause, self.pause_requested)):
            widget.setEnabled(False)
            widget.clicked.connect(slot)
            play_row.addWidget(widget, 1)
        box.addWidget(title)
        box.addLayout(kind_row)
        box.addWidget(self._blend)
        box.addWidget(self._hint)
        box.addWidget(self._btn)
        box.addWidget(self._table, 1)
        box.addWidget(self._block_line)
        box.addWidget(self._summary_line)
        box.addLayout(play_row)

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLS))
        table.setHorizontalHeaderLabels(_COLS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)   # 段清单只读
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(_COLS) - 1, QHeaderView.ResizeMode.ResizeToContents)
        return table

    @staticmethod
    def _make_line(color: QColor | None) -> QLabel:
        """一行可换行说明文字；给色即红字行（不动全局 QSS，只改本控件调色板）。"""
        label = QLabel("")
        label.setObjectName("PlaceholderBody")
        label.setWordWrap(True)
        if color is not None:
            palette = QPalette()
            palette.setColor(QPalette.ColorRole.WindowText, color)
            label.setPalette(palette)
        return label

    # --- 控制器灌入 --------------------------------------------------------- #
    def set_point_count(self, count: int) -> None:
        """按已有点位数决定 [生成路径] 可用性；不足两点给人话提示（⛔ 不静默禁用）。"""
        self._btn.setEnabled(count >= 2 and not self._playing)
        if count < 2 and self._summary is None:
            self._hint.setText(f"至少需要 2 个点位才能生成路径（当前 {count} 个）")

    def show_segments(self, segments: list[Segment], summary: PathSummary) -> None:
        """灌入段清单与汇总（本页只投影）；有阻断段 ⇒ 播放禁用、红字行给出整句原因。"""
        self._segments = list(segments)
        self._summary = summary
        self._current = 0
        self._fill_table()
        self._summary_line.setText(summary.describe())
        self._block_line.setText(self._block_text())
        self._hint.setText(f"段型：{self._kind.currentText()}")
        self._play.setEnabled(summary.ok and not self._playing)
        self._pause.setEnabled(False)
        self._btn.setEnabled(not self._playing)

    def clear(self) -> None:
        """结果作废（改点／切模式／F3／改段型）：清空段清单与汇总，播放按钮一并禁用。"""
        self._segments, self._summary, self._current, self._playing = [], None, 0, False
        self._table.setRowCount(0)
        self._block_line.setText("")
        self._summary_line.setText(_EMPTY_HINT)
        self._hint.setText(_EMPTY_HINT)
        self._play.setEnabled(False)
        self._pause.setEnabled(False)

    def set_playing(self, on: bool) -> None:
        """播放态：播放中禁用[▶播放]／[生成路径]／段型与 blending（防播放中改结果），启用[⏸]。"""
        self._playing = on
        self._play.setEnabled(not on and self._summary is not None and self._summary.ok)
        self._pause.setEnabled(on)
        self._btn.setEnabled(not on)
        self._kind.setEnabled(not on)
        self._blend.setEnabled(not on)
        if not on:
            self._current = 0
            self._paint()

    def set_current(self, seg_id: int) -> None:
        """播放进度：高亮当前段（0＝不高亮）。段号与 `Segment.id`／T08 的 seg_id 同源。"""
        if seg_id != self._current:
            self._current = seg_id
            self._paint()

    def kind(self) -> str:
        """当前段型（`core.path.KIND_POINT`｜`KIND_CONTOUR`）。"""
        return self._kind.currentData()

    def blending(self) -> bool:
        """连续过渡开关（电Q-8 回执前默认 False）。"""
        return self._blend.isChecked()

    def summary(self) -> PathSummary | None:
        """当前段序列的汇总；None＝尚未生成或已作废（步骤④⑤的门禁读它）。"""
        return self._summary

    # --- 表格与着色 --------------------------------------------------------- #
    def _fill_table(self) -> None:
        self._table.setRowCount(len(self._segments))
        for row, seg in enumerate(self._segments):
            cells = (str(seg.id), f"{seg.start_name}→{seg.end_name}",
                     _TYPE_NAMES.get(seg.type, seg.type), f"{seg.length_mm:.1f}")
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                if seg.blocked:
                    item.setToolTip(f"⛔ 第 {seg.id} 段不可达：{seg.reason}")
                self._table.setItem(row, col, item)
        self._paint()

    def _paint(self) -> None:
        """三通道着色：不可达段红底＋⛔前缀（图标）、当前段蓝底；红压过蓝（禁发优先于进度）。"""
        for row, seg in enumerate(self._segments):
            color = _DENY if seg.blocked else (_ACCENT if seg.id == self._current else None)
            for col in range(len(_COLS)):
                item = self._table.item(row, col)
                if item is not None:
                    item.setBackground(QBrush(color) if color else QBrush())
            first = self._table.item(row, 0)
            if first is not None:
                first.setText(f"⛔ {seg.id}" if seg.blocked else str(seg.id))

    def _block_text(self) -> str:
        """表下红字行：第一条不可达原因整句＋其余段数（表里只放⛔，原因要能读全）。"""
        blocked = [seg for seg in self._segments if seg.blocked]
        if not blocked:
            return ""
        more = f"（另有 {len(blocked) - 1} 段同样不可达）" if len(blocked) > 1 else ""
        return f"⛔ 第 {blocked[0].id} 段不可达：{blocked[0].reason}{more}——已禁止进入步骤④"

    # --- 用户操作 ----------------------------------------------------------- #
    def _on_option_changed(self) -> None:
        """改段型 ⇒ 已生成路径作废（段类型与速度都随段型变，留旧表＝给用户假数据）。"""
        if self._summary is None:
            return
        self.option_changed.emit(f"段型改为「{self._kind.currentText()}」")
        self.clear()

    def _on_blend_toggled(self, on: bool) -> None:
        """勾选 blending 只改段携带的标志位；电Q-8 未回执 ⇒ 当场人话告警，不静默生效。"""
        if self._summary is not None:
            self.option_changed.emit("连续过渡（blending）开关")
            self.clear()
        self.log.emit(f"已开启连续过渡：{_BLEND_NOTE}" if on else "已恢复逐段到达（blending 关闭）")
