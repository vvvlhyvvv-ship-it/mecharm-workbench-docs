"""自 app/shell.py 抽出的控制器构造、工作台装配与信号连接（T12 瘦身件）。

原委：``app/shell.py`` 在 T08 接线后恰顶 300 行零余量，T12 改多页宿主还需加启动
序列 ⇒ 按派单卡步骤 2 把原 ``:69–106`` 区段（控制器构造＋中央装配＋顶栏/分栏构建＋
信号连接）整段搬到本件。函数签名、构建顺序、信号连接顺序、槽行为一律保持（T12
收单判据：抽件只搬不改语义）。T13 只可改与装配顺序相关的行，禁改函数签名（99
台账文件归属矩阵）。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QSplitter, QVBoxLayout,
                               QWidget)

from app.assemblytree import AssemblyTree
from app.checkctl import CheckController
from app.pathctl import PathController
from app.stage import SPECS

TOP_HEIGHT = 56
CENTER_MIN = 320
LEFT_WIDTH = SPECS["std"].left_px       # 舞台档字面宽（蓝图 §5：std 365 ↔ wide 460）
RIGHT_WIDTH = SPECS["std"].right_px     # std 384 ↔ wide 490；换档由 shell._on_stage_changed 重设


def build_controllers(win) -> None:
    """构造路径/校核两个控制器（与原 MainWindow.__init__ 内的顺序一致）。"""
    win.pathctl = PathController(win.panel, win.bridge, win.stepbar, win.statusbar, win)
    win.checkctl = CheckController(win.panel, win.bridge, win.stepbar, win.statusbar,
                                   win.pathctl, win.workmode, win)


def build_workbench(win) -> QWidget:
    """装配主界面页：顶栏 │ 左树/视口/右栏 │ 底栏（原 _build_* 原样搬迁）。"""
    work = QWidget()
    col = QVBoxLayout(work)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(_build_topbar(win))
    col.addWidget(_build_splitter(win), 1)
    col.addWidget(win.statusbar)
    return work


def _build_topbar(win) -> QWidget:
    bar = QWidget()
    bar.setObjectName("TopBar")
    bar.setFixedHeight(TOP_HEIGHT)
    row = QHBoxLayout(bar)
    row.setContentsMargins(12, 0, 12, 0)
    row.setSpacing(10)
    win._left_btn = _collapse_button("◀", win._toggle_left)
    title = QLabel("机械臂工作台")
    title.setObjectName("AppTitle")
    row.addWidget(win._left_btn)
    row.addWidget(title)
    row.addWidget(win.stepbar, 1)
    row.addWidget(QLabel("工作模式"))
    row.addWidget(win.workmode)
    row.addWidget(win.badge)
    row.addWidget(win.light)
    win._right_btn = _collapse_button("▶", win._toggle_right)
    row.addWidget(win._right_btn)
    return bar


def _collapse_button(text: str, slot) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("collapse", "true")
    btn.setFixedWidth(28)
    btn.clicked.connect(slot)
    return btn


def _build_left(win) -> QWidget:
    pane = QWidget()
    pane.setObjectName("LeftPane")
    box = QVBoxLayout(pane)
    box.setContentsMargins(12, 8, 12, 8)
    box.setSpacing(8)
    title = QLabel("装配树")
    title.setObjectName("PaneTitle")
    win.tree = AssemblyTree()
    box.addWidget(title)
    box.addWidget(win.tree, 1)
    return pane


def _build_splitter(win) -> QWidget:
    win.splitter = QSplitter(Qt.Orientation.Horizontal)
    left = _build_left(win)
    left.setMinimumWidth(200)
    win.panel.setMinimumWidth(280)
    win.viewpane.setMinimumWidth(CENTER_MIN)
    win.splitter.addWidget(left)
    win.splitter.addWidget(win.viewpane)
    win.splitter.addWidget(win.panel)
    win.splitter.setCollapsible(1, False)
    win.splitter.setSizes([LEFT_WIDTH, CENTER_MIN + 240, RIGHT_WIDTH])
    win._left_pane = left
    return win.splitter


def connect_signals(win) -> None:
    """外壳级信号连接（原 MainWindow._wire 原样搬迁＋T12 新增的启动序列三连）。"""
    win.stepbar.step_clicked.connect(win._on_step_clicked)
    win.workmode.committed.connect(win._on_mode_committed)
    win.workmode.switched.connect(win._on_mode_switched)
    win.bridge.received.connect(win._on_bridge_msg)
    win.viewpane.load_failed.connect(lambda r: win.statusbar.log(r.replace("\n", " ")))
    win.viewpane.view().loadFinished.connect(win._on_view_load)
    win.panel.step1.imported.connect(win._on_imported)
    win.panel.step1.failed.connect(lambda msg: win.statusbar.log(f"导入未成功：{msg}"))
    win.panel.step2.waypoints_changed.connect(win._on_waypoints_changed)
    win.panel.step2.log.connect(win.statusbar.log)
    win.panel.step2.set_mode(None)        # 初始未选定工作模式 → 步骤②锁定
    win.pathctl.changed.connect(win._refresh_unlock)   # 路径生成/作废 → 重算④⑤门禁
    win.checkctl.changed.connect(win._refresh_unlock)  # 校核结论/指纹变化 → 重算⑤门禁（T08）
    f3 = QShortcut(QKeySequence("F3"), win)
    f3.activated.connect(win._on_invalidate_results)
    win.tree.selected.connect(win._on_tree_selected)
    win.tree.focused.connect(win._on_tree_focused)
    win.panel.set_step(1)
    # T12 新增：载入→登录→主界面启动序列（里程碑收集器驱动就绪；登录经同一槽进入）
    win.splash.entered.connect(win.enter_system)
    win.boot.all_done.connect(win.splash.set_ready_state)
    win.stage_host.stage_changed.connect(win._on_stage_changed)
