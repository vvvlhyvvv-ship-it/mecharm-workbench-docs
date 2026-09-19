"""app.steps.step2_pick —— 右栏步骤②「选取点位」业务页（T06；02 §2 步骤②）。

单一职责＝**点位列表的视图与本地编辑**；点位真值（pos/normal/source_face）由 core 换算、
经 shell 从 ``pick.face`` 注入（``add_face_point``），本页只持有 ``Waypoint`` 列表做增删改与显示，
任何改动经 ``waypoints_changed`` 信号回灌 shell（shell 再推视口标号牌）——**数据源唯一在 core**，
本页不自行计算几何（02 §2 禁止事项、03 §3 单向数据流）。

四件可见元素（02 §2 步骤②）：
  ① 顶部第一行常显当前工作模式（``set_mode``，G16）；未选定→锁定提示＋禁用列表
  ② 固定取点提示「在模型上点击机械臂要到达的面」
  ③ 点位表 [序号｜名称｜X｜Y｜Z｜删除]：名称/坐标可点开手改、回车提交、非法值红框拒绝＋人话日志、
     删除不重排序号
  ④ [+命名当前点] 主按钮：把名称列拉进编辑态（默认命名 P1、P2…）

坐标「超行程」判据走 machine.yaml 的**移动副**行程上限（mm，配置驱动、禁硬编码现场参数 §5.5-①）；
读不到配置则只做「须为数字」校验并告警，不塞默认值。颜色取 02 §4 deny 红，与视口/loader 同口径。
"""

from __future__ import annotations

import logging

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import (QAbstractItemView, QHeaderView, QLabel,
                               QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core.config import REPO_ROOT, ConfigError, load_machine
from core.geometry.face_point import FacePoint, Waypoint

_COLS = ("序号", "名称", "X", "Y", "Z", "删除")
_PICK_PROMPT = "在模型上点击机械臂要到达的面"
_LOCK_PROMPT = "先在顶栏选择当前安装的多功能臂"
_DENY = QColor("#b3261e")          # 02 §4 deny 红（＝ loader SEM.deny）
_NAME_COL = 1
_FIRST_COORD_COL = 2               # X/Y/Z 占列 2/3/4

log = logging.getLogger(__name__)


class Step2Pane(QWidget):
    """右栏步骤②页。信号 waypoints_changed(list[Waypoint])、log(str) 人话日志。"""

    waypoints_changed = Signal(object)
    log = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PlaceholderCard")
        self._waypoints: list[Waypoint] = []
        self._next_id = 1
        self._loading = False              # 程序刷新表格时屏蔽 cellChanged
        self._locked = True                # 未选定工作模式即锁定
        self._pick_offset = 0.0            # 选点偏移（T14 工具区灌入；新点位 Z 向偏移）
        self._clash_names: set[str] = set()  # 涉事段端点名（T14 干涉红行，读校核结果）
        self._bound_mm = self._read_bound()
        self._build()

    # --- 构建 --------------------------------------------------------------- #
    def _build(self) -> None:
        box = QVBoxLayout(self)
        box.setContentsMargins(16, 16, 16, 16)
        box.setSpacing(10)
        self._mode_line = QLabel("当前：未选定")   # T14 重排：标题行退役（页签统一「程序 · 步骤」）
        self._mode_line.setObjectName("PlaceholderBody")
        self._prompt = QLabel(_LOCK_PROMPT)
        self._prompt.setObjectName("PlaceholderBody")
        self._prompt.setWordWrap(True)
        self._table = self._make_table()
        self._btn = QPushButton("命名当前点")
        self._btn.setProperty("role", "primary")
        self._btn.setEnabled(False)
        self._btn.clicked.connect(self._on_name_current)
        box.addWidget(self._mode_line)
        box.addWidget(self._prompt)
        box.addWidget(self._table, 1)
        box.addWidget(self._btn)

    def _make_table(self) -> QTableWidget:
        t = QTableWidget(0, len(_COLS))
        t.setHorizontalHeaderLabels(_COLS)
        t.verticalHeader().setVisible(False)
        t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        t.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked
                          | QAbstractItemView.EditTrigger.EditKeyPressed)
        hdr = t.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(len(_COLS) - 1, QHeaderView.ResizeMode.ResizeToContents)
        t.cellChanged.connect(self._on_cell_changed)
        t.setEnabled(False)
        return t

    # --- 工作模式（G16）------------------------------------------------------ #
    def set_mode(self, name: str | None) -> None:
        """顶部第一行常显当前工作模式；未选定→锁定提示＋禁用列表（02 §2 步骤②／G16）。"""
        self._locked = not name
        self._mode_line.setText(f"当前：{name}" if name else "当前：未选定")
        self._prompt.setText(_PICK_PROMPT if name else _LOCK_PROMPT)
        self._table.setEnabled(not self._locked)
        self._btn.setEnabled(not self._locked)

    # --- 点位增删改 ---------------------------------------------------------- #
    def add_face_point(self, fp: FacePoint) -> None:
        """注入一个 core 换算好的面点；同一 B-Rep 面（source_face）去重，不产生重复点位。

        选点偏移（T14 工具区）在此并入：新点位 Z 向偏移 ``_pick_offset`` mm。
        """
        if self._locked:
            self.log.emit("未选定工作模式，步骤②锁定，无法取点")
            return
        dup = next((w for w in self._waypoints if w.source_face == fp.source_face), None)
        if dup is not None:
            self.log.emit(f"该面已有点位 {dup.name}（序号 {dup.id}），未重复添加")
            return
        wid = self._next_id
        self._next_id += 1
        pos = (fp.pos_mm[0], fp.pos_mm[1], fp.pos_mm[2] + self._pick_offset)
        self._waypoints.append(Waypoint(id=wid, name=f"P{wid}", pos_mm=pos,
                                        normal=fp.normal, source_face=fp.source_face))
        offset_note = f"（含选点偏移 {self._pick_offset:g} mm）" if self._pick_offset else ""
        self.log.emit(f"已添加点位 P{wid}（面 {fp.source_face}）{offset_note}")
        self._refresh()

    def set_pick_offset(self, mm: float) -> None:
        """选点偏移量（mm，仅影响**此后**新取的点位；已有点位不动——可追溯）。"""
        self._pick_offset = float(mm)

    def set_clash_names(self, names: set[str]) -> None:
        """涉事段端点点位红行（T14：读校核结果灌入；空集即清）。"""
        self._clash_names = set(names)
        self._refresh_silent()

    def set_waypoints(self, points: list[Waypoint]) -> None:
        """整体替换点位列表（导入恢复用）：不去重、不走锁定门禁，改动照发 ``waypoints_changed``。"""
        self._waypoints = list(points)
        top = max((w.id for w in points), default=0)
        self._next_id = top + 1
        self._refresh()

    def delete(self, wid: int) -> None:
        """删除点位；序号不重排（id 稳定，02 §2）。"""
        self._waypoints = [w for w in self._waypoints if w.id != wid]
        self.log.emit(f"已删除点位（序号 {wid}），序号不重排")
        self._refresh()

    def clear(self) -> None:
        """真清空点位列表（F3／换臂结果作废）；序号计数器一并归零。"""
        self._waypoints = []
        self._next_id = 1
        self._refresh()

    def waypoints(self) -> list[Waypoint]:
        return list(self._waypoints)

    def _on_name_current(self) -> None:
        """[+命名当前点]：把当前行（无选中则末行）的名称列拉进编辑态。"""
        if not self._waypoints:
            self.log.emit("尚无点位：请先在模型上左键点击机械臂要到达的面")
            return
        row = self._table.currentRow()
        if row < 0 or row >= len(self._waypoints):
            row = len(self._waypoints) - 1
        self._table.setCurrentCell(row, _NAME_COL)
        self._table.editItem(self._table.item(row, _NAME_COL))

    # --- 表格刷新与编辑校验 -------------------------------------------------- #
    def _refresh(self) -> None:
        self._loading = True
        self._table.setRowCount(len(self._waypoints))
        for row, w in enumerate(self._waypoints):
            self._fill_row(row, w)
        self._loading = False
        self.waypoints_changed.emit(self.waypoints())

    def _refresh_silent(self) -> None:
        """只重画表格（干涉红行等着色用），⛔ 不发 ``waypoints_changed``——着色不是数据改动，
        发了会把已生成路径误作废。"""
        self._loading = True
        self._table.setRowCount(len(self._waypoints))
        for row, w in enumerate(self._waypoints):
            self._fill_row(row, w)
        self._loading = False

    def _fill_row(self, row: int, w: Waypoint) -> None:
        no = QTableWidgetItem(str(w.id))
        no.setFlags(no.flags() & ~Qt.ItemFlag.ItemIsEditable)   # 序号只读、不重排
        no.setData(Qt.ItemDataRole.UserRole, w.id)
        self._table.setItem(row, 0, no)
        name = QTableWidgetItem(w.name)
        if w.name in self._clash_names:                          # 涉事段端点 ⇒ 红行（三通道的红底）
            name.setBackground(QBrush(_DENY))
            name.setToolTip("涉事段端点：见校核结论与「路径仿真」页签")
        self._table.setItem(row, _NAME_COL, name)
        for k in range(len(w.pos_mm)):
            self._table.setItem(row, _FIRST_COORD_COL + k,
                                QTableWidgetItem(f"{w.pos_mm[k]:.3f}"))
        btn = QPushButton("删除")
        btn.clicked.connect(lambda _=False, wid=w.id: self.delete(wid))
        self._table.setCellWidget(row, len(_COLS) - 1, btn)

    def _on_cell_changed(self, row: int, col: int) -> None:
        if self._loading or row >= len(self._waypoints):
            return
        item = self._table.item(row, col)
        if item is None:
            return
        if col == _NAME_COL:
            self._commit_name(row, item)
        elif col in (_FIRST_COORD_COL, _FIRST_COORD_COL + 1, _FIRST_COORD_COL + 2):
            self._commit_coord(row, col, item)

    def _commit_name(self, row: int, item: QTableWidgetItem) -> None:
        w = self._waypoints[row]
        text = item.text().strip()
        if not text:
            self._reject(item, w.name, "名称不能为空")
            return
        item.setBackground(QBrush())          # 合法→清除红框
        if text != w.name:
            w.name = text
            self.log.emit(f"点位（序号 {w.id}）名称改为 {text}")
            self.waypoints_changed.emit(self.waypoints())

    def _commit_coord(self, row: int, col: int, item: QTableWidgetItem) -> None:
        w = self._waypoints[row]
        k = col - _FIRST_COORD_COL
        old = f"{w.pos_mm[k]:.3f}"
        try:
            val = float(item.text().strip())
        except ValueError:
            self._reject(item, old, f"坐标须为数字（mm），收到「{item.text().strip()}」")
            return
        if self._bound_mm is not None and abs(val) > self._bound_mm:
            self._reject(item, old,
                         f"坐标 {val:g} mm 超行程（限位 ±{self._bound_mm:g} mm）")
            return
        item.setBackground(QBrush())
        pos = list(w.pos_mm)
        if abs(val - pos[k]) > 1e-9:
            pos[k] = val
            w.pos_mm = (pos[0], pos[1], pos[2])
            self.log.emit(f"点位（序号 {w.id}）坐标改为 ({w.pos_mm[0]:g}, "
                          f"{w.pos_mm[1]:g}, {w.pos_mm[2]:g}) mm")
            self.waypoints_changed.emit(self.waypoints())

    def _reject(self, item: QTableWidgetItem, old: str, why: str) -> None:
        """非法值：红框（红底）拒绝、回填旧值、人话日志（不触发二次 cellChanged）。"""
        self._loading = True
        item.setText(old)
        item.setBackground(QBrush(_DENY))
        self._loading = False
        self.log.emit(f"输入被拒绝：{why}")

    # --- 行程限位（配置驱动）------------------------------------------------- #
    @staticmethod
    def _read_bound() -> float | None:
        """坐标「超行程」上限＝machine.yaml 移动副行程的最大绝对值（mm）；读不到→None（只校验数字）。"""
        try:
            cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
        except (ConfigError, OSError) as exc:
            log.warning("读取行程限位失败，坐标只校验数字：%s", exc)
            return None
        spans: list[float] = []
        for ax in cfg.axes.values():
            if ax.type != "prismatic":
                continue
            lo, hi = ax.travel
            spans.append(max(abs(lo), abs(hi)))
        return max(spans) if spans else None
