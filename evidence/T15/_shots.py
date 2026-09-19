"""evidence/T15/_shots.py —— T15 路径仿真页签的取证截图（完成标准：干涉场景红绿带＋「估算」字样）。

**取证档启动**（裁决 7／§1-9：含甲方标识的画面⛔不得入库）：以 ``--ui-profile evidence`` 同款构造
（``load_ui(profile="evidence")``）起壳——公司名/水印/版本号全为占位文案。**干涉场景**＝障碍立方
压在路径正中（dist≤0 ⇒ 结论不通过、KPI 干涉步>0、时间轴红带、下发许可禁止），与 e2e_sim 的预警
场景互补。拍完即关停，⛔ 不留常驻进程。

用法：`python evidence/T15/_shots.py`（输出 PNG 落本目录，与 T11/T13 的 _shots 同惯例）。
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
BOX_AT = (95.0, -20.0, -20.0)   # 自造障碍：X 95–135 正压在 0→200 的路径中段（⛔ 非甲方模型/尺寸）
POINTS = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0))


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def main() -> int:
    ui = load_ui(str(pathlib.Path("config/ui.yaml")), profile="evidence")   # 取证档占位文案（裁决 7）
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    win = MainWindow(ui=ui)
    win.show()
    pump(1200)                     # 视口加载
    win.enter_system()
    pump(600)
    win.workmode.select_row(3)     # 选定工作模式 ⇒ 解锁取点区（G16；与 e2e_rig 的 MODE_INDEX 同行）
    # ① 导入压在路径正中的自造立方障碍（走真导入链路）
    with tempfile.TemporaryDirectory(prefix="t15_shots_") as tmp:
        path = pathlib.Path(tmp) / "obstacle.step"
        with contextlib.redirect_stdout(io.StringIO()):
            write_step(BRepPrimAPI_MakeBox(gp_Pnt(*BOX_AT), 40.0, 40.0, 40.0).Shape(), path)
        win._last = None
        win.panel.step1.start_import(str(path))
        for _ in range(200):
            pump(100)
            if win._last is not None:
                break
        # ② 取两点生成路径（有校核结论的时间轴/ KPI；干涉 ⇒ 禁发）
        win.panel.step2.add_face_point(FacePoint(pos_mm=POINTS[0], normal=(0.0, 0.0, 1.0), source_face=1))
        win.panel.step2.add_face_point(FacePoint(pos_mm=POINTS[1], normal=(0.0, 0.0, 1.0), source_face=2))
        win.pathctl.generate()
        win.checkctl.run_check()
        pump(400)
        win.tabshell.switch_to("sim")
        pump(600)
        win.tabshell.sim.grab().save(str(OUT / "t15_sim_干涉场景.png"))
        print(f"已保存 {OUT / 't15_sim_干涉场景.png'}")
        bottom = win.tabshell.sim.findChildren(__import__("PySide6.QtWidgets", fromlist=["QScrollArea"]).__dict__["QScrollArea"])[0]
        bottom.verticalScrollBar().setValue(bottom.verticalScrollBar().maximum())
        pump(300)
        win.tabshell.sim.grab().save(str(OUT / "t15_sim_轨迹清单与涉事设备占位.png"))
        print(f"已保存 {OUT / 't15_sim_轨迹清单与涉事设备占位.png'}")
        win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
