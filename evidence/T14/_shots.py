"""evidence/T14/_shots.py —— T14 完成标准截图取证（离屏禁用：真实平台渲染，字体才不是空心框）。

纪律：凡入 evidence/ 的一律取证档（``load_ui(profile="evidence")``，裁决 7／蓝图 §1-9）；
画面里的模型为**现场自造 40 mm 立方**（tests.cad_samples，⛔ 非甲方工件）。截图对应卡片
完成标准：编程页签四步指示四态（导入前／导入后／生成并校验后——真实状态驱动）、
导入浮层（对照演示稿画面 07，基础版＝认领/规格清单禁用占位）、编程页签整页内容
（对照画面 04：四步流水线／工具区／存取行／点位表／段清单／生成并校验＋下发执行＋结论行）。
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import os
import pathlib
import sys
import tempfile
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
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
BOX_AT = (0.0, -20.0, -20.0)
BOX = (40.0, 40.0, 40.0)         # 自造基本体（⛔ 非甲方工件尺寸）
POINTS = ((0.0, 0.0, 0.0), (100.0, 0.0, 0.0), (200.0, 0.0, 0.0))


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grab(widget, name: str) -> None:
    target = OUT / name
    widget.grab().save(str(target))
    print(f"  {target.name}  {widget.width()}x{widget.height()}  sha256={sha256(target)[:16]}…")


def set_size(win, w: int, h: int) -> None:
    win.resize(w, h)
    pump(300)
    if (win.width(), win.height()) != (w, h):
        win.resize(w, h)
        pump(500)
    print(f"  [尺寸] {w}×{h} ⇒ {win.width()}×{win.height()}（档位 {win.stage_host.kind()}）")


def wait_viewport(win, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump(200)
        if win.boot.state("viewport") == "done":
            return True
    return False


def import_box(win, tmp: str) -> None:
    path = pathlib.Path(tmp) / "box.step"
    with contextlib.redirect_stdout(io.StringIO()):
        write_step(BRepPrimAPI_MakeBox(gp_Pnt(*BOX_AT), *BOX).Shape(), path)
    win.import_pop.hide()                 # 取证走浮层/管线同源，但截图序列自己控制开合
    win.panel.step1.start_import(str(path))
    deadline = time.monotonic() + 40.0
    while time.monotonic() < deadline:
        pump(100)
        if win._last is not None:
            return
    print("  !! 导入 40 s 未完成（如实：后续指示为空态）")


def main() -> int:
    app = QApplication([])
    apply_theme(app)
    evidence = load_ui(str(UI_PATH), profile="evidence")
    with tempfile.TemporaryDirectory(prefix="t14_shots_") as tmp:
        win = MainWindow(ui=evidence)
        win.show()
        pump(60)                          # 先让 show 落位（WM 只在首显时钳尺寸，之后 resize 可超屏）
        set_size(win, 1920, 1080)
        win.enter_system()
        if not wait_viewport(win):
            print("  !! 视口 20 s 未就绪（如实）")
        pump(300)
        prog = win.tabshell.prog
        win.tabshell.switch_to("prog")
        pump(200)
        win.workmode.select_row(3)        # 「氧化皮破碎」（7 轴 ≤8 槽位，同 e2e MODE_INDEX；解锁取点区）
        pump(200)
        print("== 四步指示·导入前（全「—」；工具区/插入动作/下发执行全禁用，Δ-7/Δ-4）==")
        grab(win, "01_编程页签_导入前_evidence_1920x1080.png")
        import_box(win, tmp)
        pump(600)
        print("== 四步指示·导入后（①done＝真实件数）==")
        grab(win, "02_编程页签_导入后_evidence_1920x1080.png")
        for index, pos in enumerate(POINTS, start=1):
            win.panel.step2.add_face_point(
                FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
        pump(200)
        prog._panel.step3._btn.click()    # 生成并校验轨迹（合并语义：生成→自动校核）
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline:
            pump(100)
            if win.checkctl._result is not None:
                break
        pump(400)
        print("== 四步指示·生成并校验后（③done＋结论行三通道＋涉事红行；对照演示稿画面 04）==")
        grab(win, "03_编程页签_生成并校验后_evidence_1920x1080.png")
        scrolls = [c for c in prog.children()
                   if callable(getattr(c, "widget", None)) and c.widget() is not None]
        if scrolls:
            grab(scrolls[0].widget(), "04_编程页签_滚动内容_生成校验后_evidence.png")
        print("== 三维导入浮层（对照演示稿画面 07；基础版＝认领/规格清单禁用占位）==")
        win.topbar._import_btn.click()
        pump(300)
        grab(win, "05_三维导入浮层_evidence_1920x1080.png")
        win.import_pop.hide()
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
