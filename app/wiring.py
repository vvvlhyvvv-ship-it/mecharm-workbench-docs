"""自 app/shell.py 抽出的控制器构造、工作台装配与信号连接（T12 瘦身件；**T13 主战场**）。

T12 只搬不改；T13 在本件完成范式切换的装配重排（99 台账文件归属矩阵）：顶栏＝app/topbar.py 七区
（折叠钮经 QLayout 公共 API 挂顶栏两端，Δ-10 保留不删）、左栏＝app/tabshell.py 三页签（装配树/
编程/路径仿真）、右栏＝workhead_panel＋joints_panel 常驻双面板；StepBar 摘出布局（薄壳，L-7）。
装配树工具行（裁决 6）的删除/清空接线也在本件：几何重建调 core.geometry 纯函数，失效沿用
pathctl.invalidate＋step2.clear＋_refresh_unlock 的既有机制。``build_controllers`` 的函数签名与
构造顺序不变（矩阵约束），信号连接只增不改旧序。
"""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import QPushButton, QSplitter, QVBoxLayout, QWidget

from app.checkctl import CheckController
from app.chips import HzMeter
from app.joints_panel import JointsPanel
from app.pathctl import PathController
from app.pop_import import install_t14
from app.stage import SPECS
from app.tabshell import TabShell
from app.topbar import TopBar
from app.workhead_panel import WorkheadPanel
from core.config import REPO_ROOT, load_machine
from core.geometry.edit_model import (drop_mesh_parts, part_count, remove_parts)  # 子模块直取：
from core.geometry.tessellate import encode_mesh_parts  # 包根 __all__ 是 T05 冻结面（守卫测试钉死），不动

CENTER_MIN = 320
LEFT_WIDTH = SPECS["std"].left_px       # 舞台档字面宽（蓝图 §5：std 365 ↔ wide 460）
RIGHT_WIDTH = SPECS["std"].right_px     # std 384 ↔ wide 490；换档由 shell._on_stage_changed 重设
MACHINE_YAML = REPO_ROOT / "config" / "machine.yaml"


def build_controllers(win) -> None:
    """构造路径/校核两个控制器（与原 MainWindow.__init__ 内的顺序一致）。"""
    win.pathctl = PathController(win.panel, win.bridge, win.stepbar, win.statusbar, win)
    win.checkctl = CheckController(win.panel, win.bridge, win.stepbar, win.statusbar,
                                   win.pathctl, win.workmode, win)


def build_workbench(win) -> QWidget:
    """装配主界面页：顶栏 │ 左三页签/视口/右双面板 │ 底栏（T13 范式）。"""
    work = QWidget()
    col = QVBoxLayout(work)
    col.setContentsMargins(0, 0, 0, 0)
    col.setSpacing(0)
    col.addWidget(_build_topbar(win))
    col.addWidget(_build_splitter(win), 1)
    col.addWidget(win.statusbar)
    return work


def _build_topbar(win) -> QWidget:
    win.topbar = TopBar(win.ui, win.badge, win.light)
    win._left_btn = _collapse_button("◀", win._toggle_left)     # Δ-10：保留，挂顶栏两端避让演示稿元素
    win._right_btn = _collapse_button("▶", win._toggle_right)
    win.topbar.layout().insertWidget(0, win._left_btn)
    win.topbar.layout().addWidget(win._right_btn)
    return win.topbar


def _collapse_button(text: str, slot) -> QPushButton:
    btn = QPushButton(text)
    btn.setProperty("collapse", "true")
    btn.setFixedWidth(28)
    btn.clicked.connect(slot)
    return btn


def _build_right(win) -> QWidget:
    pane = QWidget()
    pane.setObjectName("RightPane")
    cfg = load_machine(str(MACHINE_YAML))
    win.workhead = WorkheadPanel(win.workmode, cfg)
    win.joints = JointsPanel(cfg)
    box = QVBoxLayout(pane)
    box.setContentsMargins(0, 0, 0, 0)
    box.setSpacing(8)
    box.addWidget(win.workhead)
    box.addWidget(win.joints, 1)
    win._right_pane = pane
    return pane


def _build_splitter(win) -> QWidget:
    win.splitter = QSplitter(Qt.Orientation.Horizontal)
    win.tabshell = TabShell(win.panel)
    left = win.tabshell
    left.setMinimumWidth(200)
    right = _build_right(win)
    right.setMinimumWidth(280)
    win.viewpane.setMinimumWidth(CENTER_MIN)
    win.splitter.addWidget(left)
    win.splitter.addWidget(win.viewpane)
    win.splitter.addWidget(right)
    win.splitter.setCollapsible(1, False)
    win.splitter.setSizes([LEFT_WIDTH, CENTER_MIN + 240, RIGHT_WIDTH])
    win._left_pane = left
    return win.splitter


def connect_signals(win) -> None:
    """外壳级信号连接（原 MainWindow._wire 原样搬迁＋T12 启动序列＋T13 范式切换三段）。"""
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
    win.panel.step2.set_mode(None)        # 初始未选定工作模式 → 取点区锁定（G16，挂点变锁不变）
    win.pathctl.changed.connect(win._refresh_unlock)   # 路径生成/作废 → 重算④⑤门禁
    win.checkctl.changed.connect(win._refresh_unlock)  # 校核结论/指纹变化 → 重算⑤门禁（T08）
    f3 = QShortcut(QKeySequence("F3"), win)
    f3.activated.connect(win._on_invalidate_results)
    _wire_tabs(win)
    win.panel.set_step(1)
    # T12 新增：载入→登录→主界面启动序列（里程碑收集器驱动就绪；登录经同一槽进入）
    win.splash.entered.connect(win.enter_system)
    win.boot.all_done.connect(win.splash.set_ready_state)
    win.stage_host.stage_changed.connect(win._on_stage_changed)


def _wire_tabs(win) -> None:
    """T13 范式切换的信号段：页签导航、顶栏回填、右栏面板、工具行与链路只读侧。"""
    win.tabshell.tree.selected.connect(win._on_tree_selected)
    win.tabshell.tree.focused.connect(win._on_tree_focused)
    install_t14(win)                  # T14：导入浮层＋编程页签接线（先例＝sendctl.install_send_flow）
    win.topbar.logout_requested.connect(win.return_to_login)
    win.workmode.committed.connect(win.joints.set_mode)
    win.pathctl.changed.connect(lambda: win.tabshell.set_badge("prog", len(win.pathctl.segments())))
    win.checkctl.changed.connect(lambda: _on_check_result(win))
    pane = win.tabshell.tree_pane
    pane.delete_selected.connect(lambda ids: _apply_scene(win, ids, "删除选中"))
    pane.delete_group.connect(lambda ids: _apply_scene(win, ids, "删除整组"))
    pane.clear_all.connect(lambda: _on_clear_all(win))
    link = win.checkctl.send_flow.link
    win.hz_meter = HzMeter(lambda hz: (win.topbar.chips.set_hz(hz), win.light.set_hz(hz)))
    link.frames.connect(win.hz_meter.on_frames)
    link.frames.connect(win.joints.on_frames)
    link.link_state.connect(win.joints.on_link_state)
    win.bridge.received.connect(
        lambda t, d: _on_perf(win, t, d))


def _on_perf(win, type_: str, data: object) -> None:
    """渲染 fps 芯片：只观察桥 ``perf.fps``（livectl 的同源数据，⛔ 不改它）。"""
    if type_ == "perf.fps" and isinstance(data, dict):
        try:
            win.topbar.chips.set_fps(float(data["fps"]))
        except (KeyError, TypeError, ValueError):
            pass


def _on_check_result(win) -> None:
    """校核结论 → 判定灯/碰撞 ms 芯片/路径仿真页签徽标（真实值，无则 0）。"""
    res = win.checkctl._result
    win.topbar.verdict.set_result(res)
    win.topbar.chips.set_ms(getattr(res, "elapsed_ms", None))
    win.tabshell.set_badge("sim", len(res.cases) if res else 0)


def _on_clear_all(win) -> None:
    last = win._last or {}
    asm = last.get("asm")
    ids = [node.node_id for node in asm.iter_parts()] if asm is not None else []
    if not ids:
        win.statusbar.log("清空全部模型：当前没有已导入的模型")
        return
    _apply_scene(win, ids, "清空全部模型")


def _apply_scene(win, drop_ids, action: str) -> None:
    """工具行删除/清空的编排：core 纯函数重建 → 视口整体重载 → 沿用既有失效机制。"""
    last = win._last or {}
    asm, parts = last.get("asm"), last.get("parts") or []
    if asm is None or not drop_ids:
        win.statusbar.log(f"{action}：当前没有可删除的模型")
        return
    ids = set(drop_ids)
    new_asm = remove_parts(asm, ids)
    new_parts = drop_mesh_parts(parts, ids)
    payload = encode_mesh_parts(new_parts)
    win.bridge.call_view("mesh.load", {"reset": True, "parts": payload})
    win._last = {"asm": new_asm, "parts": new_parts, "payload": payload}
    # 先更新门禁真值再触发作废链（T14）：invalidate/clear 的事件里编程页签四步指示与
    # 门禁都会刷新，读到旧 _brep_ok 就会把「已清空」显示成旧件数（T14 e2e 实测暴露）
    win._brep_ok = bool(new_asm.is_brep) and part_count(new_asm.tree) > 0
    win.pathctl.invalidate(f"已{action}")
    win.panel.step2.clear()               # 点位 source_face 随删除失效 → 真清空（连带视口标号牌）
    win._refresh_unlock()
    count = part_count(new_asm.tree)
    win.tabshell.tree.populate(new_asm.tree_payload())
    win.tabshell.tree_pane.refresh_buttons()
    win.topbar.set_import_count(count)
    win.tabshell.set_badge("tree", count)
    win.statusbar.log(f"{action}：现存 {count} 件，原点位/路径/校核结果已作废")
