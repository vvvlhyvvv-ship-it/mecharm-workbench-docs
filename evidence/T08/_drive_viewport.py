"""evidence/T08/_drive_viewport.py — **真窗体**取证：视口报警条／干涉点标记／代理盒线框／定位高亮。

跑法（worktree 根，须有显示环境；输出重定向即 `viewport_log.txt`）：
  PYTHONIOENCODING=utf-8 PYTHONPATH=. \
    D:/Miniforge3/envs/mecharm/python.exe evidence/T08/_drive_viewport.py > evidence/T08/viewport_log.txt 2>&1

⚠️ 离屏测不了视口（`document.hidden=true`、rAF 不转、`grab()` 报 NATIVE_BROWSER_VIEWPORT_UNAVAILABLE，
T06/T07 已记录同一局限）⇒ 本脚本开真窗体、以**场景图数值**为硬结论，截图只作辅证。
⚠️ 本脚本每个工况导入的都是**两立方同一 STEP**（近处＝受测障碍，另加一个 FAR_X0 处的远处立方）：
只为把 loader 的整体取景撑宽 ⇒ 点击定位时「相机飞到」才测得出位移。只放一个障碍时整体取景与定位
取景是同一个盒子，相机一动不动，那条判据无法证伪（首版实测踩过：C 节相机前后完全相同）。远处立方
离路径 0~100 mm 极远 ⇒ ⛔ 不参与任何命中（三态结论与离屏脚本逐字一致，见各节实测）。
`view/index.html` **未**注册 collision.js（注册行按卡片由指挥方合并时统一加）⇒ 页面载入后动态注入
`_probe_collision.mjs`＋`js/collision.js`，等价于合并后的注册顺序 bridge→loader→pick→path→collision。
⛔ 全程未改 index.html、未改 `view/` 下任何既有交付件；样件为自造 40 mm 立方（⛔ 不含甲方数据）。
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

os.environ["QT_QPA_PLATFORM"] = "windows"      # 须在 import _rig 之前（它 setdefault offscreen）
# Windows 上真正判遮挡的是 CalculateNativeWinOcclusion：只关 backgrounding 三件套不够（T07 实测踩过）。
os.environ["QTWEBENGINE_CHROMIUM_FLAGS"] = (
    os.environ.get("QTWEBENGINE_CHROMIUM_FLAGS", "")
    + " --disable-background-timer-throttling --disable-renderer-backgrounding"
      " --disable-backgrounding-occluded-windows"
      " --disable-features=CalculateNativeWinOcclusion").strip()

from _rig import FAR_X0, GAP_CASES, Rig, pump  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent


def js_eval(win, code: str, timeout_s: float = 4.0):
    """在页面里求值并取回结果（runJavaScript 的回调要事件循环转动才到）。"""
    got: dict = {}
    win.viewpane.page().runJavaScript(code, 0, lambda value: got.setdefault("v", value))
    deadline = time.time() + timeout_s
    while "v" not in got and time.time() < deadline:
        pump(50)
    return got.get("v")


def foremost(win, tries: int = 12) -> bool:
    """拉成活动窗口并**回读** isActiveWindow()（⛔ 不拿 raise_() 的调用本身当成功）。"""
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
    print(f"  注入 {label}:", js_eval(win, code))
    pump(1200)


def probe(win) -> dict:
    raw = js_eval(win, "window.__probe_collision ? JSON.stringify(window.__probe_collision.dump()) : null")
    return json.loads(raw) if raw else {}


def save(win, name: str) -> str:
    path = OUT / name
    win.viewpane.view().grab().save(str(path))
    return f"{name}（{path.stat().st_size} 字节）"


def banner_of(dump: dict) -> None:
    banner = dump.get("banner")
    if not banner:
        print("  报警条: 未挂出（通过态或已撤下）")
        return
    print(f"  报警条: 显示={banner['display']}｜底色={banner['background']}｜字色={banner['color']}")
    print(f"  报警条文案: {banner['text']}")


def marks_of(dump: dict) -> None:
    print(f"  碰撞图层: 找到={dump.get('layerFound')}｜显示对象 {dump.get('markCount')} 个")
    for mark in dump.get("marks", [])[:4]:
        print("   ", mark)
    pickable = [m for m in dump.get("marks", []) if m.get("pickable")]
    print(f"  可被拾取的碰撞对象（须 0 个）: {len(pickable)}")
    print(f"  障碍侧发光部件: {dump.get('glowing')}")
    print(f"  相机位置: {dump.get('cameraPos')}")


class Drive:
    """真窗体装置：注入两个脚本后逐工况核对场景图（A~F 各一节方法，每节 ≤50 行）。"""

    def __init__(self) -> None:
        self.rig = Rig()
        self.win = self.rig.win
        self.win.resize(1280, 800)
        self.win.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.win.show()
        print("窗体成为活动窗口:", foremost(self.win))
        pump(2500)
        print("视口载入后状态栏:", self.win.statusbar._log.text())

    def a_inject(self) -> None:
        print("\n=== A. 注入探针＋collision.js（等价合并后的注册顺序）===")
        inject(self.win, (OUT / "_probe_collision.mjs").as_uri(), "_probe_collision.mjs")
        base = pathlib.Path(self.win.viewpane.page().url().toLocalFile()).parent.as_uri()
        inject(self.win, base + "/js/collision.js", "js/collision.js")
        print("  探针就绪:", bool(js_eval(self.win, "!!window.__probe_collision")))
        print("  分发链最外层已换成 collision.js:",
              js_eval(self.win, "String(window.__mecharm_dispatch).indexOf('collision.show') >= 0"))
        # 注入这一刻还没人往场景里 add 过东西 ⇒ 观察钩子尚未触发（scene 由 B 节真导入时捕获）。
        print("  场景已就绪（注入即读，期望 False；B 节导入模型后才被钩子观察到）:",
              probe(self.win).get("sceneReady"))

    def b_interfere(self) -> None:
        print("\n=== B. 干涉态：报警条红底＋干涉点标记＋臂侧代理盒线框 ===")
        self.rig.run(GAP_CASES[0][1], far=FAR_X0)
        pump(900)
        dump = probe(self.win)
        print("  场景已就绪（导入触发观察钩子）:", dump.get("sceneReady"))
        banner_of(dump)
        marks_of(dump)
        print("  壳侧结论:", self.win.panel.step4._card.text())
        print("  截图:", save(self.win, "viewport_interfere.png"))

    def c_focus(self) -> None:
        print("\n=== C. 点击列表首行：定位＋双方红色高亮＋相机飞到 ===")
        before = probe(self.win)
        self.win.panel.step4.case_clicked.emit(0)      # 真信号＝操作员点了列表第一行
        pump(900)
        dump = probe(self.win)
        moved = before.get("cameraPos") != dump.get("cameraPos")
        print("  相机位置 前:", before.get("cameraPos"), "→ 后:", dump.get("cameraPos"))
        print("  相机确实飞过去了（期望 True；场景里有远处立方撑宽整体取景才测得出）:", moved)
        print(f"  标记数: {before.get('markCount')} → {dump.get('markCount')}（定位不增删标记）")
        print("  定位后标记（首条应放大到 26.6，其余压暗到 0.35）:")
        for mark in dump.get("marks", [])[:4]:
            print("   ", mark)
        print("  障碍侧发光（应由 collision.js 转 hl.set 染成 deny 红 #b3261e）:", dump.get("glowing"))
        banner_of(dump)
        print("  截图:", save(self.win, "viewport_focus.png"))

    def d_warn(self) -> None:
        print("\n=== D. 预警态：报警条黄底＋两处标记（🟡允许进⑤）＋定位染 warn 黄（⛔ 不染红）===")
        self.rig.run(GAP_CASES[1][1], far=FAR_X0)
        pump(900)
        dump = probe(self.win)
        banner_of(dump)
        marks_of(dump)
        print("  壳侧结论:", self.win.panel.step4._card.text())
        print("  ⑤按钮可用:", self.win.panel.send_btn.isEnabled(), "(期望 True：预警可进⑤)")
        self.win.panel.step4.case_clicked.emit(0)      # 预警态也点一行：高亮须随三态＝warn 黄
        pump(900)
        dump = probe(self.win)
        print("  定位后障碍侧发光（期望 #d9a520 黄，⛔ 不是 deny 红）:", dump.get("glowing"))
        print("  定位后相机:", dump.get("cameraPos"))
        print("  截图（定位后近景；整体取景里两立方相距 4 m，远景几乎空白）:",
              save(self.win, "viewport_warn.png"))

    def e_pass(self) -> None:
        print("\n=== E. 通过态：报警条撤下、标记清空（G19：视口⛔ 不显示「通过」字样）===")
        self.rig.run(GAP_CASES[2][1], far=FAR_X0)
        pump(900)
        dump = probe(self.win)
        banner_of(dump)
        marks_of(dump)
        print("  壳侧结论:", self.win.panel.step4._card.text())
        print("  截图:", save(self.win, "viewport_pass.png"))

    def f_invalidate(self) -> None:
        print("\n=== F. 干涉态下改点位（F3 作废链路）：报警条与标记一并撤下 ===")
        self.rig.run(GAP_CASES[0][1], far=FAR_X0)
        pump(900)
        print("  作废前:")
        banner_of(probe(self.win))
        print("  作废前标记数:", probe(self.win).get("markCount"))
        self.win._on_invalidate_results()              # F3 的槽：真链路
        pump(900)
        dump = probe(self.win)
        banner_of(dump)
        print("  作废后标记数:", dump.get("markCount"), "(期望 0)")
        print("  壳侧卡片:", self.win.panel.step4._card.text())
        print("  ⑤旁注:", self.win.panel.send_note.text())
        print("  截图:", save(self.win, "viewport_invalidated.png"))

    def close(self) -> None:
        self.rig.close()


def main() -> int:
    drive = Drive()
    print("取证环境:", sys.version.split()[0], "｜工作模式:", drive.win.workmode.current_mode())
    for step in (drive.a_inject, drive.b_interfere, drive.c_focus, drive.d_warn,
                 drive.e_pass, drive.f_invalidate):
        step()
    drive.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
