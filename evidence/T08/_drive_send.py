"""evidence/T08/_drive_send.py — 离屏行为级取证：禁发双阻断／指纹失配／耗时／G19 覆盖面／包络承重。

跑法（worktree 根，输出重定向即 `send_gate_log.txt`）：
  PYTHONIOENCODING=utf-8 PYTHONPATH=. QT_QPA_PLATFORM=offscreen \
    D:/Miniforge3/envs/mecharm/python.exe evidence/T08/_drive_send.py > evidence/T08/send_gate_log.txt 2>&1

⚠️ 两处**取证替身**（⛔ 不改任何交付件，只在本进程内换实例属性）：
  ① 确认弹窗 `checkctl._ask_operator` → 直接给"点了[取消]/[确认下发]"的结果（离屏不能交互）；
  ② G 节把 `pathctl._segments` 就地换掉**且不发 changed 信号**＝故障注入，用来证明双阻断第②条
    的指纹复判能独立拦住（第①条的作废链路已被绕过时仍然拒发）；K 节把 `pathctl.kinematics`
    换成包络 12 mm 的配置副本（⛔ `machine.yaml` 全程未改，用 `dataclasses.replace` 造内存副本）。
"""

from __future__ import annotations

import dataclasses
import sys

from _rig import GAP_CASES, ICON, LONG_POINTS, TWO_POINTS, Rig, pump

from core.collision import check, mode_axes, path_fingerprint, unmodeled_axes
from core.config import REPO_ROOT, load_machine
from core.geometry.face_point import Waypoint
from core.path import gen_path
from tests.test_collision import ONE, PATH, _plate, _scene   # 与 pytest 用例同一套合成配置 ⇒ 口径一致


def s0_refuse_interfere(rig: Rig) -> None:
    """F 节：干涉态**直调** `send_path()`（等价 DevTools 绕过按钮）→ 拒发且 warning 留痕。"""
    rig.show("F. 干涉态直调 send_path()：按钮已置灰，函数入口再独立判一次")
    rig.run(GAP_CASES[0][1])
    ctl = rig.win.checkctl
    print("  ⑤按钮可用:", rig.win.panel.send_btn.isEnabled(), "(期望 False＝双阻断第①条)")
    print("  ⑤旁注:", rig.win.panel.send_note.text())
    print("  直调 send_path() →", ctl.send_path(), "(期望 False＝双阻断第②条)")
    print("  拒发日志:", rig.rec.take("下发被拒")[-1:])
    print("  状态栏:", rig.win.statusbar._log.text())


def s1_stale_result(rig: Rig) -> None:
    """G 节：改点位后旧结论失效——①走真作废链路；②绕过作废链路时由指纹复判兜住。"""
    rig.show("G1. 改一个点位（真链路）：旧校核结果当场作废，⑤恒禁用")
    rig.run(GAP_CASES[2][1])
    print("  改点前 ⑤按钮:", rig.win.panel.send_btn.isEnabled(), "｜指纹:",
          rig.win.checkctl._result.path_hash)
    rig.path(((0.0, 0.0, 0.0), (120.0, 0.0, 0.0)))      # 终点从 100 改到 120＝改了一个点位
    print("  改点后 ⑤按钮:", rig.win.panel.send_btn.isEnabled(), "｜旁注:",
          rig.win.panel.send_note.text())
    print("  改点后 send_path() →", rig.win.checkctl.send_path())
    print("  作废与拒发日志:", rig.rec.take("步骤⑤下发按钮")[-1:], rig.rec.take("下发被拒")[-1:])
    print("  状态栏:", rig.win.statusbar._log.text())
    rig.show("G2. 故障注入：绕过作废信号直接换段序列 ⇒ 指纹失配必须独立拒发")
    rig.run(GAP_CASES[2][1])
    ctl, pathctl = rig.win.checkctl, rig.win.pathctl
    print("  校核时指纹:", ctl._result.path_hash)
    cfg, chain, frame = pathctl.kinematics()
    pathctl._segments = gen_path(                      # 就地换路径、⛔ 不发 changed（＝链路失效）
        [Waypoint(i, f"P{i}", (50.0 * i, 0.0, 0.0), (0.0, 0.0, 1.0), i) for i in (1, 2)],
        cfg, chain, frame)
    print("  换段后指纹:", path_fingerprint(pathctl.segments()), "｜⑤按钮仍显示:",
          rig.win.panel.send_btn.isEnabled(), "(按钮读的是旧状态)")
    print("  直调 send_path() →", ctl.send_path(), "(期望 False：入口重算指纹 ⇒ 失配拒发)")
    print("  拒发日志:", rig.rec.take("下发被拒")[-1:])
    print("  旁注:", rig.win.panel.send_note.text())


def s2_operator_choice(rig: Rig) -> None:
    """H 节：可下发态的弹窗两条出口——[取消] 不发＋留痕、[确认下发] 才发。"""
    rig.show("H. 通过态 send_path()：弹窗默认按钮＝[取消]，两条出口各留日志")
    rig.run(GAP_CASES[2][1])
    ctl = rig.win.checkctl
    ctl._ask_operator = lambda result, text: False       # 替身：操作员点了[取消]
    print("  点[取消] → send_path()", ctl.send_path(), "｜日志:", rig.rec.take("下发已取消")[-1:])
    ctl._ask_operator = lambda result, text: True        # 替身：操作员点了[确认下发]
    print("  点[确认下发] → send_path()", ctl.send_path())
    print("  确认日志:", rig.rec.take("下发请求已确认")[-1:])
    print("  状态栏:", rig.win.statusbar._log.text())


def s3_timing(rig: Rig) -> None:
    """I 节：20 段路径的校核耗时（卡片步骤 6：只留实测数字 ⛔ 不承诺指标）。

    工况是**耗时上界**：路径扫到 x=1000、障碍在 x=603 被扫过 ⇒ 每个采样姿态都过粗筛并触发
    OCC 精判（不是只有少数几对）。本节只取耗时数字，结论🔴与门禁无关（门禁见 F/G/H 节）。"""
    rig.show("I. 20 段路径校核耗时（自造 40 mm 立方障碍在 x=603，被路径扫过＝精判全触发）")
    print("  导入成功:", rig.obstacle(GAP_CASES[2][1]))
    count = rig.path(LONG_POINTS)
    for round_no in range(3):
        rig.win.checkctl.run_check()
        result = rig.win.checkctl._result
        print(f"  第 {round_no + 1} 轮: 段数 {count}｜采样姿态 {result.sample_count}｜"
              f"障碍 1 个｜结论 {ICON[result.verdict]} {result.verdict}｜"
              f"耗时 {result.elapsed_ms:.1f} ms")
        pump(50)
    print("  core 耗时日志:", rig.rec.take("碰撞校核")[-1:])
    print("  右栏实测数字行:", rig.win.panel.step4._stat.text())


def s4_coverage(rig: Rig) -> None:
    """J 节：G19 覆盖面——五模式 N 现算（⛔ 不写死 11）＋ N=0 对照走同一条 check 通路。"""
    rig.show("J. G19 覆盖面：N 一律从 machine.yaml 现算")
    cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
    print("  links 表现算已建模连杆数:", len(cfg.links), "｜全机轴数:", len(cfg.axes),
          "｜全机未建模轴数:", len(unmodeled_axes(cfg)))
    for mode in cfg.modes:
        axes = mode_axes(cfg, f"{mode.name}臂")        # 界面名带「臂」后缀（02 §3），按前缀匹配
        print(f"  模式「{mode.name}臂」: 轴 {tuple(axes)}｜N={len(unmodeled_axes(cfg, axes))}"
              f"｜{unmodeled_axes(cfg, axes)}")
    print("  本取证工况（打磨臂）UI 标注:", rig.win.panel.step4._coverage.text())
    full = dataclasses.replace(ONE, modes=(dataclasses.replace(ONE.modes[0], axes=("X1",)),))
    zero = unmodeled_axes(full, mode_axes(full, "打磨臂"))
    print(f"  N=0 对照（合成配置：模式只挂 X1，X1 有连杆）: N={len(zero)}｜{zero}")
    result = check(PATH, _scene([_plate(903.0)], cfg=full, axes=mode_axes(full, "打磨臂")),
                   full.limits.clearance_warn_mm)
    print("  N=0 结论:", result.verdict, "｜", result.describe(), "｜", result.coverage())


def s5_envelope(rig: Rig) -> None:
    """K 节：包络是**承重参数**——同一几何只改包络值，判定从🟡翻🔴（⛔ 未改 machine.yaml）。"""
    rig.show("K. 包络承重性：间隙 5 mm 的同一工况，包络 3.0 mm（配置值）vs 12.0 mm（内存副本）")
    rig.run(GAP_CASES[1][1])
    ctl, pathctl = rig.win.checkctl, rig.win.pathctl
    slim = ctl._result
    print(f"  包络 3.0 mm: {ICON[slim.verdict]} {slim.verdict}｜最近距离 "
          f"{slim.cases[0].min_dist_mm:.3f} mm｜臂侧代理盒 {[round(v, 3) for v in slim.cases[0].box]}")
    cfg, chain, frame = pathctl.kinematics()
    fat_cfg = dataclasses.replace(
        cfg, limits=dataclasses.replace(cfg.limits, collision_envelope_mm=12.0))
    real = pathctl.kinematics
    pathctl.kinematics = lambda: (fat_cfg, chain, frame)     # 取证替身：只换内存里的配置副本
    ctl.run_check()
    grown = ctl._result
    pathctl.kinematics = real
    print(f"  包络 12.0 mm: {ICON[grown.verdict]} {grown.verdict}｜最近距离 "
          f"{grown.cases[0].min_dist_mm:.3f} mm｜臂侧代理盒 {[round(v, 3) for v in grown.cases[0].box]}")
    print("  判据: 几何与路径完全相同、只改包络 ⇒ 判定翻转即证明包络参与判定（非摆设）:",
          "对" if grown.verdict != slim.verdict else "⛔ 不对")
    print("  配置文件未改（取证只在内存里换副本）:",
          load_machine(str(REPO_ROOT / "config" / "machine.yaml")).limits.collision_envelope_mm)


def main() -> int:
    rig = Rig()
    print("取证环境:", sys.version.split()[0], "｜工作模式:", rig.win.workmode.current_mode(),
          "｜短路径点位:", TWO_POINTS)
    for step in (s0_refuse_interfere, s1_stale_result, s2_operator_choice, s3_timing,
                 s4_coverage, s5_envelope):
        step(rig)
    rig.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
