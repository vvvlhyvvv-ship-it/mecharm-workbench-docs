"""evidence/T08/_drive_step4.py — 离屏行为级取证：步骤④三态／三通道／⑤门禁／弹窗／文案审计。

跑法（worktree 根，输出重定向即 `step4_drive_log.txt`）：
  PYTHONIOENCODING=utf-8 PYTHONPATH=. QT_QPA_PLATFORM=offscreen \
    D:/Miniforge3/envs/mecharm/python.exe evidence/T08/_drive_step4.py > evidence/T08/step4_drive_log.txt 2>&1

⚠️ 离屏无中文字体，PNG 里中文呈豆腐块 ⇒ **以打印的数值为证**；视口报警条与高亮成图另见
`_drive_viewport.py`（真窗体）。本脚本用**真 MainWindow**（真导入链路／真下拉／真门禁），
只对桥做记录包裹、对确认弹窗做替身（⛔ 不改任何交付件）。
"""

from __future__ import annotations

import json
import sys

from _rig import BANNED, GAP_CASES, ICON, TWO_POINTS, Rig, g19_wording

RIG: Rig | None = None
SEEN: list[str] = []          # 全部上屏字符串（E 节文案审计的输入）


def collect(state: dict) -> None:
    """把一次读数里的字符串收进审计池（列表行按单元格收，布尔/数字列表跳过）。"""
    for value in state.values():
        if isinstance(value, str):
            SEEN.append(value)
        elif isinstance(value, (list, tuple)):
            SEEN.extend(cell for row in value if isinstance(row, (list, tuple))
                        for cell in row if isinstance(cell, str))


def s0_idle(rig: Rig) -> None:
    """A 节：还没校核时的两道门（④要有实体模型才可点；⑤在未校核态恒禁用并给人话原因）。"""
    rig.show("A1. 只生成路径、未导入实体模型：[开始校核] 禁用且给人话原因")
    rig.path(TWO_POINTS)
    state = rig.ui()
    rig.dump("未导入模型", state)
    collect(state)
    print("  期望：校核按钮 False｜⑤按钮 False｜就绪提示以「等待步骤①」开头")
    ok1 = (state["校核按钮可用"] is False and state["⑤按钮可用"] is False
           and state["就绪提示"].startswith("等待步骤①"))
    print(f"  判据: 校核按钮={state['校核按钮可用']}｜⑤按钮={state['⑤按钮可用']}"
          f"｜就绪提示={state['就绪提示']!r}｜{'对' if ok1 else '⛔ 不对'}")
    rig.show("A2. 导入自造实体模型后：[开始校核] 可用，⑤仍禁用（尚未校核）")
    print("  导入成功:", rig.obstacle(GAP_CASES[2][1]))
    rig.path(TWO_POINTS)
    state = rig.ui()
    rig.dump("已导入、未校核", state)
    collect(state)
    print("  期望：校核按钮 True｜⑤按钮 False｜⑤旁注＝尚未做碰撞校核｜就绪提示回空态句（⛔ 不留等待①）")
    ok2 = (state["校核按钮可用"] is True and state["⑤按钮可用"] is False
           and state["⑤旁注"].startswith("尚未做碰撞校核")
           and state["就绪提示"].startswith("尚未校核"))
    print(f"  判据: 校核按钮={state['校核按钮可用']}｜⑤按钮={state['⑤按钮可用']}"
          f"｜⑤旁注={state['⑤旁注']!r}｜就绪提示={state['就绪提示']!r}"
          f"｜{'对' if ok2 else '⛔ 不对'}")
    print("  门禁日志:", rig.rec.take("步骤⑤下发按钮") or
          f"（无新记录：门禁状态未变化，一直置灰；已捕获日志共 {len(rig.rec.rows)} 条）")


def s1_tristate(rig: Rig) -> None:
    """B 节：三态（相交／间隙 5 mm／间隙 500 mm）→ 🔴🟡🟢，每态贴 core 数字＋壳侧三通道。"""
    for label, x0, want in GAP_CASES:
        rig.show(f"B. 三态之「{label}」：自造 40 mm 立方障碍，X 下角 {x0} mm")
        imported, count, result = rig.run(x0)
        print(f"  导入成功: {imported}｜段数: {count}｜采样姿态: {result.sample_count}"
              f"｜指纹: {result.path_hash}")
        print(f"  结论: {result.verdict} {ICON[result.verdict]}｜{result.describe()}")
        print(f"  覆盖面: {result.coverage()}｜未建模轴: {result.unmodeled_axes}")
        print(f"  命中对数: {len(result.cases)}｜最近一条: "
              f"{[(c.seg_id, c.part_a, c.part_b, round(c.min_dist_mm, 3)) for c in result.cases[:1]]}")
        print(f"  臂侧代理盒: {[round(v, 3) for v in result.cases[0].box] if result.cases else None}"
              f"｜最近点: {[round(v, 3) for v in result.cases[0].point] if result.cases else None}")
        state = rig.ui()
        rig.dump("壳侧可见状态", state)
        collect(state)
        payload = rig.last("collision.show")
        text = json.dumps(payload, ensure_ascii=True)
        print(f"  桥 collision.show: level={payload['level']}｜cases={len(payload['cases'])}"
              f"｜全 ASCII={text.isascii()}")
        print(f"  桥首条 case: {payload['cases'][0] if payload['cases'] else None}")
        print(f"  判据: 期望 {want} {ICON[want]}｜实测 {result.verdict} {ICON[result.verdict]}"
              f"｜{'对' if result.verdict == want else '⛔ 不对'}")


def s2_channels(rig: Rig) -> None:
    """C 节：三通道齐（卡片文字＋emoji／列表着色＋行文案／桥载荷→视口）＋点击行定位。"""
    rig.show("C. 三通道与列表点击定位（干涉态）")
    rig.run(GAP_CASES[0][1])
    state = rig.ui()
    print("  通道①卡片:", state["卡片"], "｜文字色:", state["卡片文字色"])
    print("  通道②列表首行:", state["列表行"][0], "｜底色:", state["列表底色"][0])
    print("  通道③桥载荷 level:", rig.last("collision.show")["level"], "（视口成图见真窗体脚本）")
    print("  整句人话:", state["整句人话"])
    rig.win.panel.step4.case_clicked.emit(0)      # 真信号：等价于操作员点了列表第一行
    print("  点击行后 collision.focus 载荷:", rig.last("collision.focus"))
    print("  点击行后状态栏:", rig.win.statusbar._log.text())
    collect(rig.ui())


def s3_confirm_text(rig: Rig) -> None:
    """D 节：下发确认弹窗正文（G19 第 4 条：窗内复述覆盖面标注，由操作员确认）。"""
    rig.show("D. 🟡预警态直调 send_path()：弹窗正文须复述覆盖面标注")
    rig.run(GAP_CASES[1][1])
    captured: list[str] = []
    ctl = rig.win.checkctl
    ctl._ask_operator = lambda result, text: (captured.append(text), True)[1]   # 替身：点[确认下发]
    print("  send_path() →", ctl.send_path())
    print("  弹窗正文（逐行）:")
    for line in captured[0].splitlines():
        print("    |", line)
    SEEN.extend(captured[0].splitlines())
    print("  弹窗后状态栏:", rig.win.statusbar._log.text())
    print("  下发确认日志:", rig.rec.take("下发请求已确认")[-1:])


def s4_wording(rig: Rig) -> None:
    """E 节：上屏文案审计——禁用词扫描＋G19 措辞判据（含通过态）。"""
    rig.show("E. 上屏文案审计（右栏卡片／列表／旁注／状态栏／弹窗正文）")
    rig.run(GAP_CASES[2][1])
    state = rig.ui()
    collect(state)
    hits = sorted({w for text in SEEN for w in BANNED if w in text})
    print(f"  受审字符串条数: {len(SEEN)}｜禁用词命中: {hits or 'CLEAN'}")
    for label, x0, _want in GAP_CASES:
        rig.run(x0)
        card = rig.win.panel.step4._card.text()
        verdict = rig.win.checkctl._result.verdict
        print(f"  G19 措辞[{label}] {verdict}: 问题={g19_wording(card, verdict) or 'CLEAN'}"
              f"｜卡片={card}")
    print("  通过态覆盖面行:", rig.win.panel.step4._coverage.text())


def main() -> int:
    global RIG
    RIG = Rig()
    print("取证环境:", sys.version.split()[0], "｜工作模式:", RIG.win.workmode.current_mode(),
          "｜点位:", TWO_POINTS)
    for step in (s0_idle, s1_tristate, s2_channels, s3_confirm_text, s4_wording):
        step(RIG)
    RIG.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
