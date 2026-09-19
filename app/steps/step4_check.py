"""app.steps.step4_check —— 右栏「碰撞校核」三态卡（T08 建；T16 起为**薄适配壳**保留）。

**T16 定位（99 台账 L-7／文件归属矩阵）**：干涉清单／报警模态／KPI 的呈现已由 T16 升级到
`app/sim_tab.py`（路径仿真页签③区）＋`app/alarm_modal.py`（阻断式模态）＋`core/collision_report.py`
（归并层）；本件**保留**右栏三态卡片与干涉列表（双通道冗余、语义不变，T16 卡步骤 6），`Step4Pane`
对外签名不变（`app/checkctl.py`／`app/panel.py` 照常引用），⛔ 不删件。本页 ⛔ 不算几何、⛔ 不持有
机台参数、⛔ 不自造结论措辞；判定真值由 `core.collision.check` 算出、经 `app.checkctl` 注入
（`show_result`）。用户意图经信号回灌控制器：`check_requested`／`case_clicked`／`log`。

五件可见元素（02 §2 步骤④＋G19）：
  ① [开始校核] 主按钮（16px 粗体、高≥40px、占右栏整宽，02 §4）
  ② 三态结果卡片：**颜色＋图标＋文字三通道**（02 §4／招标 16(3)③）——文字色取 `app.theme.TOKENS` 的
     ok／warn／deny，图标 🟢🟡🔴（02 §2 步骤④ 原文），文字取 `CollisionResult.describe()`
  ③ **覆盖面标注**（G19 第 2 条）：`coverage()` 整句**单独一行常显**，含未建模臂时用预警黄 ⇒ 与结论
     分行，⛔ 不会被读成「结论已覆盖全部臂」
  ④ 干涉／预警列表 [段号｜涉事部件｜最小距离 mm]：单位只在表头标注一次（02 §4）；点击行 →
     `case_clicked(行号)`，控制器据此推视口定位干涉点＋双方红色高亮
  ⑤ 表下整句人话（与视口顶部报警条**同一句**，两通道同口径）＋🟡预警「可进⑤、下发前再提示」说明行

⛔ **上屏禁出现"通过"**（G19 第 2 条：未建模臂属**判定空白**、不是判定为安全）⇒ 卡片文字一律用
`describe()` 的「已建模的 N 根连杆范围内 …」。颜色 ⛔ 禁散写色值（一律取 TOKENS，禁改 theme.py）。
⚠️ 涉事部件列的臂侧名是 `machine.yaml` 的连杆 id（配置里没有中文别名源、且该文件对本单只读）⇒ 前缀
「臂身」点明哪一侧是机械臂，已在 T08 汇报报备。
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QPalette
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel, QPushButton, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from app.theme import TOKENS
from core.collision import VERDICT_INTERFERE, VERDICT_PASS, VERDICT_WARN, CollisionResult

_TITLE = "碰撞校核"   # 右栏卡片标题（T16 起脱钩 StepBar 的 STEP_LABELS，L-7 清理）
_COLS = ("段号", "涉事部件", "最小距离 mm")
_ICON = {VERDICT_PASS: "🟢", VERDICT_WARN: "🟡", VERDICT_INTERFERE: "🔴"}   # 02 §2 步骤④ 原文
_TONE = {VERDICT_PASS: "ok", VERDICT_WARN: "warn", VERDICT_INTERFERE: "deny"}
_EMPTY_HINT = "尚未校核：先在步骤③生成路径，再点[开始校核]"
_IDLE_CARD = "尚未校核"
_DONE_HINT = "校核完成：结论见上方卡片。改动点位／换工作模式／导入新模型后，本结果自动作废须重校"
# 🟡预警允许进⑤（02 §2 步骤④），但下发弹窗内要再显示黄条警告 ⇒ 此处先把口径讲给操作员
_WARN_TELL = "🟡 预警：间距小于安全值。可以进入步骤⑤，但下发前会再次提示，由你确认"
_DENY_TELL = "已禁止下发（步骤⑤按钮置灰，且下发函数入口会再独立判一次）"
_TEXT = QColor(TOKENS["text"])
_DIM = QColor(TOKENS["text_dim"])
_WARN = QColor(TOKENS["warn"])
_DENY = QColor(TOKENS["deny"])


class Step4Pane(QWidget):
    """右栏步骤④页。信号＝用户意图；数据一律由控制器灌入（本页只投影、不计算）。"""

    check_requested = Signal()
    case_clicked = Signal(int)        # 列表行号（0-based，与 `CollisionResult.cases` 同序）
    log = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderCard")
        self._build()

    # --- 构建 --------------------------------------------------------------- #
    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(10)
        title = QLabel(_TITLE)
        title.setObjectName("PlaceholderTitle")
        self._hint = QLabel(_EMPTY_HINT)
        self._idle_hint = _EMPTY_HINT      # 提示行底文案：出过结果后升为 _DONE_HINT（clear 复位）
        self._hint.setObjectName("PlaceholderBody")
        self._hint.setWordWrap(True)
        self._btn = QPushButton("开始校核")
        self._btn.setProperty("role", "primary")
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self.check_requested)
        self._card = self._make_card()
        self._coverage = self._make_line(_DIM)
        self._table = self._make_table()
        self._table.cellClicked.connect(self.case_clicked)
        self._verdict_line = self._make_line(None)
        self._note = self._make_line(_WARN)
        self._stat = self._make_line(_DIM)
        for widget in (title, self._hint, self._btn, self._card, self._coverage):
            box.addWidget(widget)
        box.addWidget(self._table, 1)
        for widget in (self._verdict_line, self._note, self._stat):
            box.addWidget(widget)

    def _make_card(self) -> QLabel:
        """三态卡片：文字色随三态变（调色板，不动全局 QSS、不散写色值），图标＋整句结论 ⇒ 三通道齐。"""
        card = QLabel(_IDLE_CARD)
        card.setWordWrap(True)
        card.setAutoFillBackground(True)
        card.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        card.setContentsMargins(12, 10, 12, 10)
        card.setMinimumHeight(56)
        self._recolor(card, _DIM)
        return card

    def _make_table(self) -> QTableWidget:
        table = QTableWidget(0, len(_COLS))
        table.setHorizontalHeaderLabels(_COLS)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)   # 校核结果只读
        header = table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(len(_COLS) - 1, QHeaderView.ResizeMode.ResizeToContents)
        return table

    @staticmethod
    def _make_line(color: QColor | None) -> QLabel:
        """一行可换行说明文字；给色即着色行（同 Step3Pane 的手法，不动全局 QSS）。"""
        label = QLabel("")
        label.setObjectName("PlaceholderBody")
        label.setWordWrap(True)
        if color is not None:
            Step4Pane._recolor(label, color)
        return label

    @staticmethod
    def _recolor(label: QLabel, text: QColor) -> None:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.WindowText, text)
        label.setPalette(palette)

    # --- 控制器灌入 --------------------------------------------------------- #
    def set_ready(self, on: bool, hint: str = "") -> None:
        """[开始校核] 可用性（＝步骤③路径已生成且无不可达段 **且** 步骤①已导入实体模型）；
        不可用时提示行写人话原因 ⛔ 不静默禁用。可用时提示行回到底文案（出过结果＝`_DONE_HINT`，
        否则空态句）⇒ ⛔ 不留上一轮的过期原因。"""
        self._btn.setEnabled(on)
        self._hint.setText(hint or self._idle_hint)

    def show_result(self, result: CollisionResult) -> None:
        """灌入一次校核结果：卡片＋覆盖面标注＋列表＋整句人话＋实测数字（本页只投影、不计算）。"""
        self._recolor(self._card, QColor(TOKENS[_TONE.get(result.verdict, "text_dim")]))
        self._card.setText(f"{_ICON.get(result.verdict, '')} {result.describe()}")
        self._coverage.setText(result.coverage())
        self._recolor(self._coverage, _WARN if result.unmodeled_axes else _DIM)
        self._fill_table(result)
        self._verdict_line.setText(self.sentence(result))
        self._note.setText(_WARN_TELL if result.verdict == VERDICT_WARN else "")
        self._stat.setText(f"共 {result.sample_count} 个采样姿态 · 校核耗时 "
                           f"{result.elapsed_ms:.1f} ms · 已建模连杆 {result.modeled_links} 根")
        self._idle_hint = _DONE_HINT
        self._hint.setText(_DONE_HINT)

    @staticmethod
    def sentence(result: CollisionResult) -> str:
        """表下整句人话＝视口顶部报警条**同一句**（两通道同口径，避免两处说法打架）。"""
        if not result.cases:
            return ""
        worst = result.cases[0]
        if worst.min_dist_mm <= 0.0:
            head = f"⛔ 第 {worst.seg_id} 段与【{worst.part_b}】干涉"
            return f"{head}，{_DENY_TELL}"
        return (f"⚠ 第 {worst.seg_id} 段与【{worst.part_b}】间距 {worst.min_dist_mm:.1f} mm，"
                f"小于安全值，可进入步骤⑤（下发前会再提示）")

    def clear(self) -> None:
        """结果作废（改点／换模式／新模型／F3）：卡片回未校核态、列表清空、覆盖面标注一并撤下。"""
        self._recolor(self._card, _DIM)
        self._card.setText(_IDLE_CARD)
        self._coverage.setText("")
        self._table.setRowCount(0)
        self._verdict_line.setText("")
        self._note.setText("")
        self._stat.setText("")
        self._idle_hint = _EMPTY_HINT
        self._hint.setText(_EMPTY_HINT)

    # --- 表格与着色 --------------------------------------------------------- #
    def _fill_table(self, result: CollisionResult) -> None:
        """列表＝落进预警带的（段, 连杆, 障碍）记录，已按最小距离升序 ⇒ 第 1 行就是最危险那条。"""
        self._table.setRowCount(len(result.cases))
        for row, case in enumerate(result.cases):
            cells = (str(case.seg_id), f"臂身 {case.part_a} ↔ {case.part_b}",
                     f"{case.min_dist_mm:.1f}")
            color = _DENY if case.min_dist_mm <= 0.0 else _WARN
            for col, text in enumerate(cells):
                item = QTableWidgetItem(text)
                item.setBackground(QBrush(color))
                item.setToolTip(f"第 {case.seg_id} 段：臂身 {case.part_a} 与 {case.part_b} 的最小距离"
                                f" {case.min_dist_mm:.3f} mm（点击本行到视口定位干涉点）")
                self._table.setItem(row, col, item)
