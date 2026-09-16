"""tests/test_path.py —— T07 路径生成测试（卡片步骤 6 的**承重用例**在此）。

覆盖：① 3 点折线的段数／长度／时长与手算逐位一致（点位型与轮廓型各一遍）② 越界点注入→该段
`blocked` 且汇总 `ok=False`（卡片完成标准②：红段＋无法进入④）③ `blending` 默认 False 且只随段
携带（完成标准③，电Q-8 回执前不切）④ 汇总行人话文案 ⑤ 关节目标能被 fk 复算回端点（表格与视口
同源，禁前端自行换算）⑥ 模型框→设备框在 ik 之前施加、而段内端点仍是模型坐标
⑦ 常驻守卫（core/path.py 运行期无 GUI／OCC／numpy／comm；轴参数数值全在配置里）。

⚠️ 数值断言用现场 `config/machine.yaml` 的**占位**链（行程 [0,1000]、速度 300／50／500）——它是
本单要对齐的真实配置源；但占位值不得当成机台事实对外承诺可达性（踏勘第 3／7 项待回执）。
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import pathlib

import pytest

from core.config import REPO_ROOT, Axis, Coupling, Link, load_machine
from core.geometry.face_point import Waypoint
from core.kinematics import (PRISMATIC, CoordFrame, axis_swap_frame, derive_chain, fk,
                             model_to_device, resolve_positions)
from core.path import KIND_CONTOUR, KIND_POINT, gen_path, summarize

MINIMAL = pathlib.Path(__file__).resolve().parent / "fixtures" / "ok_minimal.yaml"
PATH_SOURCE = (REPO_ROOT / "core" / "path.py").read_text(encoding="utf-8")
SITE_CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
SITE_CHAIN = derive_chain(SITE_CFG)
# 模型框与设备框重合（契约 §7.1 的原点／轴向两条均「待确认」⇒ frame 一律显式给、无默认值）
FRAME = axis_swap_frame({"x": "+x", "y": "+y", "z": "+z"})
# 现场链上沿 x 动的轴（配置现取，⛔ 不写死轴号）：把手算的工程位置合计与 ik 的解对齐用
X_AXES = [link.axis for link in SITE_CFG.links if link.motion == "x" and link.axis]
FORBIDDEN_ROOTS = ("PySide6", "Qt", "OCC", "numpy", "comm", "app", "view")


def _wp(index, x_mm, y_mm, z_mm, normal=(0.0, 0.0, 1.0)):
    """造一个点位（T06 的 `Waypoint`）：name 按 P1… 排，source_face 用不上故填 index。"""
    return Waypoint(index, f"P{index}", (float(x_mm), float(y_mm), float(z_mm)), normal, index)


def _axis(axis_id, span, join=None):
    """造一根合成移动副轴（占位零点／正方向 +1／无比例系数）。"""
    return Axis(axis_id, PRISMATIC, "trajectory", tuple(span), 0.0, 1, None, join, False)


def _cfg(axes, links):
    """换掉 ok_minimal 的 axes／links 两节（其余节不参与本单，沿用夹具）。"""
    return dataclasses.replace(load_machine(str(MINIMAL)),
                               axes={item.id: item for item in axes}, links=links)


def _eng_x(joints):
    """一组关节输入在现场链上合成的 x 向工程位置合计（mm）——倍速轴按配置换算后再加。"""
    positions = resolve_positions(joints, SITE_CFG)
    return sum(positions[axis_id] for axis_id in X_AXES)


# ── 手算基准（3 点折线，单位 mm）：P1(0,0,0) → P2(300,0,0) → P3(300,400,0) ────────────────
#    段 1 长 300、段 2 长 400（直角折线，欧氏距离即直角边）；总长 700 mm＝0.700 m。
#    点位型速度 = min(speed_rapid 300, speed_max 500) = 300 mm/s ⇒ 时长 1.0 s／1.3333 s、合计 2.3 s
#    轮廓型速度 = min(speed_work 50, speed_max 500) = 50 mm/s ⇒ 时长 6.0 s／8.0 s、合计 14.0 s
POINTS_3 = [_wp(1, 0, 0, 0), _wp(2, 300, 0, 0), _wp(3, 300, 400, 0)]
POINT_TABLE = [("JOINT", 300.0, 300.0, 1.0), ("JOINT", 400.0, 300.0, 4.0 / 3.0)]
CONTOUR_TABLE = [("LINE", 300.0, 50.0, 6.0), ("LINE", 400.0, 50.0, 8.0)]

# ── 合成链（校核两道关卡用）：base → slide_a(SA,x，行程只到 10) → slide_b(SB,x) ──────────
#    手算：目标 x=100 ⇒ SA 被钉在上界 10、SB 取 90（Σ=100）⇒ 双驱同步偏差 80 mm > 容差 0.5 mm
#    ⇒ 该段必须由 `check_limits`（T04）判红，而不是 ik 自己判——ik 只保证在行程内选解。
SYNC = Coupling("sync", "gantry_travel", 0.5)
AXES_SYNC = (_axis("SA", (0.0, 10.0), SYNC), _axis("SB", (0.0, 1000.0), SYNC))
LINKS_SYNC = (Link("base", 0.0, None, None, None), Link("slide_a", 0.0, "base", "SA", "x"),
              Link("slide_b", 0.0, "slide_a", "SB", "x"))
CFG_SYNC = _cfg(AXES_SYNC, LINKS_SYNC)
CHAIN_SYNC = derive_chain(CFG_SYNC)
# 另加一根**不在链上**、行程下界 > 0 的轴：全零位即越界 ⇒ 用来走 travel 那一条描述分支
CFG_PARK = _cfg(AXES_SYNC + (_axis("PARK", (200.0, 800.0)),), LINKS_SYNC)
CHAIN_PARK = derive_chain(CFG_PARK)


def _table(segments):
    """把段序列压成 (类型, 长度, 速度, 时长) 表，便于与手算表逐行对。"""
    return [(seg.type, seg.length_mm, seg.speed_mm_s, seg.duration_s) for seg in segments]


def test_three_point_polyline_matches_the_hand_computed_table():
    """承重用例①：3 点 ⇒ 2 段，段型／长度／速度／时长与纸面手算逐位一致（点位型）。"""
    segments = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)
    assert len(segments) == 2
    for got, want in zip(_table(segments), POINT_TABLE):
        assert got[0] == want[0] and got[1] == pytest.approx(want[1], abs=1e-9)
        assert got[2] == pytest.approx(want[2], abs=1e-9)
        assert got[3] == pytest.approx(want[3], abs=1e-9)


def test_contour_kind_switches_segment_type_and_work_speed():
    """承重用例①：同一组点位切到轮廓型 ⇒ 段型 LINE、速度取作业速度、时长按手算放大 6 倍。"""
    segments = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME, kind=KIND_CONTOUR)
    for got, want in zip(_table(segments), CONTOUR_TABLE):
        assert got[0] == want[0] and got[1] == pytest.approx(want[1], abs=1e-9)
        assert got[2] == pytest.approx(want[2], abs=1e-9)
        assert got[3] == pytest.approx(want[3], abs=1e-9)


def test_summary_line_reads_in_plain_words():
    """用例④：汇总行文案（右栏直接上屏，禁术语 02 §2）——总长换 m 三位、节拍一位。"""
    assert summarize(gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)).describe() == \
        "共 2 段 · 总长 0.700 m · 预估节拍 2.3 s"
    assert summarize(gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME, KIND_CONTOUR)).describe() == \
        "共 2 段 · 总长 0.700 m · 预估节拍 14.0 s"


def test_summary_gates_step_four_on_both_count_and_blockage():
    """用例④：`ok` ＝有段且无阻断段——空路径不点亮步骤④，有阻断段也不点亮（完成标准②）。"""
    assert summarize([]).ok is False
    assert summarize(gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)).ok is True
    broken = gen_path([_wp(1, 0, 0, 0), _wp(2, 5000, 0, 0)], SITE_CFG, SITE_CHAIN, FRAME)
    assert summarize(broken).ok is False


def test_unreachable_point_blocks_both_neighbouring_segments():
    """承重用例②：注入越界点 P2=(5000,0,0) ⇒ 相邻两段都 blocked，原因含轴名与行程合计。

    点位为两段共用，故一个坏点标红**两段**（只标一段会让用户以为换个方向就能过）。
    """
    points = [_wp(1, 0, 0, 0), _wp(2, 5000, 0, 0), _wp(3, 300, 400, 0)]
    summary = summarize(segments := gen_path(points, SITE_CFG, SITE_CHAIN, FRAME))
    assert [seg.blocked for seg in segments] == [True, True]
    assert summary.blocked_count == 2 and summary.count == 2
    assert "合不出 5000 mm" in segments[0].reason and "[0, 3000] mm" in segments[0].reason
    assert "⛔ 2 段不可达" in summary.describe()
    # 坏点 P2 不可解 ⇒ 段 1 的终点侧与段 2 的起点侧都是空表；可解的那一侧仍带关节目标
    # （判红只禁该段参与结果确认，不等于把已解出的数据丢掉——右栏还要拿它显示哪一端是坏的）。
    assert segments[0].joints_start and segments[0].joints_end == {}
    assert segments[1].joints_start == {} and segments[1].joints_end


def test_dual_drive_sync_spread_is_caught_by_the_limits_check():
    """用例②：ik 解在行程内、但双驱同步偏差超容差 ⇒ 仍须判红（禁发判据以 check_limits 为准）。"""
    segments = gen_path([_wp(1, 0, 0, 0), _wp(2, 100, 0, 0)], CFG_SYNC, CHAIN_SYNC, FRAME)
    assert [seg.blocked for seg in segments] == [True]
    assert "双驱 gantry_travel 同步偏差 80 mm 超容差 ±0.5 mm" == segments[0].reason


def test_travel_violation_on_an_off_chain_axis_is_reported_in_plain_words():
    """用例②：travel 那一条描述分支——不在链上的轴全零位即越界（行程下界 > 0）。

    两端点位同因 ⇒ 原因**去重**（同一句话拼两遍只是屏上噪声，用户会以为是两处故障）。
    """
    segments = gen_path([_wp(1, 0, 0, 0), _wp(2, 5, 0, 0)], CFG_PARK, CHAIN_PARK, FRAME)
    assert segments[0].blocked
    assert "轴 PARK 目标 0 mm 超行程 [200, 800] mm" == segments[0].reason


def test_two_different_causes_are_both_kept_in_the_segment_reason():
    """用例②：两端各因不同原因不可达 ⇒ 两条都留、以单个分号分隔（禁只报先遇到的那条）。

    手算：P2 的 x＝5000 超 x 向三轴行程合计 [0,3000]；P3 的 y＝−5000 超 Y1 行程 [0,1000]
    （负方向压根不在行程内）⇒ 段 2 两端都坏，且原因互不相同。
    """
    points = [_wp(1, 0, 0, 0), _wp(2, 5000, 0, 0), _wp(3, 0, -5000, 0)]
    seg = gen_path(points, SITE_CFG, SITE_CHAIN, FRAME)[1]
    assert seg.blocked and seg.reason.count("；") == 1
    assert "合不出 5000 mm" in seg.reason and "合不出 -5000 mm" in seg.reason


def test_speed_is_clamped_by_the_global_maximum():
    """用例③：速度上界钳制——把 speed_max 压到 120 后点位型取 120（时长 300÷120＝2.5 s），
    而轮廓型的 50 本就低于上界 ⇒ 不受影响（钳制只在该段型速度越上界时咬）。"""
    tight = dataclasses.replace(SITE_CFG, limits=dataclasses.replace(
        SITE_CFG.limits, speed_max_mm_s=120.0))
    segments = gen_path(POINTS_3, tight, SITE_CHAIN, FRAME)
    assert segments[0].speed_mm_s == pytest.approx(120.0)
    assert segments[0].duration_s == pytest.approx(2.5, abs=1e-9)
    contour = gen_path(POINTS_3, tight, SITE_CHAIN, FRAME, KIND_CONTOUR)
    assert contour[0].speed_mm_s == pytest.approx(50.0)


def test_blending_defaults_to_false_and_only_rides_along():
    """完成标准③：`blending` 默认 False（电Q-8 回执前不切）；置真只随段携带，不改几何与时长。"""
    off = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)
    on = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME, blending=True)
    assert all(seg.blending is False for seg in off)
    assert all(seg.blending is True for seg in on)
    assert _table(off) == _table(on)


def test_fewer_than_two_points_yields_no_segments():
    """用例⑤：少于两个点位 ⇒ 空表（调用方提示「点位不足」，⛔ 不静默造段、不造零长度段）。"""
    assert gen_path([], SITE_CFG, SITE_CHAIN, FRAME) == []
    assert gen_path([_wp(1, 0, 0, 0)], SITE_CFG, SITE_CHAIN, FRAME) == []
    assert summarize([]).count == 0 and summarize([]).total_length_mm == 0.0


def test_unknown_segment_kind_is_rejected():
    """用例⑤：非法段型 ⇒ ValueError（⛔ 禁静默按点位型处理，那会让作业段跑空程速度）。"""
    with pytest.raises(ValueError, match="kind 应为"):
        gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME, kind="circle")


def test_segment_ids_are_one_based_and_names_follow_the_point_list():
    """用例⑥：段号 1-based、起终点名逐段衔接（右栏「段号｜起点→终点」列与 T08 的 seg_id 同源）。"""
    segments = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)
    assert [seg.id for seg in segments] == [1, 2]
    assert [(seg.start_name, seg.end_name) for seg in segments] == [("P1", "P2"), ("P2", "P3")]


def test_joint_targets_reproduce_the_points_through_fk():
    """承重用例⑤：每段的关节目标喂回 fk，末端平移就是该段终点——表格与视口同源的唯一保证。"""
    for seg in gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME):
        pose = fk(seg.joints_end, SITE_CHAIN.model)[SITE_CHAIN.effective_end]
        assert (pose[3], pose[7], pose[11]) == pytest.approx(seg.end_mm, abs=1e-9)
        assert (pose[3], pose[7], pose[11]) == pytest.approx(
            model_to_device(seg.end_mm, FRAME), abs=1e-9)


def test_frame_is_applied_before_ik_but_segments_stay_in_model_units():
    """用例⑥：设备框相对模型框偏移 1000 mm ⇒ ik 见到的是 1000／1200，而段内端点仍是模型坐标。

    手算：P1 设备 x＝1000、P2 设备 x＝1200，均在 x 向三轴行程合计 [0,3000] 内 ⇒ 可解；
    段长仍是 200（`CoordFrame` 是刚体变换，长度与框无关）。
    """
    shifted = CoordFrame((1000.0, 0.0, 0.0), FRAME.rotation)
    seg = gen_path([_wp(1, 0, 0, 0), _wp(2, 200, 0, 0)], SITE_CFG, SITE_CHAIN, shifted)[0]
    assert _eng_x(seg.joints_start) == pytest.approx(1000.0, abs=1e-9)
    assert _eng_x(seg.joints_end) == pytest.approx(1200.0, abs=1e-9)
    assert seg.length_mm == pytest.approx(200.0, abs=1e-9)
    assert seg.start_mm == (0.0, 0.0, 0.0) and seg.end_mm == (200.0, 0.0, 0.0)


def test_waypoint_normal_does_not_participate():
    """守卫：法向不进目标位姿（模块 docstring ①：现链全移动副、G19 禁自行补链）⇒ 只有 normal
    不同的两组点位，段长／时长／关节目标必须逐位相同。回执补链后本用例应随之改写。"""
    flipped = [_wp(item.id, *item.pos_mm, normal=tuple(-value for value in item.normal))
               for item in POINTS_3]
    plain = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)
    other = gen_path(flipped, SITE_CFG, SITE_CHAIN, FRAME)
    assert [(s.length_mm, s.duration_s, s.joints_end) for s in plain] == \
        [(s.length_mm, s.duration_s, s.joints_end) for s in other]


def test_path_module_keeps_every_axis_number_in_the_config():
    """守卫：core/path.py 无轴参数魔法数字——直接调用常驻复查①的**权威工具**（04 §5.5-①），
    不另写一套判定（两套判定＝两个口径，迟早分家）。"""
    tool = REPO_ROOT / "tools" / "lint_no_magic.py"
    spec = importlib.util.spec_from_file_location("lint_no_magic", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hits, _ = module.scan()
    assert not [hit for hit in hits if hit.startswith("core/path.py")], hits


def test_path_module_has_no_runtime_gui_geometry_or_comm_import():
    """守卫：core/path.py **运行期**不得引 GUI／OCC／numpy／comm（03 §3 铁律：core 单向依赖）。

    只核对模块顶层 import——`if TYPE_CHECKING:` 下的类型引用不产生运行期依赖，故不算命中。
    """
    names = []
    for node in ast.parse(PATH_SOURCE).body:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    hits = sorted(name for name in names if name.split(".")[0] in FORBIDDEN_ROOTS)
    assert not hits, f"core/path.py 运行期依赖越界：{hits}"


def test_segments_are_immutable_so_the_table_cannot_drift_from_the_view():
    """守卫：`Segment`／`PathSummary` 为 frozen dataclass——右栏与视口读同一份不可变数据，
    改一处即抛，杜绝「表格改了、视口没改」的静默不一致（03 §3 单向数据流）。"""
    seg = gen_path(POINTS_3, SITE_CFG, SITE_CHAIN, FRAME)[0]
    with pytest.raises(dataclasses.FrozenInstanceError):
        seg.length_mm = 1.0
    with pytest.raises(dataclasses.FrozenInstanceError):
        summarize([seg]).count = 9
