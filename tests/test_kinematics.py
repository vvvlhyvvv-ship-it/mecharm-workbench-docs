"""tests/test_kinematics.py —— T04 运动学正解与坐标变换测试。

覆盖 T04 卡步骤 6 的四类用例：① 全零位→各部件位姿＝理论值（**两条链都测**：合成链带非零连杆
长度与回转副、现场 `config/machine.yaml` 的占位 0.0 链；纸上链式乘法手算记录见交付汇报）
② 单轴走满行程端点 ③ 越界注入→Violation 命中轴正确 ④ 往返变换误差 <1e-6；另加两型耦合
（sync 超差／ratio 自指驱动级倍速／跨轴覆盖／master 成环拒）、raw_to_eng 三参代数、
build_model 四条校验、CoordFrame 正交归一与镜像拒、行主序→列主序。

⚠️ 合成链与 `SAMPLE_JOINTS` 都是**测试数据、不是机台事实**：「哪根轴驱动哪根连杆、沿哪个
坐标轴动」在 `machine.yaml` 里只存在于注释（03 §4 的字段表无此项），且《踏勘确认清单》第 7
项写明它「决定运动学链的正确定义」＝待回执 ⇒ 绑定一律显式传入，样例只活在本文件。
"""

from __future__ import annotations

import dataclasses
import pathlib

import pytest

from core.config import REPO_ROOT, Axis, Coupling, Link, load_machine
from core.kinematics import (PRISMATIC, REVOLUTE, CoordFrame, Joint, axis_swap_frame, build_model,
                             check_limits, device_to_model, device_to_scene, fk, identity,
                             model_to_device, multiply, raw_to_eng, resolve_positions, rotation,
                             scene_to_device, to_column_major, transform_point, translation)

MINIMAL = pathlib.Path(__file__).resolve().parent / "fixtures" / "ok_minimal.yaml"
SAMPLE_CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
KIND_TRAVEL, KIND_SYNC = "travel", "sync"  # Violation.kind 的两种取值（避开扫描器的字段名口径）

# ── 合成链（手算友好的整数）：base → gantry(X1,x) → column(Z1,z) → head(RA,z,200) ──
#    → tool(无驱动轴,x,100) → tube(X3,x)。X2／L1／L2 故意不绑定连杆：只参与限位与耦合。
DUAL = Coupling("sync", "dual", 0.5)                  # 双驱同步组（容差占位；实机取自配置）
SELF_RATIO = Coupling("ratio", None, None, "X3", 2.0)  # master 自指＝驱动级倍速（X3 口径）


def _axis(axis_id, kind, span, join=None, sign=1, scale=None, zero=0.0):
    """造一根合成轴：span＝行程（移动副 mm／回转副 deg）、join＝耦合、sign＝正方向 ±1、
    scale＝原始值→工程值比例系数（None＝回读已是工程值）、zero＝零点偏移（工程单位）。"""
    return Axis(axis_id, kind, "trajectory", tuple(span), zero, sign, scale, join, False)


SYN_AXES = (_axis("X1", PRISMATIC, (0.0, 500.0)), _axis("Z1", PRISMATIC, (0.0, 300.0)),
            _axis("RA", REVOLUTE, (-90.0, 90.0)), _axis("X2", PRISMATIC, (0.0, 400.0)),
            _axis("X3", PRISMATIC, (0.0, 1000.0), SELF_RATIO),
            _axis("L1", PRISMATIC, (0.0, 100.0), DUAL), _axis("L2", PRISMATIC, (0.0, 100.0), DUAL))
SYN_LINKS = (Link("base", 0.0, None), Link("gantry", 0.0, "base"), Link("column", 0.0, "gantry"),
             Link("head", 200.0, "column"), Link("tool", 100.0, "head"), Link("tube", 0.0, "tool"))
SYN_JOINTS = (Joint("gantry", "x", "X1"), Joint("column", "z", "Z1"), Joint("head", "z", "RA"),
              Joint("tool", "x"), Joint("tube", "x", "X3"))
SYN_ORDER = ("base", "gantry", "column", "head", "tool", "tube")
SYN_CFG = dataclasses.replace(load_machine(str(MINIMAL)),
                              axes={a.id: a for a in SYN_AXES}, links=SYN_LINKS)
SYN = build_model(SYN_CFG, SYN_JOINTS)

# 现场样例的**占位**驱动绑定：依据＝附录A「所属机构」列＋machine.yaml 的 links 注释＋契约
# §7.1（X 建议＝大车行走方向）；踏勘第 7 项回执前不得当真拓扑。X2 名为「机械臂升降架」却按 x
# 动，正是**轴代号字母不能反推运动方向**的实证——故绑定必须是配置／回执给的输入，不是代码推断。
SAMPLE_JOINTS = (
    Joint("gantry", "x", "X1"), Joint("frame", "z", "Z1"), Joint("carriage", "y", "Y1"),
    Joint("arm_lift", "x", "X2"), Joint("arm", "z", "Z2"), Joint("tube3", "x", "X3"),
    Joint("flange", "z"), Joint("mount_a", "y", "YA"), Joint("mount_b", "y", "YB"),
    Joint("mount_c", "y", "YC"), Joint("mount_d", "y", "YD"), Joint("mount_e", "y", "YE"))
SAMPLE_MODEL = build_model(SAMPLE_CFG, SAMPLE_JOINTS)

# 用例①②：(标签, 关节输入, 六根连杆原点的期望值 mm) —— 全部纸上手算，见交付汇报
FK_CASES = [
    ("全零位", {}, ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 200), (100, 0, 200), (100, 0, 200))),
    ("X1上端", {"X1": 500.0}, ((0, 0, 0), (500, 0, 0), (500, 0, 0), (500, 0, 200), (600, 0, 200), (600, 0, 200))),
    ("Z1上端", {"Z1": 300.0}, ((0, 0, 0), (0, 0, 0), (0, 0, 300), (0, 0, 500), (100, 0, 500), (100, 0, 500))),
    ("RA正转90", {"RA": 90.0}, ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 200), (0, 100, 200), (0, 100, 200))),
    ("X3驱动10", {"X3": 10.0}, ((0, 0, 0), (0, 0, 0), (0, 0, 0), (0, 0, 200), (100, 0, 200), (120, 0, 200))),
    ("三轴齐动", {"X1": 500.0, "Z1": 300.0, "RA": 90.0},
     ((0, 0, 0), (500, 0, 0), (500, 0, 300), (500, 0, 500), (500, 100, 500), (500, 100, 500))),
]
LIMIT_CASES = [({}, []), ({"L1": 10.0, "L2": 10.4}, []),
               ({"X1": 600.0}, [(KIND_TRAVEL, "X1", 600.0, (0.0, 500.0), "mm", None)]),
               ({"RA": -120.0}, [(KIND_TRAVEL, "RA", -120.0, (-90.0, 90.0), "deg", None)]),
               ({"X3": 600.0}, [(KIND_TRAVEL, "X3", 1200.0, (0.0, 1000.0), "mm", None)]),
               ({"L1": 10.0, "L2": 11.0}, [(KIND_SYNC, "L2", 1.0, (-0.5, 0.5), "mm", "dual")])]
IDENTITY_FRAME = CoordFrame((0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0))
Y_UP_TO_Z_UP = axis_swap_frame({"x": "+x", "y": "+z", "z": "-y"}, (10.0, 20.0, 30.0))
TILTED = CoordFrame((-5.0, 0.0, 7.5), (1.0, 0.0, 0.0, 0.0, 0.0, -1.0, 0.0, 1.0, 0.0))
OBLIQUE = CoordFrame((2.5, -7.5, 11.0), tuple(rotation("z", 30.0)[i] for i in (0, 1, 2, 4, 5, 6, 8, 9, 10)))


def _origin(pose):
    """取位姿的平移列（行主序下标 3／7／11，mm）。"""
    return pose[3], pose[7], pose[11]


def _hits(cfg, values):
    """把 Violation 摊平成可逐字段断言的元组表（含轴号／值／限值／单位／组）。"""
    return [(h.kind, h.axis_id, h.value, h.limit, h.unit, h.group)
            for h in check_limits(values, cfg)]


# ── 位姿运算与行主序约定 ──────────────────────────────────────────────────────
def test_identity_and_translation_are_row_major():
    """行主序：平移写在每行第 4 列（下标 3／7／11），旋转部分为单位阵。"""
    assert identity() == (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    assert translation(10.0, 20.0, 30.0)[3:12:4] == (10.0, 20.0, 30.0)


def test_multiply_composes_parent_then_child():
    """a∘b：子框 b 的平移先经 a 的旋转、再加 a 的平移（＝fk 逐级累积的口径）。"""
    pose = multiply(translation(0.0, 0.0, 200.0), rotation("z", 90.0))
    assert transform_point(pose, (100.0, 0.0, 0.0)) == pytest.approx((0.0, 100.0, 200.0))


def test_rotation_positive_follows_right_hand_rule():
    """契约 §7.3：右手系 Z 竖直向上，绕 z 转 +90° 把 +x 送到 +y、绕 x 转 +90° 把 +y 送到 +z。"""
    assert transform_point(rotation("z", 90.0), (1.0, 0.0, 0.0)) == pytest.approx((0.0, 1.0, 0.0))
    assert transform_point(rotation("x", 90.0), (0.0, 1.0, 0.0)) == pytest.approx((0.0, 0.0, 1.0))


def test_rotation_rejects_unknown_motion():
    """motion 非法即拒——**禁静默按某个轴处理**（姿态错得看不出来）。"""
    with pytest.raises(ValueError, match="motion"):
        rotation("w", 90.0)


def test_to_column_major_moves_translation_to_tail():
    """three.js `Matrix4.fromArray()` 要列主序：平移由下标 3／7／11 移到 12／13／14。"""
    assert to_column_major(translation(10.0, 20.0, 30.0))[12:15] == (10.0, 20.0, 30.0)


# ── 三坐标系变换（用例④在此）──────────────────────────────────────────────────
def test_axis_swap_turns_y_up_model_into_z_up_device():
    """契约 §7.1 的朝向陷阱：Y-up 模型里「向上 100」换轴后成为设备系「Z 向上 100」＋原点偏移。"""
    assert model_to_device((0.0, 100.0, 0.0), Y_UP_TO_Z_UP) == pytest.approx((10.0, 20.0, 130.0))


@pytest.mark.parametrize("mapping", [
    {"x": "-x", "y": "+y", "z": "+z"}, {"x": "+x", "y": "+y"},
    {"x": "x", "y": "+y", "z": "+z"}, {"x": "+q", "y": "+y", "z": "+z"}])  # 镜像／缺键／无符号／非法轴名
def test_axis_swap_rejects_mirror_and_bad_mapping(mapping):
    with pytest.raises(ValueError):
        axis_swap_frame(mapping)


@pytest.mark.parametrize("spin", [
    (1.0, 0.0, 0.0, 0.0, 1.0, 0.0), (1.0, 1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0),
    (1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)])  # 只 6 元素／行不归一／两行不正交
def test_frame_rejects_non_orthonormal(spin):
    """建框即校验：否则逆变换按转置算会**静默出错**。"""
    with pytest.raises(ValueError, match="rotation"):
        CoordFrame((0.0, 0.0, 0.0), spin)


@pytest.mark.parametrize("frame", [IDENTITY_FRAME, Y_UP_TO_Z_UP, TILTED, OBLIQUE])
@pytest.mark.parametrize("point", [(0.0, 0.0, 0.0), (1.5, -2.25, 7.0), (1234.5, -678.9, 4321.0)])
def test_round_trip_error_below_1e_6(frame, point):
    """用例④：往返误差 <1e-6（mm）；`OBLIQUE` 含无理数才真受浮点检验，前三框元素仅 0／±1 无舍入。"""
    assert device_to_model(model_to_device(point, frame), frame) == pytest.approx(point, abs=1e-6)
    assert scene_to_device(device_to_scene(point, frame), frame) == pytest.approx(point, abs=1e-6)


# ── 链解析的四条校验 ──────────────────────────────────────────────────────────
@pytest.mark.parametrize("links, joints, match", [
    (SYN_LINKS + (Link("ghost", 0.0, None),), SYN_JOINTS + (Joint("ghost", "x"),), "恰有 1 个根"),
    (tuple(dataclasses.replace(k, parent="base") for k in SYN_LINKS), SYN_JOINTS, "恰有 1 个根"),
    (SYN_LINKS, SYN_JOINTS[:-1], "未绑定"),
    (SYN_LINKS, SYN_JOINTS + (Joint("nope", "x", "X1"),), "表外"),
    (SYN_LINKS, (Joint("gantry", "q", "X1"),) + SYN_JOINTS[1:], "motion"),
    (SYN_LINKS, (Joint("gantry", "x", "GHOST"),) + SYN_JOINTS[1:], "不在 axes 表内"),
])
def test_build_model_rejects_bad_binding(links, joints, match):
    with pytest.raises(ValueError, match=match):
        build_model(dataclasses.replace(SYN_CFG, links=links), joints)


def test_build_model_rejects_disconnected_links():
    """两根连杆互为父（环）⇒ 自根不可达、fk 永远算不到位姿，故拒（禁静默降级）。"""
    links = SYN_CFG.links + (Link("loop_a", 0.0, "loop_b"), Link("loop_b", 0.0, "loop_a"))
    joints = SYN_JOINTS + (Joint("loop_a", "x"), Joint("loop_b", "x"))
    with pytest.raises(ValueError, match="有环或不连通"):
        build_model(dataclasses.replace(SYN_CFG, links=links), joints)


# ── 用例①②：正解 ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("label, values, want", FK_CASES)
def test_fk_link_origins_match_hand_calc(label, values, want):
    """各连杆原点＝纸上链式乘法手算值（记录见交付汇报，防自证循环）。"""
    assert SYN.order == SYN_ORDER  # 拓扑序父先于子，fk 才能逐级累积
    poses = fk(values, SYN)
    got = [coord for name in SYN_ORDER for coord in _origin(poses[name])]
    assert got == pytest.approx([coord for point in want for coord in point])
    filled = {name: 0.0 for name in SYN_CFG.axes} | values
    assert fk(filled, SYN) == poses  # 缺项按 0.0＝全零位，调用方不必凑齐 22 个键


def test_fk_revolute_orientation_matches_hand_calc():
    """RA＝+90° 时 head 的旋转部分＝Rz(90)（行主序），逐元素手算：cos90＝0、sin90＝1。"""
    head = fk({"RA": 90.0}, SYN)["head"]
    assert head[:12] == pytest.approx((0.0, -1.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 200.0))
    assert head[12:] == (0.0, 0.0, 0.0, 1.0)


# ── 两型耦合（配置驱动，禁硬编码）─────────────────────────────────────────────
def test_self_mastered_ratio_is_drive_level_doubling():
    """X3 口径（2026-09-16 定案）：master 自指 ⇒ 工程位置＝驱动位移 × ratio。

    ⛔ 禁读成跨轴约束：同时给 X2 一个值，X3 的结果**不受影响**（不是 X2 × 2）。
    """
    assert resolve_positions({"X3": 10.0}, SYN_CFG)["X3"] == pytest.approx(20.0)
    assert resolve_positions({"X2": 7.0, "X3": 10.0}, SYN_CFG)["X3"] == pytest.approx(20.0)
    assert _origin(fk({"X3": 10.0}, SYN)["tube"])[0] == pytest.approx(120.0)


def test_cross_axis_ratio_overrides_slave_input():
    """master 指向别的轴 ⇒ 从动轴＝主动轴 × ratio，输入里给从动轴的值被覆盖（约束优先）。"""
    axes = dict(SYN_CFG.axes, RA=_axis("RA", REVOLUTE, (-360.0, 360.0),
                                       Coupling("ratio", None, None, "X1", 2.0)))
    cfg = dataclasses.replace(SYN_CFG, axes=axes)
    assert resolve_positions({"X1": 100.0, "RA": 999.0}, cfg)["RA"] == pytest.approx(200.0)


def test_ratio_master_cycle_is_rejected():
    axes = dict(SYN_CFG.axes,
                X2=_axis("X2", PRISMATIC, (0.0, 400.0), Coupling("ratio", None, None, "X3", 1.0)),
                X3=_axis("X3", PRISMATIC, (0.0, 1000.0), Coupling("ratio", None, None, "X2", 1.0)))
    with pytest.raises(ValueError, match="成环"):
        resolve_positions({}, dataclasses.replace(SYN_CFG, axes=axes))


# ── 用例③：行程与同步校核 ─────────────────────────────────────────────────────
@pytest.mark.parametrize("values, want", LIMIT_CASES)
def test_check_limits_names_axis_value_and_limit(values, want):
    """越界项含轴号／值／限值／单位／组；ratio 轴按**工程位置**校核（驱动 600 → 工程 1200）。"""
    assert _hits(SYN_CFG, values) == want


def test_check_limits_returns_every_hit_at_once():
    """一次返回全部不通过项（不逐条抛）：T07／T08 的「禁发」判据以返回空表为准。"""
    values = {"X1": 600.0, "RA": 120.0, "Z1": -1.0, "L1": 10.0, "L2": 12.0}
    assert [hit[1] for hit in _hits(SYN_CFG, values)] == ["X1", "Z1", "RA", "L2"]


# ── 工程值／原始值换算（契约 §7.4 最高危项）───────────────────────────────────
@pytest.mark.parametrize("sign, scale, zero, raw, want", [
    (1, None, 0.0, 12.5, 12.5), (-1, 0.001, 5.0, 1000.0, -6.0), (1, 2.0, 10.0, 3.0, -4.0)])
def test_raw_to_eng_three_parameters(sign, scale, zero, raw, want):
    """标定四要素中的三参：工程值＝原始值 × 比例系数 × 方向符号 − 零点偏移；scale＝null 按 1.0。

    三组算式：12.5 × 1 × 1 − 0＝12.5；1000 × 0.001 × (−1) − 5＝−6；3 × 2 × 1 − 10＝−4。
    """
    axis = _axis("A", PRISMATIC, (-1e6, 1e6), None, sign, scale, zero)
    assert raw_to_eng(axis, raw) == pytest.approx(want)


def test_raw_to_eng_on_sample_axes_is_identity():
    """现场 22 轴当前 scale＝null／零点 0／正方向 +1 ⇒ 原始值即工程值（占位，非实测标定）。"""
    assert all(raw_to_eng(axis, 12.5) == 12.5 for axis in SAMPLE_CFG.axes.values())


# ── 现场样例（config/machine.yaml，T03 交付实况）──────────────────────────────
def test_sample_loads_with_pending_warnings_not_errors():
    """22 轴全 pending ⇒ **只告警不拒绝**；禁把 cfg.warnings 当错误处理、禁据此承诺可达性。"""
    assert len(SAMPLE_CFG.axes) == 22
    assert SAMPLE_CFG.warnings[0].startswith("22 个轴标 pending")


def test_sample_fk_at_zero_is_identity_chain():
    """用例①（现场链）：links 的连杆长度全为占位 0.0 ⇒ 全零位下 13 根连杆位姿全为单位阵。"""
    poses = fk({}, SAMPLE_MODEL)
    assert len(poses) == len(SAMPLE_CFG.links) == 13
    assert all(pose == identity() for pose in poses.values())


def test_sample_x3_coupling_is_self_mastered():
    """现场配置实测＝master 指向自身 ⇒ 驱动级倍速；倍率**读配置**，代码里不写死。"""
    join = SAMPLE_CFG.axes["X3"].coupling
    assert (join.type, join.master) == ("ratio", "X3")
    assert resolve_positions({"X3": 10.0}, SAMPLE_CFG)["X3"] == pytest.approx(10.0 * join.ratio)


def test_sample_travel_check_uses_engineering_position():
    """X3 驱动 600 → 工程 1200 > 占位行程上界 1000 ⇒ 命中；**禁拿驱动位移去比行程**。"""
    assert [(hit[1], hit[2]) for hit in _hits(SAMPLE_CFG, {"X3": 600.0})] == [("X3", 1200.0)]


def test_sample_sync_groups_are_single_axis():
    """现状：多驱动单元（大车四轮／机架四油缸）未被单列为轴 ⇒ 每 group 只 1 轴、极差恒 0，
    sync 校核不会触发（契约 §6.4-bit3：Q-9 回执前不启用）；回执后**自动生效、不改码**。"""
    groups: dict[str, list[str]] = {}
    for axis in SAMPLE_CFG.axes.values():
        join = axis.coupling
        if join is not None and join.type == "sync":
            groups.setdefault(join.group, []).append(axis.id)
    assert groups == {"gantry_travel": ["X1"], "frame_lift": ["Z1"], "arm_lift": ["Z2"]}
    assert [hit for hit in _hits(SAMPLE_CFG, {"X1": 900.0}) if hit[0] == KIND_SYNC] == []


def test_sample_arm_axes_have_no_link():
    """已登记的输入缺口：各臂专用轴在 links 表里无对应连杆 ⇒ fk 不出其位姿（限位仍全校 22 轴）。"""
    bound = {joint.axis_id for joint in SAMPLE_JOINTS if joint.axis_id}
    assert sorted(set(SAMPLE_CFG.axes) - bound) == [
        "FB1", "FB2", "FC", "KE", "RA", "RC", "ZA1", "ZA2", "ZB", "ZC", "ZD"]
