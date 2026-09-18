"""T13 起的**页签级判据**（``e2e_smoke.py`` 的预授权拆件，99 台账 L-2）。

为什么拆：``e2e_smoke.py`` 已 294/300，T13–T17 每单还要追加导航/页签判据 ⇒ 按 L-2 预授权把
页签导航判据拆到本件；手法同 ``e2e_faults.py``（装置共用 ``e2e_rig.py``，判据表与退出码仍只在
``e2e_smoke.py`` 一处 ⛔ 不另立入口）。T14–T17 各自只在本件追加本单判据，不动 smoke 的 A–H。

**T1–T6 在 G 与 H 之间跑**（T13 卡步骤 9）：此时链路在线、跟随中、校核结论在场 ⇒ 「在线时
8 轴有值」「芯片实测值」只有这个窗口判得出；**T7–T8 在 H 之后跑**：H2 的二次下发仍需有效
路径（⇒ 破坏性的工具行判据必须排后），H3 断线后链路离线（⇒ 离线回灰恰在此时判）。

判据读**操作员看得见的那一份**（按钮文字/禁用态/徽标原文/「—」占位），与 smoke 同一口径；
StepBar 薄壳判据（L-7）也在 T2：不删件、不进布局、旧引用全活。
"""

from __future__ import annotations

import re

from tools.comm_selftest_kit import check
from tools.e2e_rig import Rig

_NUM = re.compile(r"(-?[\d.]+)")          # 芯片/轴值里的实测数（「—」取不到即 None）
PENDING_MARK = "待回执"                     # yaml 真字段 axes[].pending 的徽标文案
UNREAD_MARK = "点表未收"                    # 无回读轴的如实标注（蓝图 §3.6 关键口径）
LATER_NOTE = "待后续版本"                   # 期 3 功能的禁用提示（Δ-7/Δ-9）
ENABLE_NOTE = "待契约回执"                  # 使能钮禁用提示（Δ-11，点表未收 enable_mask）


def _num(text: str) -> float | None:
    got = _NUM.search(text)
    return float(got.group(1)) if got else None


def section_t_online(rig: Rig, results: dict) -> None:
    """T1–T6：顶栏七区／页签导航与薄壳／徽标真值／芯片双灯／右栏双面板／22 轴在线（G 后 H 前）。"""
    print("\n=== T 顶栏·页签·右栏（T13 范式切换；在线段）===")
    _t1_topbar(rig, results)
    _t2_tabs(rig, results)
    _t3_badges(rig, results)
    _t4_chips(rig, results)
    _t5_panels(rig, results)
    _t6_axes_online(rig, results)


def _t1_topbar(rig: Rig, results: dict) -> None:
    bar, ui = rig.win.topbar, rig.win.ui
    texts = [b.text() for b in bar.findChildren(type(bar._import_btn))]
    user, name = rig.win.splash.login_values()
    print(f"  品牌区＝{bar._brand_name.text()}｜副标＝{bar._brand_sub.text()}")
    print(f"  顶栏按钮文字全集：{texts}")
    print(f"  使能钮 disabled={not bar._enable.isEnabled()} tooltip={bar._enable.toolTip()!r}｜"
          f"报警徽标={bar._alarm_badge.text()}｜用户盒＝{bar._user_name.text()}·{bar._user_no.text()}")
    check(results, "T1", (bar._brand_name.text() == ui.brand_name
                          and bar._brand_sub.text() == ui.brand_sub
                          and not any("手动" in t or "自动" in t or "21:9" in t for t in texts)
                          and bar._import_btn.isEnabled()
                          and not bar._assembly_btn.isEnabled()
                          and LATER_NOTE in bar._assembly_btn.toolTip()
                          and not bar._measure_btn.isEnabled()
                          and LATER_NOTE in bar._measure_btn.toolTip()
                          and bar._alarm_badge.text() == "—"
                          and not bar._enable.isEnabled()
                          and ENABLE_NOTE in bar._enable.toolTip()
                          and bar._user_name.text() == name and user in bar._user_no.text()),
          "顶栏七区：品牌读 ui.yaml；无模式组（Δ-1）无 21:9 预览（Δ-8）；装配体模式/测量禁用＋"
          "「待后续版本」（Δ-7）；报警徽标位留接口显示「—」（T16 接数）；使能恒禁用＋「待契约回执」"
          "（Δ-11）；用户盒姓名/工号＝登录页当前值")


def _t2_tabs(rig: Rig, results: dict) -> None:
    rig.tab("prog")
    prog_hosted = rig.win.tabshell.prog.isAncestorOf(rig.win.panel.step1)
    sim_hosted = rig.win.tabshell.sim.isAncestorOf(rig.win.panel.step5)
    rig.tab("sim")
    sim_front = rig.win.panel.step5.isVisible()
    rig.tab("tree")
    print(f"  页签切换：→prog→sim→{rig.win.tabshell.current()}；step1 归编程页签={prog_hosted}、"
          f"step5 归仿真页签={sim_hosted}、⑤页在前台={sim_front}")
    print(f"  StepBar 薄壳：可见={rig.win.stepbar.isVisible()}（应 False，不进布局）；"
          f"按钮数={len(rig.win.stepbar._buttons)}")
    check(results, "T2", (prog_hosted and sim_hosted and sim_front
                          and rig.win.tabshell.current() == "tree"
                          and not rig.win.stepbar.isVisible()),
          "导航职责移交页签：①–③页暂挂编程页签、④–⑤页暂挂仿真页签且能翻到前台；StepBar 退役为"
          "薄壳仍可实例化但不进任何布局（L-7：不 git rm，mark_completed/_completed 照常）")


def _t3_badges(rig: Rig, results: dict) -> None:
    asm = (rig.win._last or {}).get("asm")
    parts = len(list(asm.iter_parts())) if asm else 0
    want = {"tree": parts, "prog": len(rig.win.pathctl.segments()),
            "sim": len(rig.win.checkctl._result.cases) if rig.win.checkctl._result else 0}
    got = {k: rig.win.tabshell.badge_text(k) for k in want}
    print(f"  页签徽标：{got}（内核真值：{want}）")
    check(results, "T3", got == {k: str(v) for k, v in want.items()},
          "三页签徽标＝真实内核值（件数/段数/校核命中数，无则 0）——Δ-6 禁演示数字")


def _t4_chips(rig: Rig, results: dict) -> None:
    chips = rig.win.topbar.chips
    fps, hz, ms = (_num(chips._fps.text()), _num(chips._hz.text()), _num(chips._ms.text()))
    verdict = rig.win.checkctl._result.verdict if rig.win.checkctl._result else None
    lamp = rig.win.topbar.verdict.text()
    want = {"pass": "通过", "warn": "预警", "interfere": "不通过"}.get(verdict, "—")
    print(f"  芯片：fps={chips._fps.text()}｜Hz={chips._hz.text()}｜ms={chips._ms.text()}")
    print(f"  链路灯={rig.win.light.text()}｜判定灯={lamp}（校核结论={verdict}）")
    check(results, "T4", fps is not None and hz is not None and ms is not None
          and "实时" in rig.win.light.text() and "Hz" in rig.win.light.text() and want in lamp,
          "在线态三芯片全为实测值（渲染 fps＝桥 perf.fps／状态同步 Hz＝回读帧率／碰撞 ms＝上次校核"
          f"耗时，Δ-6 禁 58/10/2.4 演示值）；链路灯带实测 Hz；判定灯与结论一致（{want}）")


def _t5_panels(rig: Rig, results: dict) -> None:
    head = rig.win.workhead
    names = [m.name for m in rig.cfg.modes]
    rows = [r.text() for r in head.rows]
    marked = [t for t in rows if "★" in t]
    current = rig.win.workmode.current_mode() or ""
    print(f"  五臂行：{rows}（machine.yaml modes={names}）")
    print(f"  当前={current}；行程范围={head.travel_label.text()}；额定负载={head.load_label.text()}；"
          f"末端形式={head.tip_label.text()}；特写跟随可用={head.tcp_btn.isEnabled()}")
    check(results, "T5", (len(rows) == len(names)
                          and all(n in r for n, r in zip(names, rows))
                          and len(marked) == 1 and current in marked[0]
                          and head.travel_label.text() != "—"
                          and head.load_label.text() == "—" and head.tip_label.text() == "—"
                          and not head.tcp_btn.isEnabled()
                          and rig.win.joints.header_badge.text() == str(len(rig.cfg.axes))
                          and rig.win._right_pane.isVisible()),
          "右栏常驻双面板：五臂列表逐名来自 machine.yaml、★唯一且＝当前模式（G16 语义）；行程范围按"
          "axes 汇总为真值、额定负载/末端形式无字段恒「—」（§1-1）；特写跟随 TCP 禁用（Δ-7）；"
          "机构与关节数＝全表轴数；右栏不随页签切换")


def _t6_axes_online(rig: Rig, results: dict) -> None:
    joints = rig.win.joints
    readable_on = all(_num(joints.value_text(a)) is not None for a in joints.readable)
    dimmed = all(joints.value_text(a) == "—"
                 and UNREAD_MARK in joints.row_text(a) for a in joints.unreadable)
    pending = all(PENDING_MARK in joints.row_text(a) for a in joints.pending_axes)
    print(f"  有回读 {len(joints.readable)} 轴全有值={readable_on}；无回读 {len(joints.unreadable)} 轴"
          f"全「—」＋标注={dimmed}；pending 徽标 {len(joints.pending_axes)} 轴={pending}")
    print(f"  分组头：{[joints.group_title(i) for i in range(joints.group_count())]}")
    print(f"  软限位行：{joints.softline.text()}；点动区可用={joints.jog_btn.isEnabled()}")
    check(results, "T6", (readable_on and dimmed and pending
                          and joints.group_count() == 4
                          and joints.softline.text() != "—"
                          and not joints.jog_btn.isEnabled()
                          and LATER_NOTE in joints.jog_note.text()),
          "22 轴四组分组（共用机构/当前工作头/安装架/未建模机构，未建模判定复用 core 的"
          "unmodeled_axes）；在线时 8 轴有实测值、其余 14 轴恒「—」＋「点表未收」（⛔ 不因在线显 "
          "0.0）；pending 轴带「待回执」徽标；软限位只计有回读轴；轴点动整块禁用（Δ-7）")


def section_t_offline(rig: Rig, results: dict) -> None:
    """T7–T8：断线回灰＋离线占位／装配树工具行三钮（H 后：链路已被 H3 停掉、路径已无人消费）。"""
    print("\n=== T 离线占位＋装配树工具行（T13；H 后段）===")
    _t7_offline(rig, results)
    _t8_toolbar(rig, results)


def _t7_offline(rig: Rig, results: dict) -> None:
    from app.chips import StatChips
    joints, chips = rig.win.joints, rig.win.topbar.chips
    axes = list(joints.readable) + list(joints.unreadable)
    all_dash = all(joints.value_text(a) == "—" for a in axes)
    blank = StatChips()
    blank_dash = all("—" in lab.text() for lab in (blank._fps, blank._hz, blank._ms))
    print(f"  断线后：轴值全「—」={all_dash}；链路灯={rig.win.light.text()}；Hz 芯片={chips._hz.text()}")
    print(f"  全新 StatChips（离线初值）三芯片全「—」={blank_dash}")
    check(results, "T7", all_dash and rig.win.light.text().endswith("离线")
          and "—" in chips._hz.text() and blank_dash,
          "断线 ⇒ 轴值回「—」（⛔ 不留旧值假装在线）、链路灯「离线」、Hz 芯片回「—」；"
          "离线初值＝三芯片一律「—」（Δ-6；使能恒禁用已由 T1 判过，Δ-11）")


def _t8_toolbar(rig: Rig, results: dict) -> None:
    pane = rig.win.tabshell.tree_pane
    asked: list[str] = []
    pane._ask = lambda text: (asked.append(text), True)[1]
    initial_disabled = not pane._del_sel.isEnabled()

    def last_mesh_parts() -> int:
        for kind, payload in reversed(rig.sent):
            if kind == "mesh.load":
                return len(payload.get("parts", []))
        return -1

    def one_delete(button, label) -> list[str]:
        """导入 → 真点树节点 → 点删除钮 → 读树/视口/路径/点位的失效原文。"""
        ok = rig.import_box()
        rig.pump(200)
        rig.win.tabshell.tree.itemClicked.emit(rig.win.tabshell.tree.topLevelItem(0), 0)
        enabled = pane._del_sel.isEnabled()
        button.click()
        rig.pump(100)
        return [f"{label}: 导入={ok} 选中后删除选中可用={enabled}",
                f"{label}: 树顶层={rig.win.tabshell.tree.topLevelItemCount()} 视口件数={last_mesh_parts()}"
                f" 路径ready={rig.win.pathctl.ready()}"
                f" 点位={len(rig.win.panel.step2.waypoints())}"
                f" 删除选中复灰={not pane._del_sel.isEnabled()}"]

    lines = [f"初始（未选中）删除选中 disabled={initial_disabled}"]
    lines += one_delete(pane._del_sel, "删除选中")
    lines += one_delete(pane._del_grp, "删除整组")
    rig.import_box()
    pane._clear.click()
    rig.pump(100)
    badges = (rig.win.topbar._import_badge.text(), rig.win.tabshell.badge_text("tree"))
    lines.append(f"清空: 确认弹窗 {len(asked)} 次（原文：{asked[-1] if asked else '—'}）")
    for line in lines:
        print(f"  {line}")
    print(f"  清空后：视口件数={last_mesh_parts()}；徽标：三维导入={badges[0]} 装配树页签={badges[1]}")
    check(results, "T8", (initial_disabled
                          and all("选中后删除选中可用=True" in n for n in lines
                                  if "选中后删除选中可用" in n)
                          and last_mesh_parts() == 0 and rig.win.tabshell.tree.topLevelItemCount() == 0
                          and len(asked) >= 1 and not rig.win.pathctl.ready()
                          and badges == ("0", "0")),
          "工具行三钮：未选中时「删除选中」disabled（演示稿同位）；删除选中/整组后视口与树同步缩、"
          "路径与校核如实失效、按钮复灰；「清空全部模型」有二次确认且清后件数徽标归零"
          "（mesh.load {reset:true,parts:[]} 零新通道）")


TAB_ONLINE: tuple[tuple[str, str, object], ...] = (
    ("T1", "顶栏七区", section_t_online), ("T2", "页签导航·StepBar薄壳", None),
    ("T3", "页签徽标真值", None), ("T4", "数据芯片·双灯", None), ("T5", "右栏双面板", None),
    ("T6", "22轴分组·回读8/22", None),
)
TAB_OFFLINE: tuple[tuple[str, str, object], ...] = (
    ("T7", "离线占位·回灰", section_t_offline), ("T8", "装配树工具行", None),
)
