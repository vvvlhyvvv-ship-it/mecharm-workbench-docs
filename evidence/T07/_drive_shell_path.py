"""evidence/T07/_drive_shell_path.py — **真窗体**端到端取证（完成标准①②③）。

跑法（worktree 根；须有显示环境：WebEngine 的 rAF 在隐藏页面里不跑，故 ⛔ 不能用 offscreen）：
  PYTHONPATH=. python evidence/T07/_drive_shell_path.py
会在桌面上弹出工作台窗体约 30 秒后自动关闭。样件由 `tests/cad_samples` 现造（自造基本体，
⛔ 非甲方模型／名称／尺寸），落 tempfile、不入库。脚本自身会在 QApplication 之前设
`QTWEBENGINE_CHROMIUM_FLAGS` 关掉 Chromium 的后台节流；fps 读数仍只在窗体**真活动**时有效
（被节流时只剩 1~3fps），故 D 节逐秒并列打印 `isActiveWindow`，该值为 False 的行读数作废。

取证内容：
  A 导入自造 box → 选工作模式 → 注 5 个点位
  B 生成路径 → 视口场景图里出现 4 条段折线（常态灰）＋4 个方向箭头，工具标记尚未上场
  C 越界点注入 → 两条段折线转 deny 红、步骤④⑤仍锁定、[▶播放]禁用（完成标准②）
  D 播放 → 视口 rAF 实测 fps 经 `perf.fps` 回到底部角标（完成标准①）；当前段转 accent 蓝、
    工具标记世界坐标逐帧移动 ⇒ `pose.update` 的列主序矩阵真的驱动了视口
  E 播完自动停钟（退回按需渲染），角标保留末次实测值
  F **硬核对**：暂停后按已知插值参数发帧，视口标记世界坐标 == core `tool_pose_in_model` 的平移分量
    （ratio=0 与 ratio=1 各一次）⇒「表格与视口一致」不靠肉眼看截图
  G 视口像素统计（辅证）——⚠️ 工件本体色 0x8a97a3 与 text_dim 0x9fb0bd 相近、pick.js 标号牌边框
    就是 accent 蓝，故像素数**含干扰**；硬结论一律以 F 的场景图数值为准。

⚠️ index.html **未**注册 path.js（注册行按卡片由指挥方合并时统一加）⇒ 本脚本在页面载入后动态注入
`_probe.mjs`（取证探针）与 `js/path.js`，等价于合并后的注册顺序 bridge→loader→pick→path。
⛔ 不改 index.html、不改 view/ 下任何交付件。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import time
from collections import Counter

import app  # noqa: F401  ICU 预载须在任何 PySide6.QtWidgets 之前
from PySide6.QtCore import QEventLoop, Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication, QPushButton

from app.pathctl import _lerp
from app.shell import MainWindow
from app.theme import TOKENS, apply_theme
from core.geometry.face_point import FacePoint
from core.path import tool_pose_in_model
from tests.cad_samples import box, write_step

OUT = pathlib.Path(__file__).resolve().parent
BOX_MM = (600.0, 400.0, 250.0)               # 自造基本体尺寸（占位行程 [0,1000] 内）
POINTS = ((0.0, 0.0, 0.0), (600.0, 0.0, 0.0), (600.0, 400.0, 0.0),
          (600.0, 400.0, 250.0), (0.0, 400.0, 250.0))
FAR_POINT = (5000.0, 0.0, 0.0)               # 越界注入（占位行程合计只到 3000 mm）
COLORS = {"idle_seg": TOKENS["text_dim"], "current_seg": TOKENS["accent"],
          "blocked_seg": TOKENS["deny"], "tool_marker": TOKENS["ok"],
          "model_body": "#8a97a3"}           # 末项＝loader.js 的零件常态色（列出以显式暴露干扰）


def pump(ms: int) -> None:
    """跑一段**真事件循环**（WebEngine 合成器与 rAF 都要它，processEvents 不够）。"""
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def js_eval(win, code: str, timeout_s: float = 3.0):
    """在页面里求值并取回结果（runJavaScript 的回调要事件循环转动才到）。"""
    got: dict = {}
    win.viewpane.page().runJavaScript(code, 0, lambda value: got.setdefault("v", value))
    deadline = time.time() + timeout_s
    while "v" not in got and time.time() < deadline:
        pump(50)
    return got.get("v")


def foremost(win, tries: int = 12) -> bool:
    """把取证窗体拉成**活动窗口**，并回读结果（Windows 前台锁会拒后台进程，故要重试若干轮）。

    fps 角标只有窗体真活动时才是有效读数：非活动时 Chromium 把 rAF 节流到约 1Hz（实测踩过）。
    返回 `win.isActiveWindow()`，⛔ 不得拿 raise_() 的调用本身当成功。
    """
    for _ in range(tries):
        win.raise_()
        win.activateWindow()
        pump(150)
        if win.isActiveWindow():
            return True
    return win.isActiveWindow()


def inject(win, uri: str, label: str) -> None:
    code = ("(function(){var s=document.createElement('script');s.type='module';s.src='"
            + uri + "';document.head.appendChild(s);return '" + label + " injected';})()")
    print(f"注入 {label}:", js_eval(win, code))
    pump(900)


def probe(win) -> dict:
    """读场景图探针；未就绪返回空表。"""
    raw = js_eval(win, "window.__probe ? JSON.stringify(window.__probe.dump()) : null")
    return json.loads(raw) if raw else {}


def lines_of(dump: dict) -> list[tuple]:
    """把段折线压成 (名字, 颜色, 是否可见) 表，便于逐行对。"""
    return [(item["name"], item["color"], item["visible"])
            for item in dump.get("items", []) if item["name"].startswith("path-seg-")]


def marker_of(dump: dict):
    for item in dump.get("items", []):
        if item["name"] == "tool-marker":
            return item
    return None


def steps_enabled(win) -> list[bool]:
    return [btn.isEnabled() for btn in win.stepbar.findChildren(QPushButton)]


def feed(win, coords) -> None:
    win.panel.step2.clear()
    for index, pos in enumerate(coords, start=1):
        win.panel.step2.add_face_point(FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0),
                                                 source_face=index))


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))


def pixel_counts(pixmap, tol: int = 26) -> tuple[dict, int, int]:
    """视口截图里各语义色的像素数（±tol 容差把抗锯齿边缘算进来；干扰源见模块 docstring G）。

    工具标记另给 `green_dominant` 判据：它是被光照着色后的绿（MeshStandardMaterial 受 loader 的
    半球光＋平行光），成品像素色与 token 色相差远超容差，按 token 色匹配恒为 0（实测踩过）。
    """
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    buffer = bytes(image.constBits())
    histogram = Counter(zip(buffer[2::4], buffer[1::4], buffer[0::4]))   # RGB32 小端＝B,G,R,A
    counts = {}
    for name, text in COLORS.items():
        want = hex_to_rgb(text)
        counts[name] = sum(total for (r, g, b), total in histogram.items()
                           if abs(r - want[0]) <= tol and abs(g - want[1]) <= tol
                           and abs(b - want[2]) <= tol)
    counts["green_dominant"] = sum(total for (r, g, b), total in histogram.items()
                                   if g > r + 30 and g > b + 30)
    return counts, image.width(), image.height()


def save(pixmap, name: str) -> pathlib.Path:
    path = OUT / name
    pixmap.save(str(path))
    return path


def wait_imported(win, timeout_s: float = 60.0) -> bool:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        pump(200)
        if win._last is not None:
            return True
    return False


def _lerped(seg, ratio: float) -> dict:
    """复刻壳侧插值（只为在 Python 里算出同一帧的期望位姿，⛔ 不是第二套实现）。"""
    return _lerp(seg.joints_start, seg.joints_end, ratio)


def main() -> int:
    # ⚠️ 取证前提：Chromium 默认对「非前台／被遮挡」页面把定时器与 rAF 节流到约 1Hz
    # （实测踩过：窗体可见且前台时 fps 角标 56~64，被遮挡时只剩 1~4，且 `--disable-backgrounding-
    # occluded-windows` 三件套只把 visibilityState 拉回 visible、帧率照旧被掐——Windows 上真正
    # 判遮挡的是 CalculateNativeWinOcclusion，必须连它一起关）。旗标须在 QtWebEngine 初始化
    # （即 QApplication／首个 QWebEngineView 构造）**之前**落到环境变量里。
    os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
        os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "") +
        " --disable-background-timer-throttling"
        " --disable-renderer-backgrounding"
        " --disable-backgrounding-occluded-windows"
        " --disable-features=CalculateNativeWinOcclusion").strip()
    tmp = tempfile.TemporaryDirectory(prefix="t07_")
    step_path = write_step(box(*BOX_MM), pathlib.Path(tmp.name) / "sample_box.step")
    print("自造样件:", step_path.name, "| 尺寸 mm:", BOX_MM, "| 字节:", step_path.stat().st_size)

    qapp = QApplication(sys.argv)
    apply_theme(qapp)
    win = MainWindow()
    win.resize(1280, 800)
    win.setWindowFlag(Qt.WindowStaysOnTopHint, True)   # 别的窗口盖不住它，配合旗标免 rAF 节流
    win.show()
    print("启动时窗体成为活动窗口:", foremost(win))
    pump(2500)
    print("视口载入后日志:", win.statusbar._log.text())
    inject(win, (OUT / "_probe.mjs").as_uri(), "_probe.mjs")
    inject(win, "js/path.js", "path.js")
    print("探针就绪:", bool(probe(win)))

    print("\n=== A. 导入自造基本体 ＋ 选定工作模式 ＋ 注 5 个点位 ===")
    win.panel.step1.start_import(str(step_path))
    print("导入完成:", wait_imported(win), "|", win.statusbar._log.text())
    print("is_brep:", win._last["asm"].is_brep, "| 零件数:", win._last["asm"].stats.get("parts"))
    win._on_mode_committed("多功能臂A")     # 直接调槽：本取证测 T07 接线，不测 T02 的模式确认弹窗
    feed(win, POINTS)
    print("点位数:", len(win.panel.step2.waypoints()))
    win._on_step_clicked(3)
    pump(300)

    print("\n=== B. 生成路径：视口出现 4 条常态段折线＋4 个箭头，标记未上场 ===")
    win.pathctl.generate()
    pump(900)
    print("汇总行:", win.panel.step3._summary_line.text())
    print("表格:", [[win.panel.step3._table.item(r, c).text() for c in range(4)]
                 for r in range(win.panel.step3._table.rowCount())])
    print("步骤条可用:", steps_enabled(win), "(期望 ①②③④⑤ 全 True)")
    dump = probe(win)
    print("场景图: 折线", dump.get("lines"), "| 箭头", dump.get("arrows"),
          "| 标记", dump.get("markers"), "| 可被拾取(须 False):", dump.get("any_pickable"))
    for row in lines_of(dump):
        print("   ", row)
    print("截图:", save(win.viewpane.view().grab(), "viewport_path_generated.png"))

    print("\n=== C. 越界点注入 ⇒ 视口红段＋步骤④⑤锁定（完成标准②）===")
    feed(win, [FAR_POINT if index == 2 else pos for index, pos in enumerate(POINTS)])
    win.pathctl.generate()
    pump(900)
    print("汇总行:", win.panel.step3._summary_line.text())
    print("红字行:", win.panel.step3._block_line.text())
    print("步骤条可用:", steps_enabled(win), "(期望 ④⑤ False)")
    print("[▶播放] 可用:", win.panel.step3._play.isEnabled(), "(期望 False)")
    dump = probe(win)
    for row in lines_of(dump):
        print("   ", row)
    print("截图:", save(win.viewpane.view().grab(), "viewport_path_blocked.png"))

    print("\n=== D. 恢复可达点位并播放：角标记实测 fps、当前段转蓝、标记逐帧移动 ===")
    feed(win, POINTS)
    win.pathctl.generate()
    pump(600)
    print("播放前角标:", win.statusbar._freq.text(), "(期望 --fps：还没转 rAF)")
    print("取样前窗体是否活动窗口（False ⇒ rAF 被节流、本行 fps 读数无效）:", foremost(win))
    win.pathctl.play()
    print("播放态：[▶]", win.panel.step3._play.isEnabled(), "[⏸]",
          win.panel.step3._pause.isEnabled(), "| 步骤②页可编辑", win.panel.step2.isEnabled())
    # ⚠️ 取样窗口内**不做任何 JS 往返**：runJavaScript 要占合成器一轮，插进来会把实测帧率压下去。
    # isActiveWindow() 是纯 Qt 读值，不发 JS，故可以逐秒并列打印（用来给 fps 读数定性）。
    for second in (1, 2, 3):
        pump(1000)
        print(f"  播放 {second}.0s 角标:", win.statusbar._freq.text(),
              "| 窗体活动:", win.isActiveWindow(), "| 当前段:", win.panel.step3._current)
    print("页面 visibilityState／hasFocus（判断 rAF 是否被节流）:",
          js_eval(win, "JSON.stringify([document.visibilityState, document.hasFocus()])"))
    early = probe(win)
    early_marker = marker_of(early)
    print("播放中 标记世界坐标:", early_marker and early_marker["world"],
          "| 标记可见:", early_marker and early_marker["visible"])
    print("播放中 段折线颜色:", lines_of(early))
    save(win.viewpane.view().grab(), "viewport_playing_early.png")
    pump(600)
    late = probe(win)
    late_marker = marker_of(late)
    print("再过 0.6s 标记世界坐标:", late_marker and late_marker["world"],
          "| 当前段:", win.panel.step3._current)
    print("标记已移动:", early_marker is not None and late_marker is not None
          and early_marker["world"] != late_marker["world"])
    print("再过 0.6s 角标:", win.statusbar._freq.text())
    print("截图:", save(win.viewpane.view().grab(), "viewport_playing_late.png"))

    print("\n=== E. 播完自动停钟（退回按需渲染）===")
    pump(6000)
    print("计时器仍在跑:", win.pathctl._timer.isActive(), "(期望 False)")
    print("末次角标:", win.statusbar._freq.text())
    print("末条日志:", win.statusbar._log.text())
    print("步骤②页恢复可编辑:", win.panel.step2.isEnabled())

    print("\n=== F. 硬核对：视口标记世界坐标 == core 位姿的平移分量（表格与视口一致）===")
    seg = win.pathctl._segments[1]
    for ratio in (0.0, 0.5, 1.0):
        win.pathctl._emit_pose(seg, ratio)
        pump(350)
        item = marker_of(probe(win))
        joints = _lerped(seg, ratio)
        want = tool_pose_in_model(joints, win.pathctl._chain, win.pathctl._frame)
        expected = [round(want[3], 6), round(want[7], 6), round(want[11], 6)]
        print(f"  段{seg.id} ratio={ratio}: 视口={item and item['world']} core={expected}"
              f" 一致={item is not None and item['world'] == expected}")

    print("\n=== G. 视口像素统计（辅证，干扰源见 docstring）===")
    counts, width, height = pixel_counts(win.viewpane.view().grab())
    print(f"  {width}x{height}:", counts)
    tmp.cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
