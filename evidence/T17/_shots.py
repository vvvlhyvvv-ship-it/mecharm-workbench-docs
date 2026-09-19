"""evidence/T17/_shots.py —— T17 PLC 输出区与预览模态的取证截图（取证档启动，裁决 7／§1-9）。

以 ``--ui-profile evidence`` 同款构造（``load_ui(profile="evidence")``）起壳——公司名/水印/
版本号全为占位文案；画面内容＝自造基本体障碍＋自造两点路径（⛔ 非甲方模型/名称/尺寸）。
产出（本目录）：输出区禁用态／生成后汇总／超预算黄警示／预览模态四张 PNG ＋ 导出 CSV 样张
两份（UTF-8-BOM 在场，Excel 可读的实证样张）。拍完即关停，⛔ 不留常驻进程。

用法：`python evidence/T17/_shots.py`（输出落本目录，与 T11–T15 的 _shots 同惯例）。
"""

from __future__ import annotations

import contextlib
import dataclasses
import io
import os
import pathlib
import sys
import tempfile

os.environ["QT_QPA_PLATFORM"] = "windows"      # 真平台渲染（offscreen 中文会 tofu，同 T13 口径）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

import app.plc_out as plc_module  # noqa: E402
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.gp import gp_Pnt  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from app.shell import MainWindow  # noqa: E402
from app.theme import apply_theme  # noqa: E402
from core.config.ui_config import load_ui  # noqa: E402
from core.geometry.face_point import FacePoint  # noqa: E402
from core.process import steps_to_csv, vars_to_csv  # noqa: E402
from tests.cad_samples import write_step  # noqa: E402

OUT = pathlib.Path(__file__).parent
BOX_AT = (95.0, -20.0, -20.0)   # 自造障碍：X 95–135 正压在 0→200 的路径中段（⛔ 非甲方模型/尺寸）
POINTS = ((0.0, 0.0, 0.0), (200.0, 0.0, 0.0))


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def scroll_bottom(tab) -> None:
    area = tab.findChildren(QScrollArea)[0]
    area.verticalScrollBar().setValue(area.verticalScrollBar().maximum())
    pump(300)


def shot(widget, name: str) -> None:
    target = OUT / name
    widget.grab().save(str(target))
    print(f"已保存 {target.name}")


def main() -> int:
    ui = load_ui(str(pathlib.Path("config/ui.yaml")), profile="evidence")   # 取证档占位（裁决 7）
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    win = MainWindow(ui=ui)
    win.show()
    pump(1200)
    win.enter_system()
    pump(600)
    win.workmode.select_row(3)     # 选定工作模式 ⇒ 解锁取点区（G16；与 e2e_rig MODE_INDEX 同行）
    win.tabshell.switch_to("prog")
    pump(400)
    area = win.tabshell.prog.plc_out
    scroll_bottom(win.tabshell.prog)
    shot(win, "01_PLC输出区_未生成路径_整体禁用_evidence_1920x1080.png")

    # ① 导入压在路径正中的自造立方障碍（走真导入链路），取两点生成＋校核（干涉 ⇒ 红行黄示警）
    with tempfile.TemporaryDirectory(prefix="t17_shots_") as tmp:
        path = pathlib.Path(tmp) / "obstacle.step"
        with contextlib.redirect_stdout(io.StringIO()):
            write_step(BRepPrimAPI_MakeBox(gp_Pnt(*BOX_AT), 40.0, 40.0, 40.0).Shape(), path)
        win._last = None
        win.panel.step1.start_import(str(path))
        for _ in range(200):
            pump(100)
            if win._last is not None:
                break
        win.panel.step2.add_face_point(FacePoint(pos_mm=POINTS[0], normal=(0.0, 0.0, 1.0),
                                                 source_face=1))
        win.panel.step2.add_face_point(FacePoint(pos_mm=POINTS[1], normal=(0.0, 0.0, 1.0),
                                                 source_face=2))
        win.pathctl.generate()
        win.checkctl.run_check()
        pump(400)
        area._btn_build.click()
        scroll_bottom(win.tabshell.prog)
        shot(win, "02_PLC输出区_生成后_汇总与预算_evidence_1920x1080.png")

        # ② 超预算黄警示场景（预算改 1＋逐点编排 2 工步 ⇒ 真超限；如实呈现仍可导出；拍完还原）
        real_ui = win.ui
        win.ui = dataclasses.replace(real_ui, process_step_budget=1)
        area._mode.setCurrentIndex(1)                 # 逐点：2 点位 ⇒ 2 工步 > 预算 1
        area._btn_build.click()
        scroll_bottom(win.tabshell.prog)
        shot(win, "03_PLC输出区_超预算黄警示_evidence_1920x1080.png")
        win.ui = real_ui
        area._mode.setCurrentIndex(0)
        area._btn_build.click()

        # ③ 导出 CSV 样张（真导出路径，QFileDialog 替身同 e2e_plc；样张留 evidence 实证 BOM）
        def _fake(_parent, _caption, default: str, _filter: str):
            return str(OUT / pathlib.Path(default).name), ""

        real_dialog = plc_module.QFileDialog.getSaveFileName
        plc_module.QFileDialog.getSaveFileName = staticmethod(_fake)
        try:
            area._btn_export.click()
            pump(300)
        finally:
            plc_module.QFileDialog.getSaveFileName = real_dialog
        for suffix, sample in (("工步数据表", "样张_工步数据表.csv"), ("变量映射", "样张_变量映射.csv")):
            source = next(OUT.glob(f"*_{suffix}_*.csv"))
            target = OUT / sample
            source.replace(target)
            body = target.read_bytes()
            print(f"样张 {sample}：{len(body)} 字节，前 3 字节＝{body[:3]!r}（BOM 在场）")

        # ④ 预览模态（演示稿画面 09 对照；红条两行＋KPI＋工步表 10 列＋页脚）
        area._btn_preview.click()
        pump(400)
        shot(win, "04_预览模态_用途声明与工步表_evidence_1920x1080.png")
        win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
