"""app.alarm_modal —— 阻断式干涉报警模态（T16；01 蓝图 §3.8、演示稿画面 10、卡面步骤 2）。

**何时弹**：校核完成且**存在干涉步**（verdict＝干涉）时由 `app.checkctl` 触发；无干涉（通过／预警）
**不弹**。**只呈现、不裁决**：禁发由既有双阻断机制管（按钮置灰＋下发入口独立复判，T08 冻结语义），
关闭本窗**不改变禁发状态**——红线（G13）：本件不算几何、不自造结论，全部读 `CollisionResult`。

形态（演示稿 `__MODAL_ALARM__`）：红头「检测到干涉」＋涉事摘要条＋**干涉对列表**（零件对＋最小时距
＋步号，行点击→``collision.focus`` 视口定位＋双方高亮）＋KPI（可行/干涉/共 · 结论）＋页脚依据句。
「阻断式」＝``ApplicationModal``（弹着时主窗输入全被拦，须先处置）但走 ``show()`` **不 ``exec()``**
——校核流程与 e2e 事件流不被卡死（离屏可自动关闭，先例＝``_ask_operator`` 可替身的拆法）。

颜色一律取 ``app.theme.TOKENS``（⛔ 不散写色值；rich text 里的色值同源）。字面口径：措辞照演示稿，
「估算」恒在（§1-2）、禁内部编号上屏（§1-5）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QAbstractItemView, QDialog, QFrame, QHBoxLayout, QHeaderView,
                               QLabel, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout)

from app.theme import TOKENS
from core.collision import VERDICT_INTERFERE, CollisionResult
from core.collision_report import ClashReport, group_by_device

_COLS = ("涉事零件对", "最小时距 mm", "步号")
_TITLE = "检测到干涉 —— 本次轨迹校验不通过"
_BASIS = "依据招标第 16 条(3)③：碰撞检测结果须以高亮＋报警方式提示，碰撞路径禁止下发执行。"
_WALK = "需先调整轨迹（示教点或路径），重新校验通过后才能下发。"


def popup(parent, bridge, result: CollisionResult, report: ClashReport | None = None) -> "AlarmModal":
    """装配并弹出模态（``checkctl._publish`` 干涉态调用；``show()`` 非阻塞，返回实例供复用/测试）。"""
    modal = AlarmModal(parent, bridge, result,
                       report if report is not None else group_by_device(result, ()))
    modal.show()
    modal.raise_()
    return modal


class AlarmModal(QDialog):
    """阻断式报警模态。数据一律构造时注入（只投影）；行点击 → 视口定位（复用现桥通道）。"""

    def __init__(self, parent, bridge, result: CollisionResult, report: ClashReport) -> None:
        super().__init__(parent)
        self.setWindowTitle("碰撞校验不通过")
        self.setWindowModality(Qt.WindowModality.ApplicationModal)   # 阻断＝主窗输入被拦（不 exec）
        self.setMinimumSize(560, 380)
        self.setStyleSheet(f"QDialog{{background:{TOKENS['bg_panel']};"
                           f"border-radius:{TOKENS['r_modal']}px;}}")
        self._bridge, self._result, self._report = bridge, result, report
        bad = sum(1 for case in result.cases if case.min_dist_mm <= 0.0)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(10)
        head = QLabel(f'<b style="color:{TOKENS["text"]}">● {_TITLE}</b>')   # 令牌色（收单修复：原散写 #ffd9d9）
        head.setStyleSheet(f"background:{TOKENS['deny']};padding:10px 14px;"
                           f"border-radius:{TOKENS['r_modal']}px {TOKENS['r_modal']}px 0 0;")
        box.addWidget(head)
        body = QVBoxLayout()
        body.setContentsMargins(14, 4, 14, 4)
        body.setSpacing(8)
        devices = len(report.by_device)
        tail = f"另有 {len(report.skipped)} 个零件未能归并到设备组" if report.skipped else ""
        summary = QLabel(f"<b>{len(result.cases)} 处记录涉事</b>（干涉 {bad} 处），涉及 {devices} 处设备"
                         f"{tail}。{_WALK}")
        summary.setWordWrap(True)
        summary.setStyleSheet(f"color:{TOKENS['text']};background:{TOKENS['bg_card']};"
                              f"border-left:3px solid {TOKENS['deny']};padding:8px;")
        body.addWidget(summary)
        body.addWidget(self._make_table())
        body.addLayout(self._make_kpis())
        note = QLabel(_BASIS)
        note.setWordWrap(True)
        note.setProperty("tone", "dim")
        body.addWidget(note)
        box.addLayout(body, 1)
        box.addWidget(self._make_foot())
        if result.cases:
            self._locate(0)                      # 默认定位最危险一条（视口高亮随开随有）

    # --- 构建 --------------------------------------------------------------- #
    def _make_table(self) -> QTableWidget:
        """干涉对列表：零件对（臂身＋设备）× 最小时距 × 步号；行点击 → ``collision.focus``。"""
        table = QTableWidget(len(self._result.cases), len(_COLS))
        table.setHorizontalHeaderLabels(_COLS)
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.cellClicked.connect(self._locate)
        deny = QColor(TOKENS["deny"])
        for row, case in enumerate(self._result.cases):
            pair = f"臂身 {case.part_a} ↔ {case.part_b}"
            gap = "已相碰" if case.min_dist_mm <= 0.0 else f"{case.min_dist_mm:.1f}"
            for col, text in enumerate((pair, gap, str(case.seg_id))):
                item = QTableWidgetItem(text)
                if case.min_dist_mm <= 0.0:
                    item.setBackground(deny)
                table.setItem(row, col, item)
        return table

    def _make_kpis(self) -> QHBoxLayout:
        """KPI 行（卡面口径：可行 N／干涉 N／共 N＋结论，干涉数与结论 deny 色）。"""
        total, cases = self._result.sample_count, len(self._result.cases)
        cells = (("可行", str(total - cases), "text_dim"), ("干涉", str(cases), "deny"),
                 ("共涉事记录", str(total), "text_dim"), ("结论", "不通过", "deny"))
        row = QHBoxLayout()
        for label, value, tone in cells:
            color = TOKENS[tone]
            cell = QLabel(f"{label}<br><b style=\"color:{color};font-size:15px\">{value}</b>")
            cell.setStyleSheet(f"background:{TOKENS['bg_card']};padding:6px 10px;")
            cell.setMinimumWidth(90)
            row.addWidget(cell, 1)
        return row

    def _make_foot(self) -> QFrame:
        foot = QFrame()
        row = QHBoxLayout(foot)
        row.setContentsMargins(14, 8, 14, 10)
        detail = QPushButton("查看干涉明细")
        detail.setProperty("role", "primary")
        detail.clicked.connect(lambda: (self._locate(0), self.accept()))
        close = QPushButton("知道了（关闭）")
        close.clicked.connect(self.reject)
        row.addWidget(detail)
        row.addWidget(close)
        row.addStretch(1)
        return foot

    # --- 视口定位 ------------------------------------------------------------ #
    def _locate(self, row: int, _col: int = 0) -> None:
        """行点击／默认态 → 视口定位该条（放大标记＋障碍侧高亮＋相机飞到＝现 ``collision.focus``）。"""
        if self._bridge is not None and 0 <= row < len(self._result.cases):
            self._bridge.call_view("collision.focus", {"index": int(row)})
