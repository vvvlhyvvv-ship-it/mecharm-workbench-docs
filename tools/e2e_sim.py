"""tools/e2e_sim —— T15 路径仿真页签·执行控制判据（standalone；99 台账 2026-09-19 预授权拆件）。

为什么独立成件：``e2e_tabs.py`` 被 T14 写满冻结、``e2e_smoke.py`` 冻结拼接（L-2 波次 3a 续裁）⇒
本单判据落本件：**自起 Rig＋本机模拟器**（``e2e_rig.Rig`` 只 import 不改），rc=0＝全 PASS——完成
标准的「e2e rc=0」以本件为准（e2e_smoke 全量 27 条由指挥侧收单时另跑确认不回退）。

判据（对 T15 卡完成标准逐条；读**操作员看得见的那份原文**，同 smoke 口径）：
  U1 空态：KPI 全「—」、清单 0 行、预演三钮禁用（Δ-6）｜U2 有数据态：KPI 真值＋时间轴带与校核一致＋
  设备列真值/「—」分明＋「估算」在场｜U3 预演：▶ 播放 → 游标随 seg 推进 → ⏏ 退出停
  U4 暂停/继续：ST_PAUSED 置位/清零＋命令字脉冲清零＋位姿冻结/恢复｜U5 倍率：25% 读回==25＋计划时长
  比≥1.2｜U6 复位：人话＋无红条｜U7 停止：人话＋cmd 清零｜Δ-1：「连续/逐段」在场（禁三模式）。

顺序敏感：U3 在连接前；U4–U7 同一条链路顺路（⛔ 不重连）；U7 握手收尾不等待（drain 承担）。
"""

from __future__ import annotations

import argparse
import logging
import os
import pathlib
import re
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

from PySide6.QtCore import QEventLoop, QTimer  # noqa: E402

from core.geometry.face_point import FacePoint  # noqa: E402
from tools.comm_selftest_kit import check, force_utf8_stdout, guarded, recording  # noqa: E402
from tools.e2e_rig import THREE_POINTS, Rig  # noqa: E402

OUTPUT = pathlib.Path("evidence/T15/e2e_sim.txt")
READY_S = 40.0            # 连接／握手等待上限（同 rig 口径）
FREEZE_MS = 400           # 暂停冻结／继续恢复的观察窗（≥ 数个发布周期）
EXEC_TO_S = 15.0          # 等握手走到「执行中」（阶段 4）的上限
SPEEDUP_MIN = 1.2   # 25%/100% 计划时长比下限（实测 1.42：短行程梯形几何压低速度比；未生效恒 1.0×）。
# 写入主证据＝PLC 侧 SpeedOverride 读回 ==25，此比值为执行侧旁证


class _PlanSpan(logging.Handler):   # noqa: too-few-public-methods
    """抓模拟器「装载通过：…总时长 X s」行——计划时长＝模拟器消费倍率后的结果，比墙钟纯。"""

    def __init__(self) -> None:
        super().__init__()
        self.spans: list[float] = []   # 「装载通过」的计划时长序列（按装载先后）

    def emit(self, record: logging.LogRecord) -> None:
        hit = re.search(r"总时长 ([\d.]+) s", record.getMessage())
        if hit:
            self.spans.append(float(hit.group(1)))


_CAPTURE = _PlanSpan()


def _pump(rig: Rig, ms: float) -> None:
    loop = QEventLoop()
    QTimer.singleShot(int(ms), loop.quit)
    loop.exec()   # 跑一段真事件循环（导入/握手在各线程，processEvents 不够；口径同 e2e_rig）


def _read_node(rig: Rig, key: str, sink: list) -> None:
    # 经 linkctl.submit 在循环线程读 PLC 侧写节点当前值（自环＝模拟器地址空间镜像）
    async def _read():
        sink.append(float(await rig.flow.link._session._wr[key].read_value()))
    rig.flow.link.submit(_read(), what=f"读回 {key}")
    _pump(rig, 500)


def section_empty(rig: Rig, results: dict, durations: dict) -> None:
    """U1：未生成路径 ⇒ 全「—」＋三钮禁用（Δ-6）。"""
    tab = rig.win.tabshell.sim
    rig.tab("sim")
    print("\n=== U1 未生成路径的空态（Δ-6）===")
    kpis = {key: label.text() for key, label in tab._kpis.items()}
    tri = not tab._enter.isEnabled() and not tab._play.isEnabled() and not tab._exit.isEnabled()
    print(f"  KPI：{kpis}｜结论行：{tab._summary.text()}｜清单 {tab._table.rowCount()} 行｜三钮禁用={tri}")
    check(results, "U1", all(text == "—" for text in kpis.values()) and tab._table.rowCount() == 0 and tri,
          "未生成路径：KPI 五格全「—」、轨迹清单 0 行、预演三钮禁用（⛔ 禁 42.6s／21 步等演示值）")


def _prepare(rig: Rig) -> None:
    """导入自造障碍＋注三点＋生成路径＋校核（真控制器路径，判据读各自灌出来的可见态）。"""
    assert rig.import_box()
    rig.pick()
    rig.win.pathctl.generate()
    rig.win.checkctl.run_check()
    rig.pump(200)


def section_data(rig: Rig, results: dict, durations: dict) -> None:
    """U2：有数据态——KPI 真值＋时间轴红绿带同校核＋设备列真值/「—」分明＋「估算」在场。"""
    tab, result = rig.win.tabshell.sim, rig.win.checkctl._result
    print("\n=== U2 有数据态（KPI·时间轴·清单）===")
    kpis = {key: label.text() for key, label in tab._kpis.items()}
    from PySide6.QtWidgets import QLabel
    bad_ids = {case.seg_id for case in result.cases}
    red_bands = sum(1 for _, _, bad in tab._bands if bad)
    rows = tab._table.rowCount()
    devices = {tab._table.item(row, 2).text() for row in range(rows)}
    dev_ok = all((tab._table.item(r, 2).text() != "—") == (tab._table.item(r, 5).text() != "可行") for r in range(rows))  # 设备列（T16 回填）与状态列逐行分明
    estimate = [l for l in tab.findChildren(QLabel) if "预计时长（估算）" in l.text()]
    print(f"  KPI：{kpis}｜结论行：{tab._summary.text()}｜时间轴 {len(tab._bands)} 带（红 {red_bands}）／"
          f"{len(tab._ticks)} 刻度｜清单 {rows} 行 设备列{devices} 分明={dev_ok}｜估算在场={bool(estimate)}")
    check(results, "U2", (result is not None and "≈" in kpis["dur"] and kpis["samples"].isdigit()
          and kpis["segs"].isdigit() and kpis["bad"] == str(sum(1 for c in result.cases if c.min_dist_mm <= 0.0))
          and kpis["gate"] in ("允许", "禁止") and "校核完成" in tab._summary.text()
          and red_bands == len(bad_ids) and len(tab._bands) == len(rig.win.pathctl.segments())
          and len(tab._ticks) == len(rig.win.pathctl.segments()) and rows == len(rig.win.pathctl.segments())
          and dev_ok and bool(estimate) and "估算" in estimate[0].text()),
          "KPI 全真值（时长带≈与估算标签、干涉步＝结论、许可∈{允许,禁止}）；时间轴带/刻度＝段数、"
          "红带数＝涉事段数；涉事设备列真值/「—」与状态列逐行分明（T16 回填后口径）")


def section_preview(rig: Rig, results: dict, durations: dict) -> None:
    """U3：预演（连接前、纯仿真态）——游标随 seg 推进、退出停。"""
    tab = rig.win.tabshell.sim
    print("\n=== U3 时间轴预演（只动画面，不下发）===")
    tab._play.click()
    rig.pump(600)
    cursor_moved, seen_seg = tab._track._cursor is not None, tab._cursor_seg
    tab._exit.click()
    rig.pump(200)
    print(f"  游标在场={cursor_moved}、游标段={seen_seg}；退出后播放态={rig.win.pathctl._timer.isActive()}")
    check(results, "U3", cursor_moved and seen_seg >= 1 and not rig.win.pathctl._timer.isActive(),
          "▶ 播放预演 ⇒ 游标随 pose.update 的 seg 字段段级推进（⛔ 不外推段内进度）；"
          "⏏ 退出预演 ⇒ 播放停（沿用 pathctl 原播放机制）")


def _send_and_wait_exec(rig: Rig) -> bool:
    """下发并等握手走到「执行中」（阶段 4）；失败时打印诊断（红条/门禁旁注/阶段表）。"""
    if not rig.win.checkctl.send_path():
        print(f"  诊断：send_path 被拒；红条={rig.win.panel.step5._err.text()!r}；旁注={rig.win.panel.step5.send_note.text()!r}")
        return False
    ok = rig.wait(lambda: any(n == 4 for n, _ in rig.stages), EXEC_TO_S)
    if not ok:
        print(f"  诊断：{EXEC_TO_S:g}s 未到执行中；stages={rig.stages}；红条={rig.win.panel.step5._err.text()!r}")
    return ok


def section_pause_resume(rig: Rig, results: dict, durations: dict) -> None:
    """U4：暂停/继续逐个实测（ST_PAUSED 置位/清零＋命令字脉冲清零＋位姿冻结/恢复）。"""
    pane = rig.win.panel.step5
    print("\n=== U4 暂停 → 继续（100% 倍率）===")
    pane.connect_requested.emit()                         # 走真按钮信号连本机模拟器（G1 同款）
    if not rig.wait(lambda: rig.flow.link.is_up):
        check(results, "U4", False, "连不上本机模拟器，暂停/继续判据无从做起")
        return
    pane._override.setCurrentIndex(0)                     # 25%（短轨迹 100% 时暂停窗口太小，竞态不稳）
    started = time.perf_counter()
    if not rig.win.checkctl.send_path():
        check(results, "U4", False, "下发被拒，暂停/继续判据无从做起")
        return
    # 「执行中」出现同轮就点（等信号再点会错过 ~0.5s 轨迹窗）；点前先等 300ms——stage4＝「已请求启动」，
    # 须让 ACK 往返与 start 脉冲清零落地，否则 cmd=0 与 cmd=4 在模拟器 50ms 扫描窗内交错丢沿（实测）
    clicked, deadline = False, time.monotonic() + EXEC_TO_S
    while time.monotonic() < deadline and not clicked:
        _pump(rig, 50)
        if any(n == 4 for n, _ in rig.stages) and pane._pause_btn.isEnabled():
            (_pump(rig, 300), pane._pause_btn.click())
            clicked = True
    paused = rig.wait(lambda: pane._paused_line.isVisible())
    _pump(rig, FREEZE_MS)
    frozen, cmd_after_pause = rig.last_pose(), []
    _read_node(rig, "cmd", cmd_after_pause)
    _pump(rig, FREEZE_MS)
    still = rig.last_pose()
    pane._resume_btn.click()
    resumed = rig.wait(lambda: not pane._paused_line.isVisible())
    _pump(rig, FREEZE_MS)
    moved = rig.last_pose()
    done = rig.wait(lambda: not rig.flow.link.is_busy)
    durations["t100"] = time.perf_counter() - started
    print(f"  暂停：可见={paused} cmd清零={cmd_after_pause == [0]} 冻结={frozen == still}｜继续：隐藏={resumed} "
          f"恢复推进={moved != still} 收尾={done}｜全程 {durations['t100']:.2f} s")
    check(results, "U4", (paused and cmd_after_pause == [0] and frozen is not None and frozen == still
          and resumed and moved != still and done),
          "⏸ 暂停 ⇒ ST_PAUSED 置位＋命令字脉冲清零（§9.3-②）＋位姿冻结不外推；▶ 继续 ⇒ 清零＋恢复推进")


def section_override(rig: Rig, results: dict, durations: dict) -> None:
    """U5：倍率实做——倒序 100% 先把模型送回起点（U4 已停在终点，零距离重发测不出折速），
    再正向 25% 计时；读回 SpeedOverride==25＋模拟器计划时长比作折速实证。"""
    pane = rig.win.panel.step5
    print("\n=== U5 倍率 25% 实做（倒序 100% 归位 → 正向 25% 计时）===")
    pane._override.setCurrentIndex(3)
    _re_pick(rig, tuple(reversed(THREE_POINTS)))
    started = time.perf_counter()
    back = rig.win.checkctl.send_path() and rig.wait(lambda: not rig.flow.link.is_busy, READY_S)
    durations["t100"] = time.perf_counter() - started
    pane._override.setCurrentIndex(0)                     # 25%
    _re_pick(rig, THREE_POINTS)
    started = time.perf_counter()
    accepted = rig.win.checkctl.send_path()
    done = rig.wait(lambda: not rig.flow.link.is_busy, READY_S)
    durations["t25"] = time.perf_counter() - started
    sink: list = []
    _read_node(rig, "speed_override", sink)
    plan = _CAPTURE.spans[-2:]
    plan_ratio = round(plan[1] / plan[0], 3) if len(plan) == 2 and plan[0] else 0.0
    print(f"  归位={back} 全程 {durations['t100']:.2f} s；受理={accepted} 收尾={done}；25% 全程 {durations['t25']:.2f} s；"
          f"读回={sink}；计划时长 {plan[0] if plan else '—'}→{plan[1] if len(plan) > 1 else '—'} s（比 {plan_ratio}）；偏好={pane.preference()}")
    check(results, "U5", accepted and done and sink == [25.0] and plan_ratio >= SPEEDUP_MIN
          and pane.preference() in ("连续", "逐段"),
          f"25% 写进 PLC（读回 {sink}）且计划时长 {plan_ratio}×（≥{SPEEDUP_MIN:g}，折速旁证非只「已生效」）；"
          "执行偏好为「连续/逐段」二选一（Δ-1）")


def _re_pick(rig: Rig, points) -> None:
    # 按给定顺序重摆三点并重新生成＋校核（send_path 入口复判要求结论与指纹同源）
    rig.win.panel.step2.clear()
    for index, pos in enumerate(points, start=1):
        rig.win.panel.step2.add_face_point(
            FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
    rig.win.pathctl.generate()
    rig.win.checkctl.run_check()
    rig.pump(200)


def section_reset_stop(rig: Rig, results: dict, durations: dict) -> None:
    """U6＋U7：复位（空闲）与停止（执行中）——四命令全数实测收口。"""
    pane = rig.win.panel.step5
    print("\n=== U6 复位（空闲）｜U7 停止（执行中）===")
    pane._reset_btn.click()
    told = rig.wait(lambda: "已复位" in rig.win.statusbar._log.text())
    no_err = not pane._err.isVisible()
    print(f"  ⟲ 复位：人话={told}、红条未亮={no_err}")
    check(results, "U6", told and no_err, "⟲ 复位 ⇒ CMD_RESET 人话在场且无异常红条（不承诺位置）")
    pane._override.setCurrentIndex(3)
    if not _send_and_wait_exec(rig):
        check(results, "U7", False, "第二次下发未走到「执行中」，停止判据无从做起")
        return
    _pump(rig, 300)                       # 同 U4：等启动 ACK 往返与脉冲清零落地，防 cmd 交错丢沿
    pane._halt_btn.click()
    stopped = rig.wait(lambda: "已请求停止" in rig.win.statusbar._log.text())
    cmd: list = []
    _read_node(rig, "cmd", cmd)                        # 脉冲清零核验（交错窗口见上）
    print(f"  ⏹ 停止：人话={stopped}；cmd 清零={cmd == [0]}（握手收尾不等待，由 close 的 drain 承担）")
    check(results, "U7", stopped and cmd == [0],
          "⏹ 停止 ⇒ 「已请求停止」人话＋命令字脉冲清零（ACK_STOP_DONE 路径与 linkctl.abort 同源）")


def main(argv=None) -> int:
    args = parse(argv)
    force_utf8_stdout()
    plc_log = logging.getLogger("comm.plc_logic")   # 抓「装载通过」计划时长（U5 旁证）
    plc_log.addHandler(_CAPTURE)
    plc_log.setLevel(logging.INFO)                  # root 默认 WARNING 会把 log.info 滤掉
    results: dict[str, bool] = {}
    durations: dict[str, float] = {}
    with recording(None if args.no_save else OUTPUT):
        print(f"T15 路径仿真页签判据 · python {sys.version.split()[0]} · "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"取证物 {OUTPUT}｜只跑 {args.only or '全部节'}")
        rig = Rig()
        try:
            for key, body in PLAN:
                if args.only and not key.upper().startswith(args.only.upper()):
                    continue
                if key == "PREP":
                    _prepare(rig)                     # 导入/取点/生成/校核（U2 的前置，无判据）
                elif body is not None:
                    guarded(results, key, lambda run=body: run(rig, results, durations))
            (rig.tab("sim"), _pump(rig, 200))             # 收尾前把页签留在前台便于人读
        finally:
            rig.close()
        bad = [key for key, ok in results.items() if not ok]
        picked = [key for key, _b in PLAN if not args.only or key.upper().startswith(args.only.upper())]
        missing = [key for key in picked if key != "PREP" and key not in results]
        print("\n=== 结论 ===")
        for key, _body in PLAN:
            if key in results:
                print(f"  {key:<3} {'PASS' if results[key] else 'FAIL'}")
        print(f"  未跑到：{('、'.join(missing)) if missing else '无'}｜共 {len(results)} 条："
              f"{len(results) - len(bad)} PASS、{len(bad)} FAIL")
        print("结论：" + ("全链路走通" if not bad and not missing else "有判据未过，见上文原文"))
    return 0 if not bad and not missing else 1


def parse(argv=None):
    parser = argparse.ArgumentParser(description="T15 路径仿真页签判据（离屏、只连本机模拟器）")
    parser.add_argument("--only", default="", help="只跑这些节（前缀匹配，如 U4）")
    parser.add_argument("--no-save", action="store_true", help="不落 evidence/T15/e2e_sim.txt")
    return parser.parse_args(argv)


# (判据号, 入口)；PREP 哨兵＝导入/取点/生成/校核（U2 前置，无判据）；U6+U7 同入口
PLAN = (("U1", section_empty), ("PREP", None), ("U2", section_data), ("U3", section_preview),
        ("U4", section_pause_resume), ("U5", section_override), ("U6", section_reset_stop),
        ("U7", None))

if __name__ == "__main__":
    raise SystemExit(main())
