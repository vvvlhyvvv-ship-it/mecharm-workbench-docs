"""evidence/T12/_shots.py —— T12 完成标准截图取证（离屏；evidence/** 免 300 行约束）。

纪律：凡入 evidence/ 的一律取证档（--ui-profile evidence 等效：load_ui(profile="evidence")，
裁决 7／蓝图 §1-9）。普通档对照截图含甲方名称 ⇒ **存仓外**（LOCAL_DIR），只留
「文件名＋SHA256＋留存位置」文字痕迹（04 §4 矩阵 evidence/ 行）。
载入态截图的里程碑全部走真实序列（ICU 计时在本入口实测、配置/点表/缓存经
app.shell._startup_checks 实测、视口取 loadFinished），⛔ 无编造行。
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "windows")
# ⚠️ 截图必须真实平台：offscreen 的字体库为空（实测 QFontDatabase.families()==0），
# 所有字形渲染成空心方框（tofu）——离屏只留给 e2e 文本判据用。
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

_t0 = time.perf_counter()
from app.bootstrap import preload_windows_icu  # noqa: E402

preload_windows_icu()
ICU_MS = (time.perf_counter() - _t0) * 1000.0

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from app.shell import MainWindow, _startup_checks  # noqa: E402
from app.splash import BOOT_STEPS, BootMilestones  # noqa: E402
from app.theme import apply_theme  # noqa: E402
from core.config.ui_config import load_ui  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent
LOCAL_DIR = pathlib.Path(r"D:\ZCode项目\_t12_普通档对照_仓外留存")   # 04 矩阵：含甲方名不入库
UI_PATH = pathlib.Path(__file__).resolve().parents[2] / "config" / "ui.yaml"


def pump(ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()


def set_size(win, w: int, h: int) -> None:
    """show() 之后再 resize（实测：show 前的 1920×1080 会被 WM 钳到屏幕内 1442×939；
    show 后可超屏——带鱼屏/全尺寸档位截图都靠它），并复核尺寸真的生效。"""
    win.resize(w, h)
    pump(300)
    if (win.width(), win.height()) != (w, h):
        win.resize(w, h)
        pump(500)
    print(f"  [尺寸] 请求 {w}×{h} ⇒ 实得 {win.width()}×{win.height()}"
          f"{'' if (win.width(), win.height()) == (w, h) else '  ✗ 未生效'}")


def sha256(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def grab(win, name: str, folder: pathlib.Path = OUT) -> None:
    target = folder / name
    folder.mkdir(parents=True, exist_ok=True)
    win.grab().save(str(target))
    print(f"  {target}  {win.width()}x{win.height()}  sha256={sha256(target)[:16]}…")


def wait_viewport(win, seconds: float = 20.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        pump(200)
        if win.boot.state("viewport") == "done":
            return True
    return False


def capture_loading(app, evidence) -> MainWindow:
    """抓「载入态」：构造后不等事件循环跑满（视口缓存热时会秒就绪），resize 后单轮
    processEvents 即拍——目标是真实的 4/5 里程碑＋登录三件套禁用态；竞态输了就换新窗重试。"""
    for attempt in (1, 2, 3):
        win = MainWindow(ui=evidence, boot=BootMilestones(BOOT_STEPS))
        win.show()
        pump(60)                            # 先让 show 落位（WM 只在首显时钳尺寸，之后 resize 可超屏）
        win.resize(1920, 1080)
        app.processEvents()
        win.boot.mark("icu", f"{ICU_MS:.0f} ms")
        _startup_checks(win.boot)           # 配置加载/点表校验/缓存目录：真实计时与读数
        app.processEvents()
        if not win.splash.is_ready():
            print(f"  [尺寸] 请求 1920×1080 ⇒ 实得 {win.width()}×{win.height()}"
                  f"（首显被 WM 钳到屏内——载入态判据看内容不看尺寸；三档尺寸图见 03/04/05）")
            grab(win, "01_载入态_evidence.png")
            print(f"  载入里程碑 {win.boot.done_count()}/{win.boot.total()}"
                  f"（视口={win.boot.state('viewport')}；登录三件套可用={win.splash._user.isEnabled()}）")
            return win
        print(f"  [重试 {attempt}] 视口加载太快，载入态已翻页——换新窗重拍")
        win.close()
    raise SystemExit("三次都输给视口加载速度，载入态截图未取得")


def main() -> int:
    app = QApplication([])
    apply_theme(app)
    evidence = load_ui(str(UI_PATH), profile="evidence")
    normal = load_ui(str(UI_PATH), profile="default")

    print("== 取证档：载入态→就绪态→主界面三档（全部 evidence profile）==")
    win = capture_loading(app, evidence)
    if not wait_viewport(win):
        print("  !! 视口 20 s 未就绪（截图中该行将保持待执行态——如实）")
    pump(300)
    set_size(win, 1920, 1080)
    grab(win, "02_登录页_evidence_1920x1080.png")
    win.enter_system()
    pump(400)
    print(f"  主界面档位={win.stage_host.kind()} fs={win.stage_host.spec().fs:g}")
    grab(win, "03_主界面_evidence_std_1920x1080.png")
    set_size(win, 2560, 1080)
    print(f"  主界面档位={win.stage_host.kind()} fs={win.stage_host.spec().fs:g}"
          f"（视口 --fs 已推 {win.stage_host.spec().fs:g}）")
    grab(win, "04_主界面_evidence_wide_2560x1080.png")
    set_size(win, 1366, 768)
    grab(win, "05_主界面_evidence_1366x768.png")
    win.return_to_login()
    set_size(win, 2560, 1080)
    print(f"  登录页在带鱼屏的档位={win.stage_host.kind()}（恒 16:9 出图，两侧留边 #0b0d10）")
    grab(win, "06_登录页_evidence_带鱼屏2560x1080.png")

    print("== 普通档对照（含甲方名 ⇒ 仓外留存，不入 evidence/）==")
    twin = MainWindow(ui=normal)
    twin.show()
    set_size(twin, 1920, 1080)
    twin.splash.set_ready_state(False)
    pump(200)
    grab(twin, "对照_登录页_普通档_1920x1080.png", folder=LOCAL_DIR)

    print("== 校验：取证画面无身份串、两档确有差异 ==")
    ev_texts = win.splash.identity_texts() + [win.statusbar._watermark.text(),
                                              win.statusbar._version.text()]
    nm_texts = twin.splash.identity_texts() + [twin.statusbar._watermark.text(),
                                               twin.statusbar._version.text()]
    leaks = [v for v in (normal.company, normal.company_en, normal.bid_no, normal.bidder_note,
                         normal.watermark, normal.version_text) if any(v in t for t in ev_texts)]
    print(f"  取证档身份串（普通档真值在取证画面中出现 {len(leaks)} 处"
          f"{'' if not leaks else ' → ' + '、'.join(leaks)}）")
    diff = [t for t in ev_texts if t not in nm_texts]
    print(f"  两档差异串 {len(diff)} 处：{diff[:3]}…")
    win.close()
    twin.close()
    ok = not leaks and diff
    print("结论：" + ("取证档剥离成立，截图齐备" if ok else "!! 剥离或差异校验未过"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
