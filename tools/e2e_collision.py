"""tools/e2e_collision —— T16 干涉体系判据（standalone；99 台账 2026-09-19 预声明拆件）。

为什么独立成件：``e2e_tabs.py`` 300/300 冻结、``e2e_smoke.py`` 冻结拼接（L-2）⇒ 本单判据落本件：
**自起 Rig**（``e2e_rig.Rig`` 只 import 不改），rc=0＝全 PASS。读**操作员看得见的那份原文**（同
smoke 口径）：模态、清单、设备列、树红标、顶栏徽标都是屏上元素；视口侧经 ``runJavaScript`` 查 DOM。

判据（对 T16 卡完成标准逐条）：
  C1 无干涉场景（⚠ 最易被跳过）：模态不弹、③清单「—」、涉事设备列全「—」、顶栏徽标 0、树无 ⚠
     红标｜C2 干涉态：阻断式模态弹出（红头＋干涉对表＋KPI 不通过）、清单归并行＋「需调整示教点或
     路径」明细、设备列真值、树红标与清单同时在场、徽标＝活动干涉组数｜C3 模态行为：行点击→
     ``collision.focus`` 载荷发出；「知道了（关闭）」→ 模态关但**禁发状态不变**（双阻断独立在场）
  C4 视口：``collision.show``（deny）→ 脉冲圈与高亮条 DOM 在场、``--motion`` 接线默认开；
     ``--motion=0``（蓝图 §1-11）⇒ 圈退化为**静态红环仍在场**｜C5 fps：脉冲开启前后两实测值
     （offscreen rAF 节流噪声大 ⇒ 宽阈 ≥0.4；真平台对照值由 evidence/T16/_shots.py 另录）。

场景：C1＝``e2e_rig`` 自带障碍（终点前 8 mm ⇒ 🟡 预警、无 dist≤0）；PREP 起＝自造立方**压在路径
正中**（X 30–70 ⇒ dist≤0 ⇒ 🔴 干涉）。样件一律自造基本体 ⛔ 禁甲方模型／名称。
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox  # noqa: E402
from OCC.Core.gp import gp_Pnt  # noqa: E402
from PySide6.QtWidgets import QLabel, QTableWidget  # noqa: E402

from core.geometry.face_point import FacePoint  # noqa: E402
from tests.cad_samples import write_step  # noqa: E402
from tools.comm_selftest_kit import check, force_utf8_stdout, recording  # noqa: E402
from tools.e2e_rig import THREE_POINTS, Rig  # noqa: E402

OUTPUT = pathlib.Path("evidence/T16/e2e_collision.txt")
CLASH_AT = (30.0, -20.0, -20.0)   # 自造干涉立方：X 30–70 正压在 0→200 路径上（⛔ 非甲方模型/尺寸）
FAR_AT = (903.0, -20.0, -20.0)    # 自造远障碍：间隙 500 mm ≫ 安全值 ⇒ 校核 0 涉事记录（C1 对照）
CLASH_STEM = "clash_block"        # 文件名（零件名以解析产物为准，见 _import_box_at 注）
FPS_FLOOR = 0.4                   # 脉冲后/前 fps 比下限（offscreen 宽阈；真平台值 _shots 另录）
PLAY_MS = 1700                    # 播放观察窗（≥ path.js 的 fps 统计窗）


def _pump_ms(rig: Rig, ms: float) -> None:
    rig.pump(ms)


def _js(rig: Rig, expr: str, sink: list) -> None:
    """视口内求值（runJavaScript 异步回调）；失败回调 None ⇒ 判据按空处理不假绿。"""
    rig.win.viewpane.page().runJavaScript(expr, lambda r: sink.append(r))
    _pump_ms(rig, 500)


def _tree_marks(rig: Rig) -> list[str]:
    """装配树里的 ⚠ 红标行原文（操作员看得见的那份）。"""
    tree = rig.win.tabshell.tree
    stack = [tree.topLevelItem(i) for i in range(tree.topLevelItemCount())]
    out = []
    while stack:
        item = stack.pop()
        stack.extend(item.child(i) for i in range(item.childCount()))
        if item.text(0).startswith("⚠"):
            out.append(item.text(0))
    return out


def _import_box_at(rig: Rig, at: tuple, name: str) -> bool:
    """自造立方走**真导入链路**（同 rig.import_box 手法，只换位置）。⚠️ 零件名由 STEP 解析器给
    （内部结构 ⇒ 「零件_N」命名，非文件名）⇒ 判据一律从 ``result.cases[].part_b`` 动态取。"""
    path = pathlib.Path(rig.tmp.name) / f"{name}.step"
    with contextlib.redirect_stdout(io.StringIO()):
        write_step(BRepPrimAPI_MakeBox(gp_Pnt(*at), 40.0, 40.0, 40.0).Shape(), path)
    rig.win._last = None
    rig.win.panel.step1.start_import(str(path))
    return rig.wait(lambda: rig.win._last is not None)


def _re_pick(rig: Rig) -> None:
    """导入换模型后点位/路径已作废 ⇒ 重摆三点、重新生成与校核（真控制器路径）。"""
    rig.win.panel.step2.clear()
    for index, pos in enumerate(THREE_POINTS, start=1):
        rig.win.panel.step2.add_face_point(
            FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
    rig.win.pathctl.generate()
    rig.win.checkctl.run_check()
    _pump_ms(rig, 250)


def _play_and_read_fps(rig: Rig) -> float | None:
    """播放一段并从底栏角标读实测 fps（path.js rAF → perf.fps → statusbar 原文）。"""
    rig.win.pathctl.play()
    _pump_ms(rig, PLAY_MS)
    value = rig.fps()
    rig.win.pathctl.pause()
    _pump_ms(rig, 150)
    return value


def section_no_clash(rig: Rig, results: dict, durations: dict) -> None:
    """C1：无干涉场景（障碍远离路径 ⇒ 0 涉事记录）——模态不弹、清单/设备列「—」、徽标 0、无红标。"""
    assert _import_box_at(rig, FAR_AT, "far_block")   # X 903 起 ⇒ 间隙 500 mm ≫ 安全值 ⇒ 未检出
    rig.pick()
    rig.win.pathctl.generate()
    rig.win.checkctl.run_check()
    _pump_ms(rig, 300)
    tab = rig.win.tabshell.sim
    rows = tab._table.rowCount()
    devices = {tab._table.item(r, 2).text() for r in range(rows)} if rows else {"（无行）"}
    modal = rig.win.checkctl._alarm
    badge = rig.win.topbar._alarm_badge.text()
    marks = _tree_marks(rig)
    print(f"\n=== C1 无干涉场景（预警、无 dist≤0）===")
    print(f"  模态弹过={modal is not None}｜清单「{tab._clash.text()[:18]}」｜设备列{devices}｜"
          f"徽标={badge}｜树红标={marks}")
    check(results, "C1", modal is None and tab._clash.text() == "—" and devices == {"—"}
          and badge == "0" and not marks,
          "无干涉：阻断式模态不弹、干涉清单「—」、涉事设备列全「—」、顶栏报警徽标 0、树无红标"
          "（完成标准「最易被跳过」条）")
    durations["fps_before"] = _play_and_read_fps(rig)   # 无脉冲基线（C5 用）


def section_clash_ui(rig: Rig, results: dict, durations: dict) -> None:
    """C2：干涉态——模态弹出（红头/干涉对/KPI 不通过）＋清单归并＋设备列＋树红标＋徽标＝组数。"""
    assert _import_box_at(rig, CLASH_AT, CLASH_STEM)
    _re_pick(rig)
    result = rig.win.checkctl._result
    part_b = result.cases[0].part_b if result.cases else ""   # 障碍名以解析产物为准（⛔ 不写死）
    tab, modal = rig.win.tabshell.sim, rig.win.checkctl._alarm
    heads = [l.text() for l in modal.findChildren(QLabel)] if modal else []
    tables = modal.findChildren(QTableWidget) if modal else []
    badge = rig.win.topbar._alarm_badge.text()
    rows = tab._table.rowCount()
    devices = {tab._table.item(r, 2).text() for r in range(rows)} if rows else set()
    marks = _tree_marks(rig)
    verdict_ok = result is not None and result.verdict == "interfere"
    print(f"\n=== C2 干涉态呈现 ===")
    print(f"  verdict={getattr(result, 'verdict', None)}｜模态可见={bool(modal and modal.isVisible())}"
          f"｜红头在场={any('检测到干涉' in t for t in heads)}｜干涉对表 {sum(t.rowCount() for t in tables)} 行｜"
          f"清单「{tab._clash.text()[:40]}…」｜设备列{devices}｜树红标={marks}｜徽标={badge}")
    check(results, "C2", (verdict_ok and modal is not None and modal.isVisible()
          and any("检测到干涉" in t for t in heads) and tables and tables[0].rowCount() == len(result.cases)
          and any("不通过" in t for t in heads)
          and "干涉对" in tab._clash.text() and part_b in tab._clash.text()
          and "需调整示教点或路径" in tab._clash.text()
          and part_b in devices and len(marks) >= 1 and any(part_b in m for m in marks)
          and badge == "1"),
          "干涉态：模态弹出（红头＋干涉对表＝cases 数＋KPI 不通过）；③清单归并行＋干涉对明细含"
          "「需调整示教点或路径」；涉事设备列真值；树红标与清单同时在场（三通道）；徽标＝活动干涉组数")
    durations["fps_after"] = _play_and_read_fps(rig)    # 有脉冲读数（C5 对照）


def section_modal_gate(rig: Rig, results: dict, durations: dict) -> None:
    """C3：模态行为——行点击→collision.focus；「知道了（关闭）」→ 关但禁发状态不变。"""
    modal = rig.win.checkctl._alarm
    if modal is None or not modal.isVisible():
        check(results, "C3", False, "模态不在场（C2 未通过或已被关），C3 无从做起")
        return
    modal._locate(1, 0) if modal._result and len(modal._result.cases) > 1 else modal._locate(0, 0)
    _pump_ms(rig, 250)
    focused = [p for t, p in rig.sent if t == "collision.focus"]
    gate_before = rig.win.checkctl.ready()
    send_enabled = rig.win.panel.send_btn.isEnabled()
    close = [b for b in modal.findChildren(type(modal.findChildren(QLabel)[0]))
             if b.text() == "知道了（关闭）"] if False else None   # 占位：按钮经遍历取（下行真实现）
    from PySide6.QtWidgets import QPushButton
    buttons = {b.text(): b for b in modal.findChildren(QPushButton)}
    buttons.get("知道了（关闭）").click()
    _pump_ms(rig, 300)
    closed = not modal.isVisible()
    gate_after = rig.win.checkctl.ready()
    print(f"\n=== C3 模态行为 ===")
    print(f"  行点击→collision.focus {len(focused)} 次｜关闭前 门禁可发={gate_before} 发送钮={send_enabled}｜"
          f"关闭={closed}｜关闭后 门禁可发={gate_after}")
    check(results, "C3", bool(focused) and closed and gate_before is False and gate_after is False
          and send_enabled is False,
          "模态行点击 ⇒ collision.focus 视口定位载荷发出；「知道了（关闭）」⇒ 模态关但禁发双阻断独立"
          "在场（ready=False、发送钮禁用不变——模态只呈现、不裁决）")


def section_viewport(rig: Rig, results: dict, durations: dict) -> None:
    """C4：视口侧——deny 载荷 → 脉冲圈＋高亮条 DOM 在场；--motion=0 ⇒ 静态红环仍在场（§1-11）。"""
    rig.win.bridge.call_view("collision.show", {"level": "deny", "cases": [
        {"seg": int(c.seg_id), "arm": c.part_a, "obs": rig.win.checkctl._mesh_ids.get(c.part_b, 0),
         "dist": round(c.min_dist_mm, 6), "point": [float(v) for v in c.point], "box": []}
        for c in rig.win.checkctl._result.cases]})
    _pump_ms(rig, 400)
    pulses: list = []
    _js(rig, "document.querySelectorAll('.coll-pulse').length", pulses)
    motion: list = []
    _js(rig, "getComputedStyle(document.documentElement).getPropertyValue('--motion').trim()", motion)
    bar: list = []
    _js(rig, "(document.getElementById('scene-host').textContent || '').includes('干涉高亮')", bar)
    rig.win.viewpane.page().runJavaScript(
        "document.documentElement.style.setProperty('--motion','0'); 'ok'")
    _pump_ms(rig, 300)
    rig.win.bridge.call_view("collision.show", {"level": "deny", "cases": [
        {"seg": int(c.seg_id), "arm": c.part_a, "obs": rig.win.checkctl._mesh_ids.get(c.part_b, 0),
         "dist": round(c.min_dist_mm, 6), "point": [float(v) for v in c.point], "box": []}
        for c in rig.win.checkctl._result.cases]})
    _pump_ms(rig, 400)
    statics: list = []
    _js(rig, "document.querySelectorAll('.coll-pulse.static').length", statics)
    alls: list = []
    _js(rig, "document.querySelectorAll('.coll-pulse').length", alls)
    rig.win.viewpane.page().runJavaScript(
        "document.documentElement.style.setProperty('--motion','1'); 'ok'")   # 还原（勿污染后续节）
    _pump_ms(rig, 200)
    print(f"\n=== C4 视口脉冲圈与高亮条 ===")
    print(f"  脉冲圈 {pulses} 个｜--motion={motion}｜高亮条在场={bar}｜关动效后 静态红环={statics}／全部={alls}")
    check(results, "C4", (pulses and pulses[0] and pulses[0] >= 1 and motion and motion[0] == "1"
          and bar and bar[0] is True and statics and statics[0] >= 1 and alls and alls[0] == statics[0]),
          "deny 载荷 ⇒ 红色脉冲圈 ≥1 且「干涉高亮」条在场（蓝图 §3.5）；--motion 接线默认开（=1）；"
          "--motion=0 ⇒ 动画停、圈退化为静态红环仍在场（§1-11 信息不丢）")


def section_fps(rig: Rig, results: dict, durations: dict) -> None:
    """C5：脉冲开启前后 fps 两实测值（offscreen 宽阈；真平台对照由 evidence/T16/_shots.py 另录）。"""
    before, after = durations.get("fps_before"), durations.get("fps_after")
    ratio = round((after or 0) / before, 3) if before else 0.0
    print(f"\n=== C5 fps 对照（脉冲前 → 脉冲后）===")
    print(f"  脉冲前 {before} fps → 脉冲后 {after} fps（比 {ratio}；阈值 ≥{FPS_FLOOR}，offscreen 宽阈）")
    check(results, "C5", bool(before) and bool(after) and after / before >= FPS_FLOOR,
          f"脉冲圈开启后 fps 实测 {before}→{after}（比 {ratio}）不明显下降——脉冲走 DOM/CSS 合成层、"
          "不进 three 渲染循环（fps 芯片读数＝path.js rAF 实测）")


def main(argv=None) -> int:
    args = parse(argv)
    force_utf8_stdout()
    results: dict[str, bool] = {}
    durations: dict[str, object] = {}
    with recording(None if args.no_save else OUTPUT):
        print(f"T16 干涉体系判据 · python {sys.version.split()[0]} · "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"取证物 {OUTPUT}｜只跑 {args.only or '全部节'}")
        rig = Rig()
        try:
            for key, body in PLAN:
                if args.only and not key.upper().startswith(args.only.upper()):
                    continue
                if body is not None:
                    from tools.comm_selftest_kit import guarded
                    guarded(results, key, lambda run=body: run(rig, results, durations))
            (rig.tab("sim"), _pump_ms(rig, 200))
        finally:
            rig.close()
        bad = [key for key, ok in results.items() if not ok]
        picked = [key for key, _b in PLAN if not args.only or key.upper().startswith(args.only.upper())]
        missing = [key for key in picked if key not in results]
        print("\n=== 结论 ===")
        for key, _body in PLAN:
            if key in results:
                print(f"  {key:<3} {'PASS' if results[key] else 'FAIL'}")
        print(f"  未跑到：{('、'.join(missing)) if missing else '无'}｜共 {len(results)} 条："
              f"{len(results) - len(bad)} PASS、{len(bad)} FAIL")
        print("结论：" + ("全链路走通" if not bad and not missing else "有判据未过，见上文原文"))
    return 0 if not bad and not missing else 1


def parse(argv=None):
    parser = argparse.ArgumentParser(description="T16 干涉体系判据（离屏、不连 PLC）")
    parser.add_argument("--only", default="", help="只跑这些节（前缀匹配，如 C4）")
    parser.add_argument("--no-save", action="store_true", help="不落 evidence/T16/e2e_collision.txt")
    return parser.parse_args(argv)


# (判据号, 入口)；PREP＝干涉障碍导入＋重取点生成校核（在 C2 入口内完成，此处哨兵留位）
PLAN = (("C1", section_no_clash), ("C2", section_clash_ui),
        ("C3", section_modal_gate), ("C4", section_viewport), ("C5", section_fps))

if __name__ == "__main__":
    raise SystemExit(main())
