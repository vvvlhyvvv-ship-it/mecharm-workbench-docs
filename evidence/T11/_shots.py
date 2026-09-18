"""evidence/T11/_shots.py —— T11 视觉基线取证截图（窗口模式跑，本机执行）。

对应 T11 卡「完成标准」第 2／4 条：
  01 启动态：空态卡（模态/浮层档 8px）＋顶栏徽标胶囊＋右栏占位卡（卡片档 0px）＋步骤①主按钮（青底深字）
  02 导入后：视口浅色画布 #d9e2ea＋自造模型（⚠️ 自造样件，不含甲方数据，evidence/README.md 入库边界）
  03 导入中：三阶段进度条（小控件档 chunk 4px；进度条仅忙时可见，轮询抓拍）
  04 装配树选中：树行选中态＝青底深字（QSS ::item:selected）

链路纪律同 e2e_rig：导入走 step1.start_import 真链路（QThread→shell→mesh.load→视口），
⛔ 不直调 core 抄近道。跑法（仓根）：D:/Miniforge3/envs/mecharm/python.exe evidence/T11/_shots.py
"""

from __future__ import annotations

import contextlib
import io
import pathlib
import sys
import tempfile
import time

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from app.bootstrap import preload_windows_icu  # noqa: E402  ICU 红线：必须先于 PySide6

preload_windows_icu()

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.gp import gp_Pnt  # noqa: E402
from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.shell import MainWindow  # noqa: E402
from app.theme import apply_theme  # noqa: E402
from tests import cad_samples  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent


def pump(app: QApplication, ms: int) -> None:
    """跑一段真事件循环（WebEngine 渲染/导入线程都靠它推进）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def save(win: MainWindow, name: str) -> None:
    ok = win.grab().save(str(OUT / name))
    print(f"  {'已存' if ok else '失败'}  {name}")


def main() -> int:
    app = QApplication.instance() or QApplication([])
    apply_theme(app)
    win = MainWindow()
    win.resize(1600, 900)
    win.show()
    pump(app, 1500)                       # 等 WebEngine 起页面（空态卡此时在场）
    print("[1/4] 启动态截图（空态卡 8px／徽标胶囊／占位卡 0px／主按钮青底深字）：")
    save(win, "01_启动_空态卡8px_胶囊徽标_占位卡0px.png")

    # 自造样件：两个互不接触的立方（⛔ 非甲方模型；compound ⇒ 装配树两叶可选中）
    tmp = tempfile.TemporaryDirectory(prefix="t11_shots_")
    path = pathlib.Path(tmp.name) / "two_boxes.step"
    with contextlib.redirect_stdout(io.StringIO()):       # 吞 OCC 写器统计噪声
        cad_samples.write_step(cad_samples.compound([
            BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), 60.0, 40.0, 40.0).Shape(),
            BRepPrimAPI_MakeBox(gp_Pnt(90.0, -20.0, 0.0), 40.0, 40.0, 60.0).Shape(),
        ]), path)

    print("[2/4] 真导入链路（进度条 4px chunk 轮询抓拍 + 导入后浅色画布）：")
    win._last = None
    win.panel.step1.start_import(str(path))
    deadline = time.monotonic() + 40.0
    got_progress = False
    while time.monotonic() < deadline and win._last is None:
        pump(app, 60)
        if not got_progress and win.panel.step1._progress.isVisible():
            save(win, "03_导入中_进度条chunk4px.png")
            got_progress = True
    if win._last is None:
        print("  [FAIL] 导入超时（40s），后续截图缺模型")
        return 1
    pump(app, 1500)                       # mesh.load → 视口按需重绘
    save(win, "02_导入后_浅色画布_自造模型.png")

    print("[3/4] 装配树选中态（青底深字）：")
    item = win.tree.topLevelItem(0)
    if item is not None and item.childCount() > 0:
        item = item.child(0)              # 落到叶（零件行）
    win.tree.setCurrentItem(item)
    win.tree.itemClicked.emit(item, 0)    # 走真信号 ⇒ hl.set 选中高亮＝accent 青
    pump(app, 800)
    save(win, "04_装配树选中_青底深字.png")

    print("[4/4] 完成。")
    tmp.cleanup()
    win.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
