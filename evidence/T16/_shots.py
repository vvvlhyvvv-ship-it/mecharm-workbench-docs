"""evidence/T16/_shots.py —— T16 干涉体系取证截图（完成标准：模态＋脉冲圈＋高亮条＋树红标四件套
＋无干涉场景对照）。

**取证档启动**（裁决 7／§1-9）：``load_ui(profile="evidence")`` 起壳，公司名/水印/版本号全为占位
文案。**干涉场景**＝自造立方压在路径正中（dist≤0 ⇒ 校核不通过 ⇒ 阻断式模态自动弹出、视口红色脉冲
圈＋底缘高亮条、装配树涉事零件整行红标、顶栏「报警与日志」徽标＝活动干涉组数）。**无干涉场景**＝
远障碍（间隙 500 mm ⇒ 0 涉事）对照：模态不弹、清单「—」、徽标 0。视口画面（脉冲圈/高亮条属
WebEngine 合成层）用 **QScreen 级抓取**（QWidget.grab 抓不到 WebEngine 内容）；其余 Qt 页签用
grab()。fps 角标原文随拍打印（真平台对照值，e2e_collision C5 为 offscreen 宽阈）。

用法：`python evidence/T16/_shots.py`（输出 PNG 落本目录，与 T11–T15 的 _shots 同惯例；拍完即关）。
"""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "windows"      # 真平台渲染（offscreen 中文会 tofu，同 T13 _shots 口径）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.gp import gp_Pnt  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.shell import MainWindow  # noqa: E402
from app.theme import apply_theme  # noqa: E402
from core.config.ui_config import load_ui  # noqa: E402
from core.geometry.face_point import FacePoint  # noqa: E402
from tests.cad_samples import write_step  # noqa: E402

OUT = pathlib.Path(__file__).parent
CLASH_AT = (95.0, -20.0, -20.0)    # 干涉立方：X 95–135 正压路径中段（⛔ 非甲方模型/尺寸）
FAR_AT = (903.0, -20.0, -20.0)     # 远障碍：间隙 500 mm ⇒ 0 涉事（无干涉对照）
POINTS = ((0.0, 0.0, 0.0), (200.0, 0.0, 0.0))


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def import_box(win: "MainWindow", tmp: str, at: tuple, name: str) -> None:
    path = pathlib.Path(tmp) / f"{name}.step"
    with contextlib.redirect_stdout(io.StringIO()):
        write_step(BRepPrimAPI_MakeBox(gp_Pnt(*at), 40.0, 40.0, 40.0).Shape(), path)
    win._last = None
    win.panel.step1.start_import(str(path))
    for _ in range(200):
        pump(100)
        if win._last is not None:
            return
    raise RuntimeError("导入超时")


def recheck(win: "MainWindow") -> None:
    """导入换模型即作废 ⇒ 重摆两点、生成并校核（真链路，模态按 verdict 自动弹/不弹）。"""
    win.panel.step2.clear()
    for index, pos in enumerate(POINTS, start=1):
        win.panel.step2.add_face_point(
            FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
    win.pathctl.generate()
    win.checkctl.run_check()
    pump(500)


def grab_window(win: "MainWindow", path: pathlib.Path) -> None:
    """全窗 grab（T13 同款手法）——脉冲圈/高亮条是 **DOM 层**元素，随 WebEngine 合成帧入图。"""
    win.raise_()
    pump(700)                      # 等一帧合成（遮挡场景下 rAF 节流，给足余量再抓）
    win.grab().save(str(path))
    print(f"已保存 {path}")


def main() -> int:
    ui = load_ui(str(pathlib.Path("config/ui.yaml")), profile="evidence")   # 取证档占位文案（裁决 7）
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    win = MainWindow(ui=ui)
    win.show()
    pump(1500)
    win.enter_system()
    pump(600)
    win.workmode.select_row(3)
    with tempfile.TemporaryDirectory(prefix="t16_shots_") as tmp:
        # ── 干涉场景四件套 ──────────────────────────────────────────────────────────
        import_box(win, tmp, CLASH_AT, "clash")
        recheck(win)
        modal = win.checkctl._alarm
        if modal is not None and modal.isVisible():
            modal.grab().save(str(OUT / "t16_01_阻断式报警模态.png"))
            print(f"已保存 {OUT / 't16_01_阻断式报警模态.png'}")
            modal.close()
        pump(300)
        grab_window(win, OUT / "t16_02_视口脉冲圈与高亮条.png")      # 全窗＝脉冲圈＋高亮条＋顶栏徽标
        win.tabshell.switch_to("tree")
        pump(400)
        win.tabshell.tree_pane.grab().save(str(OUT / "t16_03_装配树干涉红标.png"))
        print(f"已保存 {OUT / 't16_03_装配树干涉红标.png'}")
        win.tabshell.switch_to("sim")
        pump(400)
        win.tabshell.sim.grab().save(str(OUT / "t16_04_干涉清单与涉事设备列.png"))
        print(f"已保存 {OUT / 't16_04_干涉清单与涉事设备列.png'}")
        print(f"顶栏报警徽标（干涉态）＝{win.topbar._alarm_badge.text()}｜清单原文＝{win.tabshell.sim._clash.text()[:60]}…")
        # ── 无干涉场景对照（模态不弹、清单/设备列「—」、徽标 0）──────────────────────
        import_box(win, tmp, FAR_AT, "far_block")
        recheck(win)
        pump(300)
        win.tabshell.switch_to("tree")
        pump(300)
        grab_window(win, OUT / "t16_05_无干涉对照_树与徽标.png")
        win.tabshell.switch_to("sim")
        pump(300)
        win.tabshell.sim.grab().save(str(OUT / "t16_06_无干涉对照_清单与KPI.png"))
        print(f"已保存 {OUT / 't16_06_无干涉对照_清单与KPI.png'}")
        print(f"无干涉对照：模态弹过={win.checkctl._alarm is not None and win.checkctl._alarm.isVisible()}｜"
              f"清单「{win.tabshell.sim._clash.text()[:12]}」｜徽标={win.topbar._alarm_badge.text()}")
        # ── fps 真平台读数（顶栏「渲染」芯片＝perf.fps 实测；脉冲走 DOM/CSS 合成层不进渲染循环）──
        win.pathctl.play()
        pump(2300)
        fps_chip = win.topbar.chips._fps
        print(f"顶栏「渲染」芯片原文（脉冲开着播放中）＝{fps_chip.text()} fps")
        win.pathctl.pause()
        pump(300)
        win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
