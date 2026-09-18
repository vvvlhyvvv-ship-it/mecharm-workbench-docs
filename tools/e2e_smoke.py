"""T10 卡片步骤⑦：全链路冒烟——导入 → 3 点 → 路径 → 校核 → 模拟器下发 → 跟随 10 s，逐节断言完成。

跑法（仓根；退出码 0＝所选节全 PASS）：
    /d/Miniforge3/envs/mecharm/python.exe tools/e2e_smoke.py [--only A,G] [--no-save]
输出落 ``evidence/T10/e2e_smoke.txt``（``--no-save`` 只上屏）。本件自置 ``QT_QPA_PLATFORM=offscreen``
⇒ 不需显示器；只连 127.0.0.1 的本机模拟器（D-6 禁连真 PLC）。

**三件分工**（拆件理由同一个：合起来实测 310 行 > 04 §4.5-① 的 300 行上限，去重复与抽函数都已做完，
只剩拆文件一条路 §4.5-②③；手法同 T09 的 ``comm_selftest.py``＋``comm_selftest_kit.py``）：
本件＝判据表＋入口＋卡片步骤⑦ 的 A–G 判据；``tools/e2e_rig.py``＝装置（起壳／驱动 UI／读数）；
``tools/e2e_faults.py``＝卡片步骤④ 的 H1–H3 判据。⛔ 入口与退出码只在本件一处。

十九条判据分九节：**A** 发布周期守卫（G20-②：``publish_interval_ms ≤ 50`` ⇔ ≥20 Hz；静默改 60 时 pytest
仍全绿、只有本件会红 ⇒ 负控证据＝临时改 60 跑出 A 节 FAIL 再还原）；**S** T12 启动序列（经登录页
进主界面／舞台档位表 std·wide·1366／取证档身份剥离）；**B–E** 步骤①→④ 各步真做完；**F**
下发块组装守卫（轴数 > 槽位数 ⇒ 人话拒绝并点名放不下的轴，⛔ 不静默截断）；**G1–G7** 连接／确认弹窗的
请求值小字／握手五段／``pose.update`` 出前端／角标实测频率／帧计数／模式互斥；**H1–H3** 卡片步骤④ 的
异常三用例（越界丢帧／PLC 拒绝给红条＋原因码＋[查看日志]／运行中断线后灯灰＋模型停住不跳飞）。

⚠️ **各节有先后依赖**（B 的模型是 E 的障碍源、D 的路径是 F／G 的下发内容、G 连上的链路是 H 的工况，
且 H3 断线会停掉本机模拟器 ⇒ 三例的顺序固定为越界→拒绝→断线）⇒ ``--only`` 只适合复跑单节看原文，
单跑 G 或 H 会因缺前置而红，这不是缺陷。
"""

from __future__ import annotations

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

from app.livectl import HZ_DIVISOR  # noqa: E402
from app.sendseg import SendSegError, build_segments  # noqa: E402
from app.splash import SplashPane  # noqa: E402
from app.statusbar import StatusBar  # noqa: E402
from comm.opcua_client import axis_slots_of  # noqa: E402
from core.collision import mode_axes  # noqa: E402
from core.config.ui_config import load_ui  # noqa: E402
from tools.comm_selftest_kit import check, force_utf8_stdout, guarded, recording  # noqa: E402
from tools.e2e_faults import section_h  # noqa: E402  卡片步骤④ 异常三用例的判据（拆件理由见那件 docstring）
from tools.e2e_rig import CONFIG, STAGES, THREE_POINTS, Rig  # noqa: E402

OUTPUT = pathlib.Path("evidence/T10/e2e_smoke.txt")
UI_CONFIG = pathlib.Path("config/ui.yaml")   # T12 S 节：取证档判据读同一份真实交付物
MAX_PUBLISH_MS = 50.0        # G20-② 守卫值：≤50 ms ⇔ ≥20 Hz（契约 §6.1 的回读节律）⛔ 不写死 Hz
OVER_MODE = "打磨臂"          # 9 轴 > 8 槽位：只为证 F 节的人话拒绝，⛔ 不用它下发
FOLLOW_S = 10.0              # 卡片步骤⑦ 的「跟随 10 s」
DONE_ICON = "●"              # ⑤页五段进度的「完成」图标（app/steps/step5_send.py 的 _ICON）
NOTE_MARK = "本次要写进 PLC 的请求值"        # 确认弹窗里请求值小字的标题行（卡片步骤①）


def section_a(rig: Rig, results: dict) -> None:
    print("\n=== A 发布周期守卫（G20-②：publish_interval_ms ≤ 50 ms ⇔ ≥20 Hz）===")
    interval = rig.cfg.opcua.publish_interval_ms
    nominal, floor = rig.nominal_hz(), 1000.0 / MAX_PUBLISH_MS
    print(f"  machine.yaml 的 publish_interval_ms = {interval:g} ms ⇒ 标称 {nominal:.1f} Hz")
    if interval <= MAX_PUBLISH_MS:
        check(results, "A", True,
              f"发布周期 {interval:g} ms ≤ 上限 {MAX_PUBLISH_MS:g} ms（标称 {nominal:.1f} Hz ≥ {floor:g} Hz）")
        return
    check(results, "A", False, f"发布周期 {interval:g} ms > 上限 {MAX_PUBLISH_MS:g} ms ⇒ 标称只有 "
                               f"{nominal:.1f} Hz，低于契约 §6.1 的 {floor:g} Hz：回读节律不够、跟随会掉帧")


def section_s(rig: Rig, results: dict) -> None:
    print("\n=== S T12 启动序列：经登录页进入＋舞台档位＋取证档 ===")
    user, name = rig.win.splash.login_values()
    print(f"  当前页={rig.win.stage_host.page()}；登录预填 工号={user}·姓名={name}；"
          f"载入里程碑 {rig.win.boot.done_count()}/{rig.win.boot.total()}")
    check(results, "S1", rig.win.stage_host.page() == "workbench" and user and name,
          "经载入/登录页进入主界面（同窗原地切换、未另开窗）；预填来自 ui.yaml、可改")
    _stage_table(rig, results)
    _evidence_strip(results)


def _stage_table(rig: Rig, results: dict) -> None:
    wanted = ((1920, 1080, "std", 1.0), (2560, 1080, "wide", 1.56), (1366, 768, "std", 1.0))
    verdicts = []
    for w, h, kind, fs in wanted:
        rig.win.resize(w, h)
        rig.pump(120)
        spec = rig.win.stage_host.spec()
        ok = spec.key == kind and abs(spec.fs - fs) < 1e-6
        verdicts.append(ok)
        print(f"  窗口 {w}×{h} ⇒ {spec.key}（--fs={spec.fs:g}，左右栏 {spec.left_px}/{spec.right_px}）"
              f"{'✓' if ok else '✗ 期望 ' + kind}")
    rig.win.resize(1440, 860)               # 还原 Rig 默认窗口，后续节不因尺寸分心
    rig.pump(120)
    check(results, "S2", all(verdicts) and rig.win.minimumWidth() == 1366,
          "档位取值表：std 1920×1080／wide 2560×1080（--fs=1.56）／1366×768 等比可显（最小尺寸在）")


def _evidence_strip(results: dict) -> None:
    base = load_ui(str(UI_CONFIG))
    evid = load_ui(str(UI_CONFIG), profile="evidence")
    splash = SplashPane(evid)
    bar = StatusBar(evid)
    texts = splash.identity_texts() + [bar._watermark.text(), bar._version.text()]
    leaks = [v for v in (base.company, base.company_en, base.bid_no, base.bidder_note,
                         base.watermark, base.version_text) if any(v in t for t in texts)]
    print(f"  取证档画面身份串（前两串）：{texts[:2]}｜底栏：{texts[-2]}｜{texts[-1]}")
    print(f"  与普通档身份值重合：{len(leaks)} 处" + ("" if not leaks else f" → {'、'.join(leaks)}"))
    check(results, "S3", not leaks,
          "取证档启动 ⇒ 画面无甲方中英文名／招标编号／乙方投标标识（水印与版本同被占位替换）")


def section_b(rig: Rig, results: dict) -> None:
    print("\n=== B 步骤①导入实体模型（自造 40 mm 立方，走真 QThread 导入链路）===")
    ok = rig.import_box()
    asm = rig.assembly()
    stats = getattr(asm, "stats", None) or {}
    print(f"  导入完成={ok}；零件数={stats.get('parts')}；三角面={stats.get('tris')}；"
          f"B-Rep 真身={getattr(asm, 'is_brep', None)}")
    check(results, "B", ok and asm is not None and bool(asm.is_brep),
          f"实体模型已导入且带 B-Rep 真身（碰撞校核的几何源），零件 {stats.get('parts')} 个")


def section_c(rig: Rig, results: dict) -> None:
    print("\n=== C 步骤②取 3 个点位（真 step2 接口，⛔ 不塞私有序列）===")
    got = rig.pick()
    print(f"  点位表 {len(got)} 行：" + "、".join(f"{w.name}{tuple(w.pos_mm)}" for w in got))
    check(results, "C", len(got) == len(THREE_POINTS),
          f"点位表 {len(got)} 行 ＝ 要求的 {len(THREE_POINTS)} 点")


def section_d(rig: Rig, results: dict) -> None:
    print("\n=== D 步骤③生成路径 ===")
    rig.win.pathctl.generate()
    segments, summary = rig.win.pathctl.segments(), rig.win.panel.step3.summary()
    print(f"  {summary.describe() if summary else '（没有汇总）'}")
    for seg in segments:
        print(f"    第 {seg.id} 段 {seg.type} {seg.start_name}→{seg.end_name} 长 {seg.length_mm:.1f} mm"
              f" 速 {seg.speed_mm_s:.1f} mm/s 时长 {seg.duration_s:.2f} s 阻断={seg.blocked}")
    check(results, "D", summary is not None and summary.ok and len(segments) == len(THREE_POINTS) - 1,
          f"{len(segments)} 段（{len(THREE_POINTS)} 点 ⇒ {len(THREE_POINTS) - 1} 段）、"
          f"汇总 ok={getattr(summary, 'ok', None)}、不可达段 {getattr(summary, 'blocked_count', None)} 个")


def section_e(rig: Rig, results: dict) -> None:
    print("\n=== E 步骤④碰撞校核（core OCC 是判定权威，本件只读结论）===")
    rig.win.checkctl.run_check()
    res = rig.win.checkctl._result
    if res is None:
        check(results, "E", False, "跑不出结论（数据不齐或判定失败，原因已进状态栏）")
        return
    print(f"  结论={res.verdict}｜{res.describe()}\n  覆盖面={res.coverage()}")
    print(f"  路径指纹={res.path_hash}｜耗时 {res.elapsed_ms:.1f} ms｜命中 {len(res.cases)} 项")
    for case in res.cases:
        print(f"    第 {case.seg_id} 段 {case.part_a} ↔ {case.part_b} 最小距离 {case.min_dist_mm:.2f} mm")
    check(results, "E", res.verdict in ("pass", "warn") and bool(res.coverage()) and bool(res.path_hash),
          f"结论「{res.verdict}」（非干涉 ⇒ 步骤⑤门禁应解锁）、覆盖面标注与路径指纹都非空")


def section_f(rig: Rig, results: dict) -> None:
    print("\n=== F 下发块组装守卫（轴数 > 槽位数 ⇒ 人话拒绝并点名，⛔ 不静默截断）===")
    slots, axes = axis_slots_of(rig.cfg.opcua.pack_profile), mode_axes(rig.cfg, OVER_MODE)
    overflow = axes[slots:]
    print(f"  pack_profile={rig.cfg.opcua.pack_profile} ⇒ 槽位 {slots} 个；"
          f"「{OVER_MODE}」轨迹轴 {len(axes)} 根：{'、'.join(axes)}")
    try:
        path = build_segments(rig.win.pathctl.segments(), rig.cfg, OVER_MODE)
        check(results, "F", False, f"⛔ 竟然组装出了 {len(path)} 段——超槽位就该人话拒绝")
        return
    except SendSegError as exc:
        told = str(exc)
    print(f"  人话原文：{told}")
    named = [name for name in overflow if name in told]
    check(results, "F", len(named) == len(overflow) and "无处安放" in told,
          f"已拒绝并点名放不下的轴 {'、'.join(overflow)}（{len(named)}/{len(overflow)} 个出现在原文里）")


def section_g(rig: Rig, results: dict) -> None:
    print("\n=== G 连接 → 确认弹窗 → 写段与命令字 → 握手五段 → 跟随 10 s ===")
    rig.win.panel.step5.connect_requested.emit()          # 走真按钮信号，⛔ 不直调 link.start
    up = rig.wait(lambda: rig.flow.link.is_up)
    print(f"  端点={rig.flow.link.endpoint}；会话可用={up}")
    check(results, "G1", up, f"已连上本机 PLC 模拟器 {rig.flow.link.endpoint}" if up else "连不上模拟器")
    if up:
        _handshake(rig, results)


def _handshake(rig: Rig, results: dict) -> None:
    accepted = rig.win.checkctl.send_path()               # 双阻断＋确认弹窗（已替身）全走一遍
    text = rig.dialogs[-1] if rig.dialogs else ""
    print(f"  send_path() 受理={accepted}；确认弹窗 {len(text)} 字，含请求值小字={NOTE_MARK in text}")
    for line in text.splitlines():
        print(f"    | {line}")
    check(results, "G2", accepted and NOTE_MARK in text and "槽位↔轴" in text,
          "确认弹窗摊开了真要写进 PLC 的请求值（端点／段数×槽位×字节／倍率／槽位↔轴／逐段目标值）")
    done = rig.wait(lambda: not rig.flow.link.is_busy)
    print(f"  握手结束={done}；linkctl 报来的阶段号={[n for n, _ in rig.stages]}")
    for number, line in rig.stages:
        print(f"    [阶段 {number}] {line}")
    icons = rig.stage_icons()
    print(f"  ⑤页进度图标={''.join(icons)}；日志里出现过人话的阶段={rig.said_stages()}")
    check(results, "G3", done and rig.said_stages() == list(STAGES) and icons.count(DONE_ICON) == len(STAGES),
          f"五段进度全部走到并全部标完成（阶段 1 由下发编排自标、2–5 由 linkctl 报来；"
          f"图标 {icons.count(DONE_ICON)}/{len(STAGES)} 完成）")
    rig.pump(FOLLOW_S * 1000)                             # 卡片步骤⑦：跟随 10 s
    _follow(rig, results)


def _follow(rig: Rig, results: dict) -> None:
    poses = rig.poses()
    matrices = [next(iter(p["poses"].values())) for p in poses if p.get("poses")]
    print(f"  跟随 {FOLLOW_S:g} s：pose.update {len(poses)} 帧、矩阵 {len(matrices)} 个"
          f"（每个 {len(matrices[0]) if matrices else 0} 数）")
    check(results, "G4", bool(matrices) and all(
        len(m) == 16 and all(isinstance(v, float) for v in m) for m in matrices),
        f"{len(poses)} 帧 pose.update 出前端，位姿一律 16 个浮点（to_column_major 之后的列主序）")
    hz, nominal, badge_text = rig.hz(), rig.nominal_hz(), rig.win.statusbar._freq.text()
    fps = rig.fps()
    print(f"  角标原文：{badge_text}（标称 {nominal:.1f} Hz、变黄阈值 {nominal / HZ_DIVISOR:.1f} Hz）")
    check(results, "G5", hz is not None and hz >= nominal / HZ_DIVISOR and fps is not None,
          f"实测数据频率 {'--' if hz is None else f'{hz:.1f}'} Hz ≥ 标称的一半 {nominal / HZ_DIVISOR:.1f} Hz"
          f"（角标不变黄；阈值由 publish_interval_ms 算出 ⛔ 不写死 10），且画面 fps 也同时在角标上"
          f"（{'有' if fps else '没有'}）——`set_freq` 是整体替换、数据 Hz 与画面 fps 由两件分别写，"
          f"两个数都留得住才证得出 livectl **后连** Bridge.received 那条接线顺序")
    got, dropped = rig.flow.live.stats()
    print(f"  已采用 {got} 帧、丢弃 {dropped} 帧；⑤页计数行：{rig.win.panel.step5._counts.text()}")
    check(results, "G6", got > 0 and dropped == 0,
          f"回读帧已采用 {got} 帧（> 0）、越界丢弃 {dropped} 帧（本次工况在行程内 ⇒ 应为 0）")
    live, badge = rig.flow.live.following, rig.win.badge.text()
    print(f"  跟随中={live}；徽标={badge}；②可编辑={rig.win.panel.step2.isEnabled()}；"
          f"③可编辑={rig.win.panel.step3.isEnabled()}；步骤⑤标完成={rig.win.stepbar._completed[4]}")
    check(results, "G7", live and badge == "联动" and not rig.win.panel.step2.isEnabled()
          and not rig.win.panel.step3.isEnabled() and rig.win.stepbar._completed[4],
          "模式互斥成立：徽标[联动]、点位与步骤③已锁定（要改点须先[暂停跟随]）、步骤⑤已标完成")


# (判据号, 标题, 入口函数)；G2–G7／H2–H3 无入口＝由 section_g／section_h 在同一条链路上顺路记进
# results（⛔ 不重连：重连就等于换了工况，前一条的证据也就不作数了）
PLAN: tuple[tuple[str, str, object], ...] = (
    ("A", "发布周期守卫", section_a), ("S1", "登录进入主界面", section_s),
    ("S2", "舞台档位表", None), ("S3", "取证档剥离", None),
    ("B", "步骤①导入", section_b), ("C", "步骤②3 点", section_c),
    ("D", "步骤③路径", section_d), ("E", "步骤④校核", section_e), ("F", "下发块组装守卫", section_f),
    ("G1", "连接", section_g), ("G2", "确认弹窗请求值", None), ("G3", "握手五段", None),
    ("G4", "pose.update 出前端", None), ("G5", "角标实测频率", None), ("G6", "帧计数", None),
    ("G7", "模式互斥", None),
    ("H1", "越界丢帧", section_h), ("H2", "PLC 拒绝", None), ("H3", "断线冻结", None),
)


def selected(key: str, only: str) -> bool:
    """``--only`` 按**前缀**匹配（写 G 即选中 G1–G7），逗号分隔口径同 ``tools/comm_selftest.py``。"""
    tokens = [token.strip().upper() for token in only.split(",") if token.strip()]
    return not tokens or any(key.upper().startswith(token) for token in tokens)


def parse(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="T10 全链路冒烟（离屏、只连本机模拟器）")
    parser.add_argument("--only", default="", help="只跑这些节（逗号分隔、前缀匹配，如 A,G）")
    parser.add_argument("--no-save", action="store_true", help="只上屏，不落 evidence/T10/e2e_smoke.txt")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = parse(argv)
    force_utf8_stdout()
    results: dict[str, bool] = {}
    with recording(None if args.no_save else OUTPUT):
        print(f"T10 全链路冒烟 · python {sys.version.split()[0]} · {time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"配置文件 {CONFIG}｜取证物 {OUTPUT}｜只跑 {args.only or '全部节'}")
        rig = Rig()
        try:
            for key, _title, body in PLAN:
                if body is not None and selected(key, args.only):
                    guarded(results, key, lambda run=body: run(rig, results))
        finally:
            rig.close()
        bad = [key for key, ok in results.items() if not ok]
        missing = [key for key, _title, _body in PLAN if selected(key, args.only) and key not in results]
        print("\n=== 结论 ===")
        for key, title, _body in PLAN:
            if key in results:
                print(f"  {key:<3} {title:<18} {'PASS' if results[key] else 'FAIL'}")
        print("  未跑到（前置节失败或被 --only 排除）：" + ("、".join(missing) if missing else "无"))
        print(f"共 {len(results)} 条判据：{len(results) - len(bad)} PASS、{len(bad)} FAIL、"
              f"{len(missing)} 条未跑到")
        print("结论：" + ("全链路走通" if not bad and not missing else "有判据未过，见上文原文"))
    return 0 if not bad and not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
