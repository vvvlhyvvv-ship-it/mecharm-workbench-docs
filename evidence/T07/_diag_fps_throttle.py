"""evidence/T07/_diag_fps_throttle.py — fps 节流的**排除法**诊断（⛔ 非交付件、⛔ 不放 view/）。

为什么单列：`_drive_shell_path.py` 的 fps 角标会被 Chromium 间歇掐到 1~7fps，而完成标准①要求
「角标记录实测 fps」⇒ 必须能当场区分「本单代码有缺陷」与「宿主帧调度被节流」，否则只能靠重跑
碰运气。本脚本三段对照（结论写进 `selftest_path_animation.md` 局限 2）：

  1 裸 `QWebEngineView`＋空页里的 rAF 计数 → 本机本底帧率（与 three.js／壳都无关）
  2 载入真 `view/index.html`（three.js＋WebGL）＋注入 `_probe.mjs` 的常驻心跳 → 页面级本底，
    顺带打印 WebGL 渲染器串（判断是否掉到软件渲染）
  3 真壳逐阶段读心跳（未导入／已导入／已生成／做过两次 `view.grab()`／播放中／已暂停），
    并在播放前给 `window.requestAnimationFrame` 套**计时壳** → 单帧回调耗时分布

判读口径：心跳高而角标低 ⇒ 壳侧时钟或 path.js 循环的问题（本单代码）；心跳与角标**同低** ⇒ 整页
帧调度被节流（宿主），该轮 fps 读数作废、⛔ 不得写进自测记录冒充「播放流畅」。

跑法（worktree 根；须有显示环境，⛔ 不能 offscreen）：
  PYTHONPATH=. python evidence/T07/_diag_fps_throttle.py
样件由 `tests/cad_samples` 现造（自造基本体，⛔ 非甲方模型／名称／尺寸），落 tempfile、不入库。
"""

from __future__ import annotations

import sys
import time

import app  # noqa: F401  ICU 预载须在任何 PySide6.QtWidgets 之前
from PySide6.QtCore import Qt
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

from _drive_shell_path import FAR_POINT, OUT, POINTS, Rig, feed, js_eval, probe, pump, wait_imported
from app.theme import apply_theme

ROOT = OUT.parent.parent
BARE_HTML = """<html><body><script>
let n = 0, t0 = performance.now(), last = 0;
function loop(now) {
  n += 1;
  if (now - t0 >= 1000) { last = Math.round(n * 1000 / (now - t0)); n = 0; t0 = now; }
  requestAnimationFrame(loop);
}
requestAnimationFrame(loop);
window.fps = () => last;
</script></body></html>"""

# 计时壳：path.js 每帧都重新取 window.requestAnimationFrame，故播放前套上即可量到它的回调耗时。
# ⚠️ 只量时间、不改调度（回调照旧同步执行），故不影响被测行为。
TIMING_HOOK = """
(function () {
  window.__cost = { durs: [] };
  const orig = window.requestAnimationFrame.bind(window);
  window.requestAnimationFrame = function (cb) {
    return orig(function (now) {
      const t0 = performance.now();
      try { cb(now); } finally { window.__cost.durs.push(performance.now() - t0); }
    });
  };
  return 'rAF 计时壳已套上';
})()"""

COST_STATS = """
(function () {
  const d = window.__cost.durs.slice().sort((a, b) => a - b);
  if (!d.length) return null;
  const pick = (q) => +d[Math.min(d.length - 1, Math.floor(d.length * q))].toFixed(2);
  return JSON.stringify({ n: d.length, min: +d[0].toFixed(2), p50: pick(0.5), p90: pick(0.9),
                          max: +d[d.length - 1].toFixed(2),
                          over100ms: d.filter((x) => x > 100).length });
})()"""

WEBGL_RENDERER = """
(function () {
  try {
    const gl = document.createElement('canvas').getContext('webgl2')
            || document.createElement('canvas').getContext('webgl');
    const dbg = gl.getExtension('WEBGL_debug_renderer_info');
    return gl.getParameter(dbg.UNMASKED_RENDERER_WEBGL);
  } catch (exc) { return String(exc); }
})()"""


INJECT_MODULE = ("(function(){var s=document.createElement('script');s.type='module';s.src='%s';"
                 "document.head.appendChild(s);return 1;})()")


def js_page(page, code: str, timeout_s: float = 3.0):
    """在给定 page 上求值并取回结果（裸 view 没有 `viewpane`，故不能直接用 `js_eval`）。"""
    got: dict = {}
    page.runJavaScript(code, 0, lambda value: got.setdefault("v", value))
    deadline = time.time() + timeout_s
    while "v" not in got and time.time() < deadline:
        pump(50)
    return got.get("v")


def foreground(widget, tries: int = 12) -> bool:
    """拉成活动窗口并**回读** `isActiveWindow()`（同 `_drive_shell_path.foremost`，兼容裸 view）。"""
    for _ in range(tries):
        widget.raise_()
        widget.activateWindow()
        pump(150)
        if widget.isActiveWindow():
            return True
    return widget.isActiveWindow()


def heart(widget, label: str) -> None:
    """读一次常驻裸 rAF 心跳，并列打印窗体活动状态（心跳低＋活动 True ⇒ 仍被节流）。"""
    page = widget.viewpane.page() if hasattr(widget, "viewpane") else widget.page()
    print(f"  [{label}] 心跳 fps:", js_page(page, "window.__probe.dump().heartbeat_fps"),
          "| 窗体活动:", widget.isActiveWindow())


def bare_view() -> None:
    """段 1：裸 QWebEngineView＋空页——环境本底帧率（不涉 three.js、不涉壳）。"""
    print("\n=== 段 1. 裸 QWebEngineView＋空页的 rAF 计数（环境本底）===")
    view = QWebEngineView()
    view.resize(640, 400)
    view.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    view.setHtml(BARE_HTML)
    view.show()
    print("  成为活动窗口:", foreground(view))
    pump(1500)
    for index in range(3):
        pump(1200)
        print(f"  第 {index + 1} 次 裸 rAF fps:", js_page(view.page(), "window.fps()"),
              "| 窗体活动:", view.isActiveWindow())
    view.close()


def real_page() -> None:
    """段 2：真 index.html（three.js＋WebGL）＋探针心跳——页面级本底＋渲染器串。"""
    print("\n=== 段 2. 真 index.html（three.js）里的常驻心跳（页面级本底）===")
    view = QWebEngineView()
    view.resize(1280, 800)
    view.setWindowFlag(Qt.WindowStaysOnTopHint, True)
    view.load((ROOT / "view" / "index.html").as_uri())
    view.show()
    print("  成为活动窗口:", foreground(view))
    pump(2500)
    js_page(view.page(), INJECT_MODULE % (OUT / "_probe.mjs").as_uri())
    pump(1200)
    for index in range(3):
        pump(1200)
        print(f"  第 {index + 1} 次 心跳 fps:",
              js_page(view.page(), "window.__probe.dump().heartbeat_fps"),
              "| 窗体活动:", view.isActiveWindow())
    print("  WebGL 渲染器（软件渲染会写 SwiftShader）:", js_page(view.page(), WEBGL_RENDERER))
    view.close()


def staged_shell() -> None:
    """段 3：真壳逐阶段心跳（复用取证装置 `Rig`：旗标／样件／窗体／注入都由它办）。"""
    print("\n=== 段 3. 真壳逐阶段心跳（含两次 view.grab()）＋播放中 rAF 回调耗时 ===")
    rig = Rig()
    win = rig.win
    try:
        heart(win, "刚注入，未导入")
        win.panel.step1.start_import(str(rig.step_path))
        print("  导入完成:", wait_imported(win))
        heart(win, "已导入实体")
        win._on_mode_committed("多功能臂A")
        feed(win, POINTS)
        win._on_step_clicked(3)
        pump(300)
        win.pathctl.generate()
        pump(900)
        heart(win, "已生成路径，未播放")
        _staged_grab_and_play(win)
    finally:
        rig.close()


def _staged_grab_and_play(win) -> None:
    """段 3 中段：两次 `view.grab()` 后再读心跳（验截图是否把合成器拖进节流）。"""
    win.viewpane.view().grab()
    pump(300)
    feed(win, [FAR_POINT if index == 2 else pos for index, pos in enumerate(POINTS)])
    win.pathctl.generate()
    pump(900)
    win.viewpane.view().grab()
    pump(300)
    heart(win, "越界生成＋做过两次 grab")
    feed(win, POINTS)
    win.pathctl.generate()
    pump(600)
    heart(win, "恢复可达，未播放")
    _staged_play(win)


def _staged_play(win) -> None:
    """段 3 后半：套计时壳→播放 3 s，并列打印角标／心跳／回调耗时分布→暂停后再读。"""
    print("  套计时壳:", js_eval(win, TIMING_HOOK))
    js_eval(win, "window.__cost.durs.length = 0;")
    print("  取样前成为活动窗口:", foreground(win))
    win.pathctl.play()
    for second in (1, 2, 3):
        pump(1000)
        print(f"  播放 {second}.0s 角标:", win.statusbar._freq.text(),
              "| 窗体活动:", win.isActiveWindow(), "| 当前段:", win.panel.step3._current)
    print("  播放中 rAF 回调耗时(ms):", js_eval(win, COST_STATS))
    heart(win, "播放中")
    print("  场景图活对象（探针）:", {key: probe(win).get(key)
                                    for key in ("lines", "arrows", "markers")})
    win.pathctl.pause()
    pump(800)
    heart(win, "已暂停")
    print("  判读：心跳与角标同低 ⇒ 宿主节流（该轮 fps 作废）；心跳高而角标低 ⇒ 本单代码问题。")


def main() -> int:
    qapp = QApplication(sys.argv)
    apply_theme(qapp)
    print("诊断目的：区分「fps 角标低」是宿主帧调度节流还是本单代码缺陷（判读口径见模块 docstring）")
    bare_view()
    real_page()
    staged_shell()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
