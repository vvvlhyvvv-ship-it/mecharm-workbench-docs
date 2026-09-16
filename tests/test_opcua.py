"""tests/test_opcua.py —— T09「OPC UA 桥与模拟器」测试。

覆盖 T09 卡完成标准里能在单进程内测的四条：段长实测 56 B（第 2 条）、回读频率（第 3 条）、断链后 5 s 内
判离线（第 4 条）、换点表零改码（第 5 条）。第 1 条「双进程日志一致」与第 6 条 commit 归
``tools/comm_selftest.py`` 出证据（落 ``evidence/T09/``）。

⚠️ 本仓**没有** ``pytest-asyncio``（``requirements.lock.txt`` 实测只有 pytest／anyio），故自环用例一律用
``asyncio.run`` 驱动，不为此引新依赖（T09 禁自行装包／改环境文件）。

⚠️ 频率一条在本文件里只断言**节拍本身**，平均频率的严格判定归 ``tools/comm_selftest.py``（理由见该用例）。

夹具规矩（多 worktree 通用）：**不写死仓内绝对路径**——现场配置由 ``REPO_ROOT`` 推，改名后的点表在
``tmp_path`` 里现场生成（仓根随 worktree／合并位置变化，写死即假通过）。
"""

from __future__ import annotations

import ast
import asyncio
import pathlib
import socket
import time

import pytest
from asyncua import ua

import comm
import comm.opcua_client as api
from comm.opcua_client import (ALARM_LIMIT, AckTimeout, CommError, LinkState, LoadRejected,
                               MOTION_REL, ReadbackBuffer, Segment, Session, WRITE_NODE_TYPES,
                               apply_security, axis_slots_of, connect, describe_alarm,
                               pack_segments, seg_layout, unpack_segments)
from comm.plc_nodes import PUBLISH_NODE_TYPES, split_symbol
from comm.simulator import PlcSimulator
from comm.virtual_motion import Move, build_plan, clamp_speeds
from core.config import REPO_ROOT, load_machine

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
MINIMAL = load_machine(str(FIXTURES / "ok_minimal.yaml"))
LIVE = REPO_ROOT / "config" / "machine.yaml"
PATH = (Segment(pos=(120.0, 30.0), vel=200.0, acc=800.0, dec=800.0),
        Segment(pos=(240.0, -15.0), vel=200.0, acc=800.0, dec=800.0, dwell_ms=100))
SLOTS = axis_slots_of(MINIMAL.opcua.pack_profile)
NOMINAL_HZ = 1000.0 / MINIMAL.opcua.publish_interval_ms
# 换点表演示：只改 NodeId 里的符号名（DB 名与变量名全换），配置键与代码一律不动。
RENAMES = (("DB_PLC_to_SW", "DB_Auf"), ("DB_SW_to_PLC", "DB_Ab"), ("SegCount", "Anzahl"),
           ("SpeedOverride", "Ueberfahrt"), ("AlarmWord", "Alarme"), ("Heartbeat", "Puls"),
           ("CurSeg", "SegmentNr"), ("Status", "Zustand"), ("SeqID", "Folge"), ("Ack", "Quitt"),
           ("Cmd", "Befehl"), ("Pos[", "P["), ("Vel[", "V["), ('"Seg"', '"Segmente"'))


class _Stub:
    """假节点：``ReadbackBuffer`` 只用到 ``nodeid.to_string()``，故一个属性就够。"""

    def __init__(self, nodeid: ua.NodeId) -> None:
        self.nodeid = nodeid


def stub(key: str, index: int = 0) -> _Stub:
    """按配置里的 NodeId 字符串造假节点（实测 ``to_string()`` 与配置逐字相同，故反查必命中）。"""
    items = MINIMAL.opcua.read_nodes[key]
    return _Stub(ua.NodeId.from_string(items[index] if isinstance(items, tuple) else items))


def variant(tmp_path: pathlib.Path, renames) -> pathlib.Path:
    """在 tmp_path 里生成改过名的配置样例，返回路径（不碰仓内文件）。"""
    text = (FIXTURES / "ok_minimal.yaml").read_text(encoding="utf-8")
    for old, new in renames:
        text = text.replace(old, new)
    out = tmp_path / "machine.yaml"
    out.write_text(text, encoding="utf-8")
    return out


def run_loop(body, cfg=MINIMAL, **link):
    """把用例体跑在「模拟器＋客户端」自环里；``link`` 透传给 ``connect``（on_frames／on_state 等）。"""
    async def driver():
        with socket.socket() as probe:            # 取空闲端口，避免与常驻模拟器抢 4840
            probe.bind(("127.0.0.1", 0))
            url = f"opc.tcp://127.0.0.1:{probe.getsockname()[1]}"
        sim = PlcSimulator(cfg, url)
        await sim.start()
        try:
            sess = await connect(url, cfg, **link)
            try:
                return await body(sim, sess)
            finally:
                await sess.close()
        finally:
            await sim.stop()
    return asyncio.run(driver())


def test_seg_length_is_measured_56_bytes():
    assert seg_layout(SLOTS)[1] == 56                    # §5.2 每段 56 字节
    payload = pack_segments(PATH, SLOTS)
    assert len(payload) == 560                           # §5.1 ARRAY[0..9] OF ST_Seg
    assert payload[:4] == bytes(4)                       # SegType/MotionMode/BlendMode/Reserved1
    assert payload[56:60] == bytes(4)                    # 第二段头部同样从 0 起


def test_pack_roundtrip_and_zero_fill():
    back = unpack_segments(pack_segments(PATH, SLOTS), SLOTS, len(PATH))
    assert back[0].pos[:2] == (120.0, 30.0)
    assert all(value == 0.0 for value in back[0].pos[2:])    # §5.2 未使用轴位一律填 0
    assert (back[1].dwell_ms, back[1].vel) == (100, 200.0)


def test_pack_rejects_out_of_range_input():
    with pytest.raises(ValueError, match="分批下发"):
        pack_segments([Segment()] * 11, SLOTS)
    with pytest.raises(ValueError, match="槽位"):
        pack_segments([Segment(pos=(0.0,) * (SLOTS + 1))], SLOTS)
    with pytest.raises(ValueError, match="§5.1"):
        unpack_segments(b"", SLOTS)


def test_unfrozen_profile_refuses_to_pack_or_connect(tmp_path):
    with pytest.raises(CommError, match="尚未冻结"):
        axis_slots_of("v1_3_24axis")
    grown = variant(tmp_path, (("pack_profile: v1_2_8axis", "pack_profile: v1_3_24axis"),))
    with pytest.raises(CommError, match="尚未冻结"):
        Session("", load_machine(str(grown)))


def test_describe_alarm_and_rejected_carry_reasons():
    assert describe_alarm(0) == ()
    assert describe_alarm(ALARM_LIMIT) == ("软限位超程",)
    caught = LoadRejected(ALARM_LIMIT, 7)
    assert isinstance(caught, CommError) and caught.seq_id == 7
    assert "软限位超程" in str(caught) and "装载" in str(caught)


def test_type_tables_cover_every_config_key():
    assert set(PUBLISH_NODE_TYPES) == set(MINIMAL.opcua.read_nodes)
    assert set(WRITE_NODE_TYPES) == set(MINIMAL.opcua.write_nodes)
    assert set(PUBLISH_NODE_TYPES) == set(load_machine(str(LIVE)).opcua.read_nodes)


def test_buffer_maps_config_keys_onto_frame_slots():
    seen: list = []
    buffer = ReadbackBuffer(MINIMAL.opcua.read_nodes, on_frames=seen.extend)
    for key, items in MINIMAL.opcua.read_nodes.items():
        if key == "heartbeat":
            continue
        for index, item in enumerate(items if isinstance(items, tuple) else (items,)):
            buffer.datachange_notification(_Stub(ua.NodeId.from_string(item)),
                                           3.5 if key.startswith("axis") else index + 1, None)
    assert seen == []                                    # 节拍键未到，不出帧
    buffer.datachange_notification(stub("heartbeat"), 9, None)
    assert len(seen) == 1
    frame = seen[0]
    assert (frame.heartbeat, frame.seq_id, frame.cur_seg) == (9, 1, 1)
    assert frame.pos[1] == 3.5 and frame.vel[7] == 3.5


def test_buffer_refuses_to_extrapolate_and_reset_keeps_watchdog_hungry():
    hits: list = []
    buffer = ReadbackBuffer(MINIMAL.opcua.read_nodes, on_rx=lambda: hits.append(1))
    buffer.datachange_notification(stub("heartbeat"), 1, None)
    assert buffer.emit() is None and buffer.last_frame is None   # §9.3-③ 宁可少一帧
    buffer.seed("status", [1])
    assert len(hits) == 2                        # seed＝重连后主动读回的真数据，须刷新新鲜度基准
    buffer.reset()
    assert len(hits) == 2 and buffer.value("status") is None     # 清快照不算「收到数据」


def test_code_contains_no_plc_symbol_literals():
    """``comm/`` 里不得出现 PLC 符号名字面量（完成标准第 5 条「换点表零改码」的前提）。

    只比对**非 docstring** 的字符串常量：docstring／注释里点名符号名属口径说明（plc_nodes 自己就要举例
    ``"DB_PLC_to_SW"."Pos[0]"``），连 docstring 一起比必假红——实测即此。
    """
    banned = ("DB_PLC_to_SW", "DB_SW_to_PLC", "Pos[0]", "SpeedOverride")
    holders = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
    for path in sorted(pathlib.Path(comm.__file__).parent.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        docs = {id(h.body[0].value) for h in ast.walk(tree)
                if isinstance(h, holders) and h.body and isinstance(h.body[0], ast.Expr)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) \
                    and id(node) not in docs:
                assert not any(w in node.value for w in banned), f"{path.name} 写死了 {node.value!r}"


def test_package_root_reexports_whole_api():
    assert api.__all__ and not [name for name in api.__all__ if not hasattr(api, name)]
    assert (connect, Segment, PlcSimulator) == (api.connect, api.Segment, PlcSimulator)


def test_split_symbol_and_security_policy():
    assert split_symbol('ns=3;s="DB_PLC_to_SW"."Pos[0]"') == ("DB_PLC_to_SW", "Pos[0]")
    assert split_symbol("ns=3;s=Bare") == ("", "Bare")
    with pytest.raises(CommError, match="电Q-2"):
        apply_security(object(), "Basic256Sha256")


def test_trapezoid_clamps_both_ends_and_never_extrapolates():
    move = Move.build(10.0, 110.0, 200.0, 500.0, 500.0)
    assert move.at(-1.0) == (10.0, 0.0)
    assert move.at(move.total) == (110.0, 0.0)
    assert move.at(move.total * 3) == (110.0, 0.0)       # §9.3-③ 超时不外推
    middle, speed = move.at(move.total / 2)
    assert 10.0 < middle < 110.0 and speed > 0.0


def test_trapezoid_degenerates_when_peak_unreachable():
    short = Move.build(0.0, 1.0, 1000.0, 10.0, 10.0)
    assert short.cruise_t == 0.0 and short.peak < 1000.0
    still = Move.build(5.0, 5.0, 100.0, 10.0, 10.0)
    assert still.total == 0.0 and still.at(9.9) == (5.0, 0.0)


def test_plan_accumulates_relative_targets_and_dwell():
    plan = build_plan(PATH, [0.0] * SLOTS, 100.0, MINIMAL.limits)
    assert len(plan) == 2 and plan[1].duration > plan[1].moves[0].total   # 含 DwellMS
    relative = build_plan((Segment(pos=(10.0,), motion_mode=MOTION_REL),
                           Segment(pos=(10.0,), motion_mode=MOTION_REL)),
                          [0.0] * SLOTS, 100.0, MINIMAL.limits)
    assert relative[1].moves[0].end == 20.0


def test_clamp_takes_limits_from_config_not_literals():
    limits = MINIMAL.limits
    assert clamp_speeds(Segment(vel=1e6, acc=1e6, dec=1e6), 100.0, limits) == (
        limits.speed_max_mm_s, limits.accel_max_mm_s2, limits.accel_max_mm_s2)
    assert clamp_speeds(Segment(vel=40.0), 50.0, limits)[0] == 20.0       # 倍率 50% 折速


def test_selfloop_handshake_runs_to_done():
    async def body(sim, sess):
        frame = await sess.run(PATH)
        assert frame.done and not frame.running
        assert frame.seq_id == sess.seq_id               # §6.1 SeqID 回显一致
        assert frame.cur_seg == len(PATH) - 1
        assert frame.pos[0] == pytest.approx(240.0) and frame.pos[1] == pytest.approx(-15.0)
        assert frame.pos[2:] == (0.0,) * (SLOTS - 2)
    run_loop(body)


def test_readback_frequency_holds_nominal_cadence():
    """节拍＝``publish_interval_ms``：每帧带新心跳、帧间隔**中位数**贴合标称周期（±20 %）。

    不断言「平均 ≥20 Hz」：平均值的分母是墙钟，共享机把某周期拖过一整个周期时（全套连跑实测过一次 466 ms）
    扫描按设计重置基准而**不补扫**（补扫＝凭空造周期，同 §9.3-③），那几个周期就真没了，3 s 窗口上平均值会掉到
    16.7 Hz——环境负载而非代码缺陷。严格「≥20 Hz」归 ``tools/comm_selftest.py``（60 s 窗口＋服务端自计旁证）。
    """
    seen: list = []
    async def body(sim, sess):
        await asyncio.sleep(0.5)
        seen.clear()
        await asyncio.sleep(3.0)
    run_loop(body, on_frames=seen.extend)
    stamps = [frame.t for frame in seen]
    beats = [frame.heartbeat for frame in seen]
    gaps = sorted(later - earlier for earlier, later in zip(stamps, stamps[1:]))
    assert len(stamps) > NOMINAL_HZ                              # 确有一串帧，不是空窗
    assert all(now < nxt for now, nxt in zip(beats, beats[1:]))  # 每帧都带新心跳，无重复帧
    assert abs(gaps[len(gaps) // 2] - 1 / NOMINAL_HZ) <= 0.2 / NOMINAL_HZ   # 中位间隔贴合标称周期


def test_load_rejected_reports_alarm_reason():
    async def body(sim, sess):
        sim.inject_fault("reject", alarm=ALARM_LIMIT)
        with pytest.raises(LoadRejected, match="软限位超程"):
            await sess.load(PATH)
    run_loop(body)


def test_ack_timeout_when_plc_swallows_ack():
    async def body(sim, sess):
        sim.inject_fault("timeout", cycles=200)
        with pytest.raises(AckTimeout):
            await sess.load(PATH)
    run_loop(body)


def test_offline_is_judged_within_5s(tmp_path):
    states: list = []

    async def body(sim, sess):
        await asyncio.sleep(0.3)
        began = time.monotonic()
        sim.inject_fault("disconnect")
        while LinkState.OFFLINE not in states and time.monotonic() - began < 6.0:
            await asyncio.sleep(0.05)
        return time.monotonic() - began
    elapsed = run_loop(body, on_state=states.append)
    assert LinkState.OFFLINE in states and elapsed < 5.0     # 完成标准第 4 条


def test_swapped_node_table_needs_zero_code_change(tmp_path):
    cfg = load_machine(str(variant(tmp_path, RENAMES)))
    assert cfg.opcua.read_nodes["status"].endswith('"Zustand"')

    async def body(sim, sess):
        frame = await sess.run(PATH)
        assert frame.done and frame.pos[0] == pytest.approx(240.0)
    run_loop(body, cfg=cfg)
