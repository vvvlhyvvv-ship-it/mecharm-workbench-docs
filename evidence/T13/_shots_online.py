"""evidence/T13/_shots_online.py —— 在线态截图佐证（卡片完成标准：8 轴有值、14 轴「—」＋
「点表未收」、pending「待回执」徽标可见——本单最易造假处，须真链路在线后截）。

不借用 ``tools/e2e_rig.Rig``（它按默认档起壳）：此处以**取证档** ui.yaml 构造 MainWindow，
再走与 e2e G 节完全相同的真链路（真下拉选臂 → step5.connect_requested 真按钮信号 → 本机
模拟器 → link_state ONLINE → frames 流入）。只连 127.0.0.1（D-6 禁真 PLC），拍完即关停。
"""

from __future__ import annotations

import contextlib
import io
import os
import pathlib
import sys
import tempfile
import time

os.environ["QT_QPA_PLATFORM"] = "windows"      # 真平台渲染（offscreen 字体为空，中文全 tofu）
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

OUT = pathlib.Path(__file__).resolve().parent
UI_PATH = pathlib.Path(__file__).resolve().parents[2] / "config" / "ui.yaml"
THREE_POINTS = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0))   # 同 e2e_rig 口径


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def wait(predicate, seconds: float = 40.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump(100)
        if predicate():
            return True
    return bool(predicate())


def prepare_path(win, tmp: str) -> None:
    """连接前置（linkctl._config 要步骤③那份配置）：自造立方 → 真 step2 接口 3 点 → 生成路径。"""
    box = pathlib.Path(tmp) / "box.step"
    with contextlib.redirect_stdout(io.StringIO()):
        write_step(BRepPrimAPI_MakeBox(gp_Pnt(0.0, -20.0, -20.0), 40.0, 40.0, 40.0).Shape(), box)
    win.panel.step1.start_import(str(box))
    if not wait(lambda: win._last is not None):
        raise SystemExit("导入未完成，前置不齐（如实中止）")
    for index, pos in enumerate(THREE_POINTS, start=1):
        win.panel.step2.add_face_point(
            FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
    win.pathctl.generate()
    pump(300)


def main() -> int:
    app = QApplication([])
    apply_theme(app)
    evidence = load_ui(str(UI_PATH), profile="evidence")
    with tempfile.TemporaryDirectory(prefix="t13_online_") as tmp:
        win = MainWindow(ui=evidence)
        win.show()
        pump(60)
        win.resize(1920, 1080)
        pump(300)
        win.splash.set_ready_state(win.boot.is_all_done())
        win.enter_system()
        win.workmode.select_row(3)                          # 氧化皮破碎（真列表行 ⇒ committed）
        pump(200)
        prepare_path(win, tmp)
        win.panel.step5.connect_requested.emit()            # 走真按钮信号连本机模拟器
        link = win.checkctl.send_flow.link
        up = wait(lambda: link.is_up)
        online = wait(lambda: win.light.property("online") == "true", seconds=15.0)
        pump(3000)                                          # 收几秒真实回读帧
        print(f"  链路可用={up}；在线灯={win.light.text()}；Hz 芯片={win.topbar.chips._hz.text()}")
        joints = win.joints
        readable = {a: joints.value_text(a) for a in joints.readable}
        dim = sum(1 for a in joints.unreadable if joints.value_text(a) == "—")
        print(f"  有回读 8 轴读数：{readable}")
        print(f"  无回读 14 轴「—」计数：{dim}/14；软限位行：{joints.softline.text()}")
        target = OUT / "08_右栏_在线8轴有值_evidence.png"
        win._right_pane.grab().save(str(target))
        print(f"  {target.name} 已存")
        target2 = OUT / "09_顶栏_在线芯片双灯_evidence.png"
        win.topbar.grab().save(str(target2))
        print(f"  {target2.name} 已存")
        win.checkctl.send_flow.shutdown()
        win.close()
        pump(300)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
