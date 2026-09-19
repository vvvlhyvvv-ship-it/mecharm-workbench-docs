"""工作台主窗体（02 V2.0 §1 全局骨架的装配处；T12 改多页宿主，T13 范式切换）。

启动序列：载入页→登录页→主界面，同一 MainWindow 内**原地切换、不另开窗**（裁决 9）——
载入/登录＝app/splash.py 两态页（恒 1920×1080 逻辑构图）；主界面＝app/wiring.py 装配的
**T13 范式**：顶栏七区（app/topbar.py）｜左三页签（app/tabshell.py）｜右栏常驻双面板
（workhead/joints）｜底栏；StepBar 退役为薄壳（仍实例化、不进布局，99 台账 L-7）。
舞台＝app/stage.py（蓝图 §5 固定逻辑尺寸＋等比缩放，载入/登录不参与 wide 档）。启动里程碑
只报真实发生的步骤（app/splash.BootMilestones）：ICU 计时由 run.py 回填、配置/点表/缓存在
main() 实测、「视口就绪」取 ViewPane.loadFinished。控制器构造、工作台装配（T13 重排）与信号
连接在 app/wiring.py。颜色/字号一律走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

import os
import pathlib
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication, QMainWindow

from app.bridge import Bridge
from app.mode import ModeBadge, OnlineLight, WorkModeSelector
from app.panel import Panel
from app.splash import BOOT_STEPS, BootMilestones, SplashPane
from app.stage import MIN_H, MIN_W, StageHost
from app.statusbar import StatusBar
from app.stepbar import STEP_LABELS, StepBar
from app.theme import apply_theme
from app.viewpane import ViewPane
from app.wiring import CENTER_MIN, build_controllers, build_workbench, connect_signals
from core.config import REPO_ROOT, ConfigError, load_machine
from core.config.ui_config import UiConfig, load_ui
from core.geometry.face_point import face_point_from_tri
from core.geometry.import_model import GeometryError

UI_PATH = REPO_ROOT / "config" / "ui.yaml"


class MainWindow(QMainWindow):
    """多页宿主主窗体：载入→登录→主界面原地切换。"""

    def __init__(self, ui: UiConfig | None = None, stage_forced: str = "",
                 boot: BootMilestones | None = None) -> None:
        super().__init__()
        self.ui = ui or load_ui(str(UI_PATH))
        self.setWindowTitle("机械臂三维示教工作台")
        self.resize(1440, 860)
        self.setMinimumSize(MIN_W, MIN_H)    # 画面 12 口径：1366×768 等比可显
        self.setAcceptDrops(True)              # 拖放模型文件到窗口即导入（02 §2 步骤①）
        self._mode_ok = False                  # 已选定工作模式
        self._brep_ok = False                  # 已导入实体模型；面片模型保持 False → ②-⑤锁定
        self._last: object = None              # 最近导入结果（含 parts.face_index，留存供 T06）
        self._pick_on = False                  # 步骤②拾取态（pick.enable 的 on，进退步骤②时切换）
        self.boot = boot or BootMilestones(BOOT_STEPS[1:])

        self.bridge = Bridge(self)
        self.stepbar = StepBar()
        self.workmode = WorkModeSelector()
        self.badge = ModeBadge()
        self.light = OnlineLight()
        self.viewpane = ViewPane()
        self.viewpane.view().setAcceptDrops(False)  # 让拖放冒泡到主窗（WebEngine 默认吞 drop）
        self.panel = Panel()
        self.statusbar = StatusBar(self.ui)
        build_controllers(self)

        self.stage_host = StageHost(forced=stage_forced, default=self.ui.stage_default)
        self.setCentralWidget(self.stage_host)
        self.splash = SplashPane(self.ui, self.boot)
        self.stage_host.set_splash(self.splash)
        self.stage_host.set_workbench(build_workbench(self))
        self.stage_host.show_splash()
        self._splash_guard = QTimer(self)     # splash_max_ms 上限：到点即绪（未完项如实标注）
        self._splash_guard.setSingleShot(True)
        self._splash_guard.timeout.connect(lambda: self.splash.set_ready_state(self.boot.is_all_done()))
        self._splash_guard.start(self.ui.splash_max_ms)

        self.bridge.attach(self.viewpane.page())
        connect_signals(self)
        self.viewpane.start()
        self.boot.begin("viewport")

    # --- 启动序列与舞台 -------------------------------------------------------- #
    def enter_system(self, user: str = "", name: str = "") -> None:
        """「进入系统」唯一入口（登录页按钮/回车与 e2e 走同一槽；T13 顶栏「退出」的对称面）。"""
        if not user or not name:
            user, name = self.splash.login_values()
        self._splash_guard.stop()
        self.stage_host.show_workbench()
        self.topbar.set_user(user, name)   # 用户盒以登录页实值回填（T13 顶栏）
        self.statusbar.log(f"已进入系统：{name}（{user}）")

    def return_to_login(self) -> None:
        """回登录页（舞台回登录档＝16:9；T13 顶栏「退出」挂本槽——裁决 9 连带）。"""
        self.stage_host.show_splash()
        self.splash.set_ready_state(self.boot.is_all_done())
        self.statusbar.log("已退回登录页")

    def _on_stage_changed(self, kind: str) -> None:
        spec = self.stage_host.spec()
        self.splitter.setSizes([spec.left_px, CENTER_MIN + 240, spec.right_px])
        self._push_viewport_fs()
        self.statusbar.log(f"舞台档位：{spec.label()}")

    def _push_viewport_fs(self) -> None:
        """视口 HTML 的 ``--fs``（蓝图 §5 缩放第②层：WebEngine 不做位图缩放，经
        app/bridge.py:54 同一条 runJavaScript 通道直写 CSS 变量——不是桥消息）。"""
        fs = self.stage_host.spec().fs
        self.viewpane.page().runJavaScript(
            f"document.documentElement.style.setProperty('--fs','{fs:g}')")

    def _on_view_load(self, ok: bool) -> None:
        if not ok:
            return
        self.bridge.set_ready(True)
        self.statusbar.log("视口就绪，发送 ping")
        self.bridge.ping(1)
        self.boot.mark("viewport", "单视口")
        self._push_viewport_fs()

    # --- 既有外壳行为（T02–T10 已验收，语义不变） -------------------------------- #
    def _on_step_clicked(self, n: int) -> None:
        self.stepbar.set_current(n)
        self.panel.set_step(n)
        self._set_pick_active(n == 2)          # 仅步骤②开启拾取态（半透明＋标号牌）
        self.statusbar.log(f"切换到 {STEP_LABELS[n - 1]}")

    def _on_mode_committed(self, name: str) -> None:
        self._mode_ok = True
        self.panel.step2.set_mode(name)        # 顶部第一行常显当前工作模式、解锁列表（G16）
        self._refresh_unlock()
        tail = ("，步骤②③已解锁（④⑤待路径生成后解锁）" if self._brep_ok
                else "（待导入实体模型后解锁步骤②③）")
        self.statusbar.log(f"工作模式：{name}{tail}")

    def _on_mode_switched(self, name: str) -> None:
        self.pathctl.invalidate("已切换工作模式")  # 先按换臂原因作废路径，再清点（点位变化亦触发作废）
        self.panel.step2.clear()               # 换臂结果作废：先真清空点位（连带视口标号牌）
        self.bridge.call_view("invalidate", {"mode": name})
        self.statusbar.log("结果作废：已清空当前点位与路径，换臂后须重新示教与校核")

    def _on_bridge_msg(self, type_: str, data: object) -> None:
        if type_ == "pick.face":
            return self._on_pick_face(data)
        self.statusbar.log(f"桥 echo：收到 {type_} {data}")

    def _on_pick_face(self, data: object) -> None:
        """视口左键命中 → core 换算真实点＋真法向 → 注入步骤②点位列表（数据源唯一在 core）。"""
        if self._last is None:
            self.statusbar.log("尚未导入模型，无法取点")
            return
        if not isinstance(data, dict):
            self.statusbar.log(f"pick.face 载荷异常：{data!r}")
            return
        try:
            fp = face_point_from_tri(self._last["parts"], int(data["mesh_id"]),
                                     int(data["face_id"]), float(data["u"]), float(data["v"]))
        except (GeometryError, KeyError, ValueError, TypeError) as exc:
            self.statusbar.log(f"取点失败：{exc}")
            return
        self.panel.step2.add_face_point(fp)

    def _on_waypoints_changed(self, _wps: object) -> None:
        """点位列表变化 → 把权威显示清单整体推给视口标号牌（前端不存真值，只投影）。"""
        self._refresh_pick()

    def _set_pick_active(self, on: bool) -> None:
        """进／退步骤②：切换拾取态（on 决定半透明＋十字光标＋标号牌是否生效）。"""
        self._pick_on = on
        self._refresh_pick()

    def _refresh_pick(self) -> None:
        """推送 pick.enable：on＝当前是否步骤②拾取态，markers＝core 点位的显示投影（整体替换）。"""
        markers = [{"id": w.id, "name": w.name, "pos": list(w.pos_mm)}
                   for w in self.panel.step2.waypoints()]
        self.bridge.call_view("pick.enable", {"on": self._pick_on, "markers": markers})

    def _on_invalidate_results(self) -> None:
        """F3「结果作废」：真清空点位列表（连带视口标号牌），保留拾取态以便立即重新示教。"""
        self.pathctl.invalidate("已按 F3 作废结果")
        self.panel.step2.clear()
        self.statusbar.log("结果作废：已清空当前点位（含视口标号牌），可重新示教")

    def _refresh_unlock(self) -> None:
        # 步骤②③需“已选工作模式 且 已导入实体模型”同时成立（面片模型不可编程）
        base = self._mode_ok and self._brep_ok
        for n in (2, 3):
            self.stepbar.set_step_enabled(n, base)
        # 步骤④另需路径已生成且无不可达段（完成标准②：越界→无法进入④）；步骤⑤再需校核结论非干涉
        # 且路径指纹一致（T08 禁发双阻断第①条：按钮置灰；第②条在 checkctl.send_path() 入口内）
        self.stepbar.set_step_enabled(4, base and self.pathctl.ready())
        self.stepbar.set_step_enabled(5, base and self.checkctl.ready())

    def _on_imported(self, res: object) -> None:
        asm = res["asm"]
        had_points = bool(self.panel.step2.waypoints())
        self._last = res
        self.bridge.call_view("mesh.load", {"reset": True, "parts": res["payload"]})
        self.pathctl.invalidate("已导入新模型")
        self.panel.step2.clear()              # 新模型 → 原点位 source_face 失效，结果作废
        self.tabshell.tree.populate(asm.tree_payload())   # T13：树在左栏装配树页签内
        self.stepbar.mark_completed(1)        # 红线④：步骤①导入成功即标记完成
        self._brep_ok = bool(asm.is_brep)
        self._refresh_unlock()
        name = pathlib.Path(asm.source_path).name
        kind = "实体模型 ✓" if asm.is_brep else "面片模型 ✗（不能用于编程，步骤②保持锁定）"
        tail = "；原点位已作废" if had_points else ""
        count = asm.stats.get("parts", 0)
        self.topbar.set_import_count(count)          # T13：件数徽标（顶栏＋页签，真实值）
        self.tabshell.set_badge("tree", count)
        self.tabshell.tree_pane.refresh_buttons()
        self.statusbar.log(f"已导入 {name}，{count} 个零件，{kind}{tail}")

    def _on_tree_selected(self, ids: list) -> None:
        self.bridge.call_view("hl.set", {"ids": ids, "semantic": "ok"})

    def _on_tree_focused(self, ids: list) -> None:
        self.bridge.call_view("hl.set", {"ids": ids, "semantic": "ok", "focus": True})

    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.panel.step1.start_import(urls[0].toLocalFile())

    def _toggle_left(self) -> None:
        vis = not self._left_pane.isVisible()
        self._left_pane.setVisible(vis)
        self._left_btn.setText("◀" if vis else "▶")

    def _toggle_right(self) -> None:
        vis = not self._right_pane.isVisible()   # T13：右栏＝常驻双面板容器（Δ-10 折叠钮保留）
        self._right_pane.setVisible(vis)
        self._right_btn.setText("▶" if vis else "◀")


def _startup_checks(boot: BootMilestones) -> bool:
    """载入页里程碑的真实来源：配置加载／点表校验／缓存目录（蓝图 §3.1，⛔ 禁编造行）。"""
    t0 = time.perf_counter()
    try:
        cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
    except ConfigError as exc:
        print(f"参数校验不通过：\n{exc}", file=sys.stderr)
        return False
    boot.mark("config", f"{(time.perf_counter() - t0) * 1000:.0f} ms · {len(cfg.axes)} 轴")
    boot.mark("nodes", f"读 {len(cfg.opcua.read_nodes)} 键 · 写 {len(cfg.opcua.write_nodes)} 键")
    cache = pathlib.Path(cfg.paths.cache_dir)
    try:
        cache.mkdir(parents=True, exist_ok=True)
        writable = os.access(cache, os.W_OK)
    except OSError:
        writable = False
    boot.mark("cache", cache.name if writable else f"{cache.name}（不可写）")
    return True


def main(stage: str = "auto", ui_profile: str = "default", icu_ms: float | None = None) -> int:
    """启动外壳（唯一 QApplication 装配处；--stage／--ui-profile 由 run.py 解析后下传）。

    icu_ms＝run.py 在 QApplication 之前实测的入口引导耗时（回填给载入页日志；
    `python -m app.shell` 路径没有该计时 ⇒ 载入日志按实际少一行如实展示）。
    """
    try:
        ui = load_ui(str(UI_PATH), profile=ui_profile)
    except ConfigError as exc:
        print(f"界面配置校验不通过：\n{exc}", file=sys.stderr)
        return 2
    boot = BootMilestones(BOOT_STEPS if icu_ms is not None else BOOT_STEPS[1:])
    app = QApplication(sys.argv)
    apply_theme(app)
    win = MainWindow(ui=ui, stage_forced="" if stage == "auto" else stage, boot=boot)
    if icu_ms is not None:
        boot.mark("icu", f"{icu_ms:.0f} ms")
    win.show()
    app.processEvents()
    if not _startup_checks(boot):
        return 2
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
