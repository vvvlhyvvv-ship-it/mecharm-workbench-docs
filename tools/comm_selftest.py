"""T09 完成标准的**双进程**自测取证（步骤 5 ＋ 完成标准 1／2／3／4／5）。

``tests/test_opcua.py`` 在**同进程**里验协议与阈值；但完成标准第 1 条要「模拟器＋客户端**双进程**跑通」、
第 4 条要「断 simulator **进程**→客户端 5 s 内判离线」——这两条只有真起子进程才算数。故本脚本分六节出证据，
每节打印**实测数字**并当场判 PASS／FAIL：

    A 段打包实测（完成标准 2）　　B 双进程回读测频（完成标准 1／3＋步骤 5 的「≥20 Hz」）
    C 九步握手到 ST_DONE（完成标准 1，两侧日志同轮对账）　　D 注入拒绝 → 收原因码（步骤 5）
    E kill 子进程 → 5 s 内判离线（完成标准 4）　　F 换点表零改码（完成标准 5）

跑法（仓根，解释器须是装了 asyncua 的 mecharm 环境；B／C／E 共用一个子进程与一次会话）::

    python tools/comm_selftest.py             # 全跑，输出同时落 evidence/T09/selftest.txt
    python tools/comm_selftest.py --only A,F  # 只跑指定节；加 --no-save 则只上屏不落盘

退出码：0＝所选节全 PASS；1＝有 FAIL 或有节没出结论（失败原文打印，不吞异常）。

**频率判据的窗口／估计量／容差三项均偏离卡面字面写法，实测依据与原始数字全写在 ``measure_frequency``**。

**拆件说明**（04 §4.5-①②③）：本件实测 **410 行**超 300 行上限，去重复与抽函数均已做完（无函数超 50 行），故
只剩拆文件一条路——**双进程通用夹具**（子进程宿主／Tee 落盘／临时端口／记账／最小二乘）拆到 ``comm_selftest_kit.py``。
"""

from __future__ import annotations

import argparse
import asyncio
import pathlib
import sys
import tempfile
import time

# `python tools/comm_selftest.py` 的 sys.path[0] 是 tools/ 而非仓根，故先补仓根才能 import comm.*
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from comm.opcua_client import (MS_PER_S, SEG_HEAD_BYTES, SEG_SLOTS, LinkState,  # noqa: E402
                               LoadRejected, Segment, axis_slots_of, connect, pack_segments,
                               seg_layout, unpack_segments)
from comm.simulator import FAULT_REJECT  # noqa: E402
# 走 `tools.` 前缀（仓根已补进 sys.path）：附6-② 按包名白名单放行 `tools`，裸模块名会被误判为第三方包。
from tools.comm_selftest_kit import (RATE_MARK, STALL_MARK, Child, check,  # noqa: E402
                                     force_utf8_stdout, free_endpoint, guarded, recording, slope)
from core.config import REPO_ROOT, load_machine  # noqa: E402

CONFIG = REPO_ROOT / "config" / "machine.yaml"
EVIDENCE = REPO_ROOT / "evidence" / "T09"
OUTPUT = EVIDENCE / "selftest.txt"

EXPECTED_SEG_BYTES = 56     # 完成标准第 2 条点名的实测段长（``v1_2_8axis``）；此处是**判据**，不是布局常量
READ_SECONDS = 60.0         # 频率判据窗口（为何不是卡面字面的 10 s，实测依据见 measure_frequency）
CARD_SECONDS = 10.0         # 步骤 5 字面的「读模拟器 10 s」；作为子窗口数字一并贴出
MIN_HZ = 20.0               # 完成标准第 3 条：实测频率 ≥20 Hz（阈值本身，不因下面的容差而下调）
HZ_RESOLUTION = 0.02        # 量具分辨率容差（真值与阈值重合故必留，见 measure_frequency）＝60 s 斜率实测散布
                            # （跨度 0.0106≈±0.005）的约 4 倍；原 0.01 误称 5 倍实约 2 倍、最小值仅高通过线 0.0097（红闪）⇒ @user 裁改。
OFFLINE_LIMIT_S = 5.0       # 完成标准第 4 条：断进程后 5 s 内判离线
SPEED_OVERRIDE = 50.0       # §5.1 倍率（%）；取半速顺带验 SpeedOverride 真的进了钳位
TOL_MM = 1e-3               # DONE 时刻回读位置与目标点之差的容许量（梯形末端是钳位到终点的，应严格相等）
SECTIONS = ("A", "B", "C", "D", "E", "F")

# 测试路径：本体 6 轴（≤8 槽位，契约 V1.2 口径），两段、第二段带 dwell
PATH = (Segment(pos=(120.0, 30.0, -15.0, 0.0, 45.0, 10.0), vel=200.0, acc=800.0, dec=800.0),
        Segment(pos=(240.0, -15.0, 30.0, 0.0, 90.0, -20.0), vel=200.0, acc=800.0, dec=800.0,
                dwell_ms=100))

# 换点表演示的改名表：DB 名＋符号名整体换掉（含数组下标写法），证明代码里没有任何符号名字面量
RENAMES = (("DB_PLC_to_SW", "DB_Auf"), ("DB_SW_to_PLC", "DB_Ab"), ("SegCount", "Anzahl"),
           ("SpeedOverride", "Ueberfahrt"), ("AlarmWord", "Alarme"), ("Heartbeat", "Puls"),
           ("CurSeg", "SegmentNr"), ("Status", "Zustand"), ("SeqID", "Folge"), ("Ack", "Quitt"),
           ("Cmd", "Befehl"), ("Pos[", "P["), ("Vel[", "V["), ('"Seg"', '"Segmente"'))


def section_a(cfg, results: dict) -> None:
    """完成标准第 2 条：段长实测 56 B、未用轴位与未用段一律填 0（十六进制留痕）。"""
    print("\n[A] 段打包（pack_profile 开关 → struct.calcsize 实算）")
    slots = axis_slots_of(cfg.opcua.pack_profile)
    fmt, seg_bytes = seg_layout(slots)
    payload = pack_segments(PATH, slots)
    used = len(PATH[0].pos)
    first = payload[:seg_bytes]
    print(f"  pack_profile = {cfg.opcua.pack_profile}，槽位 = {slots} 个，struct = {fmt}")
    print(f"  段长实测 = {seg_bytes} B；整批 = {len(payload)} B = {SEG_SLOTS} 段 × {seg_bytes} B")
    print(f"  第 1 段头 4 B（SegType／MotionMode／BlendMode／Reserved1）= {first[:SEG_HEAD_BYTES].hex(' ')}")
    print(f"  第 1 段前 {used} 个轴位 REAL = {first[SEG_HEAD_BYTES:SEG_HEAD_BYTES + used * 4].hex(' ')}")
    tail = first[SEG_HEAD_BYTES + used * 4:SEG_HEAD_BYTES + slots * 4]
    idle = payload[seg_bytes * len(PATH):]
    print(f"  第 1 段第 {used}–{slots - 1} 槽位（本段未驱动）= {tail.hex(' ') or '（无）'} → 全 0 = {not any(tail)}")
    print(f"  第 {len(PATH) + 1}–{SEG_SLOTS} 段（未用段）共 {len(idle)} B → 全 0 = {not any(idle)}")
    print(f"  逆运算核对：解回第 1 段 pos = {unpack_segments(payload, slots, 1)[0].pos}")
    check(results, "A",
          seg_bytes == EXPECTED_SEG_BYTES and len(payload) == EXPECTED_SEG_BYTES * SEG_SLOTS
          and not any(tail) and not any(idle),
          f"段长 {seg_bytes} B／整批 {len(payload)} B／未用轴位与未用段全 0")


def run_live(cfg, results: dict, want) -> None:
    child = Child(free_endpoint(), CONFIG, cwd=REPO_ROOT)
    try:
        if not child.wait_ready():
            for section in filter(want, ("B", "C", "E")):
                check(results, section, False, "模拟器子进程未起来（日志见上）")
            return
        asyncio.run(_live(child, cfg, results, want))
    finally:
        child.stop()
        child.dump()


async def _live(child, cfg, results: dict, want) -> None:
    frames, states = [], []          # 收到的帧／链路态回调，B／C／E 三节都从这里取数
    session = await connect(child.endpoint, cfg, on_frames=frames.extend, on_state=states.append)
    print(f"  客户端已连 {session.endpoint}，链路态 = {session.link_state.value}")
    try:
        if want("B"):
            await measure_frequency(child, session, frames, cfg, results)
        if want("C"):
            await handshake(session, results)
        if want("E"):
            await offline_after_kill(child, session, states, results)
    finally:
        await session.close()


async def measure_frequency(child, session, frames: list, cfg, results: dict) -> None:
    """完成标准第 1／3 条＋步骤 5：连上后读 ``READ_SECONDS``，用「心跳计数 对 客户端时刻」的回归斜率定频率。

    ⚠️ 两处偏离卡面字面写法，均为实测所逼、原始数字一律照贴。**窗口 60 s 而非字面 10 s**：计数法只能数整周期、
    两端又不与服务端周期对齐，故系统性少一周期（60 s 实收 1199 帧／标称 1200 → 19.967 Hz）；端点法（心跳差 ÷
    首末帧跨距）被 asyncua 批量投递的端点抖动主导（帧间隔实测 0／47／125 ms，30 s 上即 ±0.05 Hz）；斜率用全部
    约 1200 点，两轮 60 s 实测 **19.9997／20.0011 Hz**、散布 ±0.002 Hz，故判据取它。**阈值 20 Hz 不下调**，另带
    ``HZ_RESOLUTION`` 量具容差：真值恰为 20.000 Hz，阈值与真值重合时无偏估计量必有一半概率落在其下（pytest 那条
    用 95 % 标称值是怕共享机负载抖动假红；判据归本脚本，故只放这一项由实测散布定出的容差）。子进程每 200 周期打
    一行「扫描自计 …Hz」（只用服务端钟、不经推送），本节贴最后一行作旁证；落后告警次数也打印——低于标称的唯一
    合法成因是某周期被系统拖过一整个周期，扫描按设计重置基准而**不补扫**（补扫＝凭空造周期，同 §9.3-③）。
    """
    print(f"\n[B] 双进程回读频率：客户端读模拟器 {READ_SECONDS:.0f} s")
    nominal = MS_PER_S / cfg.opcua.publish_interval_ms
    stamp0, count0 = time.monotonic(), len(frames)
    while time.monotonic() - stamp0 < READ_SECONDS:
        await asyncio.sleep(0.2)
    window = time.monotonic() - stamp0
    stamps = [frame.t for frame in frames[count0:]]
    beats = [frame.heartbeat for frame in frames[count0:]]
    if len(stamps) < 2:
        check(results, "B", False, f"{window:.1f} s 内只收到 {len(stamps)} 帧，无法统计频率")
        return
    hz = slope(stamps, beats)
    step = max(len(stamps) * int(CARD_SECONDS) // int(READ_SECONDS), 2)   # 卡面 10 s 子窗口的点数
    gaps = sorted(round((b - a) * MS_PER_S, 1) for a, b in zip(stamps, stamps[1:]))
    stalls = sum(STALL_MARK in line for line in child.lines)
    server = next((line for line in reversed(child.lines) if RATE_MARK in line), "")
    print(f"  收帧 {len(stamps)} 帧／窗口 {window:.3f} s（标称 {nominal:.1f} Hz）；"
          f"心跳 {beats[0]}→{beats[-1]}（每周期 +1，§9.1 步骤 7）")
    print(f"  判据＝回归斜率（心跳 对 客户端时刻，全 {len(stamps)} 点）→ **{hz:.4f} Hz**；通过线 "
          f"{MIN_HZ:.0f} − {HZ_RESOLUTION:.2f}（量具容差）＝ {MIN_HZ - HZ_RESOLUTION:.2f} Hz")
    print(f"  对照：端点法 {(beats[-1] - beats[0]) / (stamps[-1] - stamps[0]):.4f} Hz、计数法 "
          f"{len(stamps) / window:.4f} Hz、卡面 {CARD_SECONDS:.0f} s 子窗口斜率 "
          f"{slope(stamps[:step], beats[:step]):.4f} Hz")
    print(f"  帧间隔 最小／中位／最大 = {gaps[0]:.1f}／{gaps[len(gaps) // 2]:.1f}／{gaps[-1]:.1f} ms；"
          f"服务端扫描落后告警 {stalls} 次（不补扫，故会真少几帧）")
    print(f"  服务端自计（只用服务端钟、不经推送）：{server.split(': ', 1)[-1] or '（本轮未满 200 周期）'}")
    check(results, "B", hz >= MIN_HZ - HZ_RESOLUTION and session.link_state is LinkState.ONLINE,
          f"实测 {hz:.4f} Hz ≥ 通过线 {MIN_HZ - HZ_RESOLUTION:.2f} Hz（阈值 {MIN_HZ:.0f} Hz 减量具容差），"
          f"链路态 {session.link_state.value}")


async def handshake(session, results: dict) -> None:
    """完成标准第 1 条：九步握手跑到 ST_DONE，回读位置与目标点对得上。"""
    print(f"\n[C] 九步握手：下发 {len(PATH)} 段（倍率 {SPEED_OVERRIDE:.0f} %）→ LOAD → START → ST_DONE")
    began = time.monotonic()
    frame = await session.run(PATH, speed_override=SPEED_OVERRIDE)
    goal = PATH[-1].pos
    print(f"  用时 {time.monotonic() - began:.2f} s；SeqID={frame.seq_id} CurSeg={frame.cur_seg} "
          f"status=0x{frame.status:02x} heartbeat={frame.heartbeat}")
    print(f"  回读 Pos = {tuple(round(v, 3) for v in frame.pos)}")
    print(f"  目标 Pos = {goal}（其后 {len(frame.pos) - len(goal)} 个槽位未驱动，应为 0）")
    print(f"  回读 Vel = {tuple(round(v, 3) for v in frame.vel)}（DONE 时应全 0）")
    hit = all(abs(frame.pos[index] - value) <= TOL_MM for index, value in enumerate(goal))
    idle_zero = not any(frame.pos[len(goal):])
    check(results, "C", frame.done and hit and idle_zero and not any(frame.vel),
          f"ST_DONE={frame.done}，{len(goal)} 个驱动轴位到达目标（误差 ≤{TOL_MM} mm）"
          f"＝{hit}，未驱动槽位为 0＝{idle_zero}，速度归零＝{not any(frame.vel)}")


async def offline_after_kill(child, session, states: list, results: dict) -> None:
    """完成标准第 4 条：``kill`` 模拟器子进程 → 客户端 5 s 内判离线并回调状态。"""
    print("\n[E] 断进程判离线：kill 模拟器子进程后计时")
    states.clear()
    killed = time.monotonic()
    child.kill()
    while time.monotonic() - killed < OFFLINE_LIMIT_S + 2.0 and LinkState.OFFLINE not in states:
        await asyncio.sleep(0.05)
    took = time.monotonic() - killed
    print(f"  判离线用时 **{took:.2f} s**（阈值 {OFFLINE_LIMIT_S:.1f} s），状态回调序列 = "
          f"{[state.value for state in states]}")
    held = session.last_frame and tuple(round(v, 3) for v in session.last_frame.pos)
    print(f"  降级期间 last_frame 原样保留、不外推：帧数停在 {session.frame_count}，末帧 Pos = {held}")
    check(results, "E", LinkState.OFFLINE in states and took <= OFFLINE_LIMIT_S,
          f"{took:.2f} s 内判 OFFLINE 并回调（阈值 {OFFLINE_LIMIT_S:.1f} s）")


def section_d(cfg, results: dict) -> None:
    """步骤 5：子进程带 ``--fault reject`` 起 → 客户端须收到 ACK_LOAD_NG 与 §6.4 原因码。"""
    print("\n[D] 注入拒绝异常：子进程 --fault reject，客户端下发同一条路径")
    child = Child(free_endpoint(), CONFIG, fault=FAULT_REJECT, cwd=REPO_ROOT)
    try:
        if child.wait_ready():
            asyncio.run(_rejected(child, cfg, results))
        else:
            check(results, "D", False, "模拟器子进程未起来（日志见上）")
    finally:
        child.stop()
        child.dump()


async def _rejected(child, cfg, results: dict) -> None:
    session = await connect(child.endpoint, cfg)
    try:
        await session.load(PATH)
        check(results, "D", False, "装载竟然通过了——故障注入未生效")
    except LoadRejected as caught:
        print(f"  客户端收到：{caught}")
        print(f"  原因码（§6.4 报警字）= 0x{caught.alarm:04x} → 中文说明 = {'、'.join(caught.reasons)}")
        check(results, "D", bool(caught.reasons), f"被拒且带原因位：{'、'.join(caught.reasons)}")
    finally:
        await session.close()


def section_f(results: dict) -> None:
    """完成标准第 5 条：NodeId 整体改名（DB 名＋符号名）后子进程复跑，代码零改动。"""
    print(f"\n[F] 换点表零改码：{len(RENAMES)} 组改名后子进程复跑")
    text = CONFIG.read_text(encoding="utf-8")
    for old, new in RENAMES:
        text = text.replace(old, new)
    with tempfile.TemporaryDirectory() as scratch:      # 改名件落仓外临时目录，不入库
        swapped = pathlib.Path(scratch) / "machine_swapped.yaml"
        swapped.write_text(text, encoding="utf-8")
        cfg = load_machine(str(swapped))
        print("  改名后的 NodeId（取自加载结果，非手抄；两张表分开遍历——「seq_id」两边都有同名键）：")
        for table in (cfg.opcua.read_nodes, cfg.opcua.write_nodes):
            for key, value in table.items():
                items = value if isinstance(value, (list, tuple)) else (value,)
                print(f"    {key:<11} {items[0]}{' …' if len(items) > 1 else ''}（{len(items)} 个）")
        child = Child(free_endpoint(), swapped, cwd=REPO_ROOT)
        try:
            ok = child.wait_ready() and asyncio.run(_swap_probe(child, cfg))
        finally:
            child.stop()
            child.dump()
    check(results, "F", ok, "另一份点表、代码零改动，回读照跑（详见子进程日志）")


async def _swap_probe(child, cfg) -> bool:
    frames: list = []
    session = await connect(child.endpoint, cfg, on_frames=frames.extend)
    try:
        await asyncio.sleep(2.0)
        frame = await session.run(PATH, speed_override=SPEED_OVERRIDE)
    finally:
        await session.close()
    print(f"  改名点表下 2 s 收帧 {len(frames)} 个，握手到 ST_DONE（CurSeg={frame.cur_seg}）")
    return len(frames) >= 20 and frame.done


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="T09 双进程自测取证（仅 127.0.0.1 自环）")
    parser.add_argument("--only", default="", help=f"只跑指定节，逗号分隔（可选 {'/'.join(SECTIONS)}）")
    parser.add_argument("--no-save", action="store_true", help="只上屏，不落 evidence/T09/selftest.txt")
    args = parser.parse_args(argv)
    force_utf8_stdout()
    picked = [part.strip().upper() for part in args.only.split(",") if part.strip()] or list(SECTIONS)
    if unknown := [part for part in picked if part not in SECTIONS]:
        print(f"未知节：{'、'.join(unknown)}（可选 {'/'.join(SECTIONS)}）")
        return 1
    want = picked.__contains__
    results: dict[str, bool] = {}
    cfg = load_machine(str(CONFIG))
    with recording(None if args.no_save else OUTPUT):
        print("=" * 72)
        print(f"T09 双进程自测取证　{time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  python {sys.version.split()[0]} @ {sys.executable}")
        print(f"  配置 {CONFIG}（pack_profile={cfg.opcua.pack_profile}，"
              f"周期 {cfg.opcua.publish_interval_ms} ms，ns={cfg.opcua.ns_index}）")
        print(f"  所选节：{'、'.join(picked)}")
        guarded(results, "A", lambda: want("A") and section_a(cfg, results))
        if any(want(section) for section in ("B", "C", "E")):
            guarded(results, "BCE", lambda: run_live(cfg, results, want))
        guarded(results, "D", lambda: want("D") and section_d(cfg, results))
        guarded(results, "F", lambda: want("F") and section_f(results))
        marks = {True: "PASS", False: "FAIL", None: "未出结论"}
        failed = [item for item in picked if results.get(item) is not True]
        verdict = (f"{len(picked)} 节全 PASS（数字均为实测，非估算）" if not failed
                   else f"{len(failed)} 节未通过：" + "、".join(failed))
        print("\n" + "=" * 72)
        print("  " + "　".join(f"{item}＝{marks[results.get(item)]}" for item in picked))
        print(f"结论：{verdict}　取证物：{'（--no-save，未落盘）' if args.no_save else OUTPUT}")
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
