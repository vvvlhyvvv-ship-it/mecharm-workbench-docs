"""app.pop_import —— 三维导入浮层（基础版）＋ T14 接线总成（01 蓝图 §3.8，演示稿画面 07）。

浮层＝主窗内**覆盖层**（全屏半透明遮罩＋居中卡片，点遮罩／✕／Esc 关闭），顶栏
``import_requested`` 唤出（T13 预埋挂点）。**复用 step1 现有导入管线与缓存 ⛔ 不重写导入
逻辑**：拖拽／[选择文件] 都转 ``panel.step1.start_import``，进度＝step1 新增的 ``stage_changed``
转发信号（解析→三角化→优化 三阶段，ImportWorker 原文），结果读数＝``imported`` 信号里的
asm.stats 真值（件/面/耗时）。「目录命名即认领」「模型规格清单」完整版期 3 ⇒ 浮层内渲染
**禁用占位区**＋「待后续版本」（如实提示，Δ-7）。

⚠️ 卡片圆角 8px（蓝图 §4-C 模态档）需要 QSS，而 theme.py 冻结（T11 已收单）⇒ 本件用
string.Template 从 ``TOKENS`` 渲染一份**局部**样式表（手法同 theme.build_qss，色值零散写
字面量、唯一真值仍在 theme）；除此之外不写内联样式。

``install_t14(win)``＝T14 的接线总成（先例＝``sendctl.install_send_flow``：wiring._wire_tabs
一行调用，shell 零改动）：装浮层＋``pathctl.generated_ok→checkctl.run_check``（「生成并校验
轨迹」合并语义）＋编程页签的外壳数据注入与刷新链。
"""

from __future__ import annotations

import pathlib
import time
from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QFileDialog, QFrame, QHBoxLayout, QLabel, QMessageBox, QProgressBar,
                               QPushButton, QVBoxLayout, QWidget)

from app.theme import TOKENS
from core.config import REPO_ROOT

LATER_NOTE = "待后续版本"                  # 期 3 功能的禁用提示（Δ-7）
DROP_MAIN = "拖拽模型 / 目录到此处，或点击选择文件"
DROP_SUB = "STEP · IGES · STL"             # 与 step1._FILE_FILTER 同口径的支持格式
POP_WIDTH = 430                            # 演示稿 .popover 宽（HTML:285，基础版取窄档）

_QSS = Template("""
    #PopMask { background-color: rgba(6, 9, 12, 170); }
    #PopCard { background-color: $bg_card; border: 1px solid $border2; border-radius: ${r_modal}px; }
    #PopHead { background-color: $bg_panel; border-bottom: 1px solid $border; }
    #PopTitle { font-size: ${body_px}px; font-weight: 600; }
    #PopX { background-color: $bg_card; border: 1px solid $border; border-radius: ${r_ctl_s}px; }
    #DropZone { border: 1px dashed $border2; border-radius: ${r_ctl}px;
                background-color: $bg_panel; color: $text_dim; }
    #Phase3 { background-color: $bg_panel; border: 1px solid $border; border-radius: ${r_ctl_s}px;
              color: $text_faint; }
""")


class ImportPopup(QWidget):
    """三维导入浮层（基础版）。``show_pop``／遮罩点击／Esc 即开合，全程同一实例。"""

    def __init__(self, win, parent: QWidget | None = None) -> None:
        super().__init__(win if parent is None else parent)
        self.setObjectName("PopMask")         # QSS #PopMask 遮罩暗化（选择器按 objectName 匹配）
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)   # QWidget 画 QSS 背景的开关
        self._win = win
        self.setVisible(False)
        self.setAcceptDrops(True)             # 拖放整层收（PySide6 事件须类内重写，实例赋值无效）
        self.setStyleSheet(_QSS.substitute(TOKENS))
        QShortcut(QKeySequence(Qt.Key.Key_Escape), self).activated.connect(self.hide)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        center = QHBoxLayout()
        center.addStretch(1)
        card = QFrame()
        card.setObjectName("PopCard")
        card.setFixedWidth(POP_WIDTH)
        card.setLayout(self._build_body())
        center.addWidget(card)
        center.addStretch(1)
        outer.addLayout(center)
        outer.addStretch(1)
        step1 = win.panel.step1
        step1.stage_changed.connect(self._on_stage)
        step1.imported.connect(self._on_imported)
        step1.failed.connect(lambda msg: self._result.setText(f"✗ 导入未成功：{msg}"))

    def _build_body(self) -> QVBoxLayout:
        box = QVBoxLayout()
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        head = QFrame()
        head.setObjectName("PopHead")
        hrow = QHBoxLayout(head)
        hrow.setContentsMargins(12, 8, 12, 8)
        hrow.setSpacing(8)
        title = QLabel("三维模型导入 · 基础版")
        title.setObjectName("PopTitle")
        close = QPushButton("✕")
        close.setObjectName("PopX")
        close.setFixedWidth(26)
        close.clicked.connect(self.hide)
        hrow.addWidget(title, 1)
        hrow.addWidget(close)
        body = QWidget()
        brow = QVBoxLayout(body)
        brow.setContentsMargins(12, 10, 12, 12)
        brow.setSpacing(8)
        zone = QLabel(f"⇪\n{DROP_MAIN}\n{DROP_SUB}")
        zone.setObjectName("DropZone")
        zone.setAlignment(Qt.AlignmentFlag.AlignCenter)
        zone.setWordWrap(True)
        pick = QPushButton("选择文件")
        pick.setProperty("role", "primary")
        pick.clicked.connect(self.pick_file)
        self._bar = QProgressBar()
        self._bar.setRange(0, 3)
        self._bar.setVisible(False)
        self._phase = QLabel("")
        self._phase.setObjectName("Phase3")
        self._phase.setVisible(False)
        self._result = QLabel("尚未导入")
        self._result.setProperty("tone", "dim")
        self._result.setWordWrap(True)
        for text in ("目录命名即认领", "模型规格清单"):    # 完整版期 3：禁用占位区＋如实提示
            row = QLabel(f"{text} · {LATER_NOTE}")
            row.setProperty("tone", "dim")
            brow.addWidget(row)
        brow.addWidget(zone)
        brow.addWidget(pick)
        brow.addWidget(self._bar)
        brow.addWidget(self._phase)
        brow.addWidget(self._result)
        box.addWidget(head)
        box.addWidget(body, 1)
        return box

    def show_pop(self) -> None:
        self.setGeometry(self._win.rect())
        self.raise_()
        self.setVisible(True)

    def mouseReleaseEvent(self, event) -> None:
        if not self.rect().adjusted(0, 0, -10, -10).contains(event.position().toPoint()):
            self.hide()

    def pick_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择模型文件", "",
                                              "模型文件 (*.step *.stp *.iges *.igs *.stl);;所有文件 (*)")
        if path:
            self._win.panel.step1.start_import(path)

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self._win.panel.step1.start_import(urls[0].toLocalFile())

    def _on_stage(self, name: str) -> None:
        self._bar.setVisible(True)
        self._phase.setVisible(True)
        self._phase.setText(f"三阶段：{name}…")

    def _on_imported(self, res: object) -> None:
        asm = res["asm"]
        s = asm.stats
        self._bar.setValue(self._bar.maximum())
        self._phase.setText("三阶段完成")
        kind = "实体模型 ✓（可拾取、可算碰撞）" if asm.is_brep else "面片模型 ✗（不能用于编程）"
        self._result.setText(f"已导入 {s.get('parts', 0)} 件 · 面数 {s.get('tris', 0)} · "
                             f"耗时 {s.get('load_ms', 0.0):.0f} ms · {kind}")


def install_t14(win) -> None:
    """T14 接线总成（wiring._wire_tabs 一行调用，先例＝sendctl.install_send_flow）：浮层挂点＋页签注入＋合并语义＋存取动作。"""
    win.import_pop = ImportPopup(win)
    win.topbar.import_requested.connect(win.import_pop.show_pop)
    prog = win.tabshell.prog
    prog.bind(win)
    win.pathctl.generated_ok.connect(win.checkctl.run_check)   # 「生成并校验轨迹」合并语义
    win.pathctl.changed.connect(lambda: prog.refresh_flow(win))
    win.panel.step2.waypoints_changed.connect(lambda _w: prog.refresh_flow(win))
    win.panel.step1.imported.connect(lambda _r: prog.refresh_flow(win))
    win.checkctl.changed.connect(lambda: prog.refresh_check(win.checkctl._result))
    prog.store_log.connect(win.statusbar.log)
    actions = (save_project, export_json, export_csv, import_file, clear_program)
    for btn, fn in zip(prog._store_btns, actions):
        btn.clicked.connect(lambda _=False, f=fn: f(win))


# --- 程序存取编排（prog_tab 存取行的动作族；数据走 core.project proj/v1，⛔ 该件只读）------ #
def _project(win):
    """组装待存工程：mode/model/path/check 全取外壳真值（无则如实为 None，⛔ 不造）。"""
    from core.config import load_machine
    from core.path import summarize
    from core.project import ModelRef, build_project, check_snapshot, path_snapshot
    cfg = win.pathctl.kinematics()[0] or load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
    asm = (win._last or {}).get("asm")
    model = (ModelRef(asm.source_path, bool(asm.is_brep), int(asm.stats.get("parts", 0)))
             if asm is not None else None)
    segs = win.pathctl.segments()
    snap = (path_snapshot(segs, summarize(segs), win.panel.step3.kind(),
                          win.panel.step3.blending()) if segs else None)
    check = check_snapshot(win.checkctl._result) if win.checkctl._result is not None else None
    return build_project(cfg, win.workmode.current_mode(), model,
                         win.panel.step2.waypoints(), snap, check)


def _ask_path(win, title: str, filters: str, save: bool) -> pathlib.Path | None:
    """文件对话框（取消返回 None；保存态默认名＝工程名＋时间戳，蓝图 §6.3 文件名口径）。"""
    prog = win.tabshell.prog
    name = f"{_project(win).config_name}_{time.strftime('%Y%m%d_%H%M%S')}" if save else ""
    pick = QFileDialog.getSaveFileName if save else QFileDialog.getOpenFileName
    path, _ = pick(prog, title, name, filters)
    return pathlib.Path(path) if path else None


def save_project(win, path: str = "") -> pathlib.Path | None:
    """保存工程（.mproj，proj/v1 全量快照）。e2e／测试可直传 path 免对话框。"""
    from core.project import save
    target = pathlib.Path(path) if path else _ask_path(win, "保存工程", "工程文件 (*.mproj)", True)
    if target is None:
        return None
    out = save(_project(win), target)
    win.tabshell.prog.store_log.emit(f"工程已保存：{out}")
    return out


def export_json(win, path: str = "") -> pathlib.Path | None:
    """导出 JSON（同 proj/v1 工程原文，不改格式——蓝图 §6.1）。"""
    from core.project import save
    target = pathlib.Path(path) if path else _ask_path(win, "导出 JSON", "JSON 工程文件 (*.json)", True)
    if target is None:
        return None
    out = save(_project(win), target)
    win.tabshell.prog.store_log.emit(f"工程已导出 JSON：{out}")
    return out


def export_csv(win, path: str = "") -> pathlib.Path | None:
    """导出程序清单 CSV（UTF-8-BOM，Excel 可读；列＝序号/名称/X/Y/Z/类型）。"""
    from app.prog_tab import build_csv
    target = pathlib.Path(path) if path else _ask_path(win, "导出 CSV", "程序清单 (*.csv)", True)
    if target is None:
        return None
    text = build_csv(win.panel.step2.waypoints(), win.panel.step3.current_kind_text())
    target.write_text(text, encoding="utf-8-sig")
    win.tabshell.prog.store_log.emit(f"程序清单已导出 CSV：{target}")
    return target


def import_file(win, path: str = "") -> list | None:
    """导入：.mproj/.json＝proj/v1 无损恢复点位（结果按作废口径，core.project docstring）；
    .csv＝清单级恢复（法向与来源面不在列内 ⇒ 占位值，日志如实声明）。"""
    from app.prog_tab import parse_csv
    from core.config import load_machine
    from core.project import ProjectError, config_drift, load
    target = pathlib.Path(path) if path else _ask_path(
        win, "导入", "工程文件 (*.mproj *.json);;程序清单 (*.csv)", False)
    if target is None:
        return None
    try:
        if target.suffix.lower() == ".csv":
            points = parse_csv(target.read_text(encoding="utf-8-sig"))
            win.panel.step2.set_waypoints(points)
            win.tabshell.prog.store_log.emit(
                f"已按清单导入 {len(points)} 点（CSV 不含法向与来源面，按占位恢复）")
            return points
        project = load(target)
    except (ProjectError, ValueError, OSError) as exc:
        win.tabshell.prog.store_log.emit(f"导入未成功：{exc}")
        return None
    drift = config_drift(project, load_machine(str(REPO_ROOT / "config" / "machine.yaml")))
    if drift:
        win.tabshell.prog.store_log.emit(drift)
    win.panel.step2.set_waypoints(list(project.waypoints))
    win.tabshell.prog.store_log.emit(
        f"工程已导入：恢复 {len(project.waypoints)} 点（路径与校核结果按作废口径，须重新生成）")
    return list(project.waypoints)


def clear_program(win) -> bool:
    """清空当前程序（点位）：二次确认后真清空（pathctl 经 waypoints_changed 自动作废）。"""
    points = win.panel.step2.waypoints()
    if not points:
        win.tabshell.prog.store_log.emit("清空：当前没有点位")
        return True
    if not _confirm(win, f"将清空当前程序的 {len(points)} 个点位（路径与校核一并作废），确定？"):
        return False
    win.panel.step2.clear()
    win.tabshell.prog.store_log.emit(f"已清空程序：{len(points)} 点")
    return True


def _confirm(win, text: str) -> bool:
    """清空二次确认（拆成独立函数：离屏 e2e 可替身，⛔ 不因此改判定）。默认按钮＝[取消]。"""
    box = QMessageBox(win.tabshell.prog)
    box.setWindowTitle("确认清空")
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(text)
    ok = box.addButton("清空", QMessageBox.ButtonRole.AcceptRole)
    box.setDefaultButton(box.addButton("取消", QMessageBox.ButtonRole.RejectRole))
    box.exec()
    return box.clickedButton() is ok
