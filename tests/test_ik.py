"""tests/test_ik.py —— T07 解析逆解测试（卡片步骤 6：ik 已知位姿手算复核，记录贴汇报）。

覆盖四类：① 手算位姿的逆解与 fk∘ik 往返 ② 多解按行程／连续性选支（含 `_allocate` 的均分、
钉住、不可达）③ 各 IkError 分支（球腕／回转后移动副／跨轴 ratio／被动偏置／无该向移动副／
末端并列）④ 常驻守卫（禁硬编码机台事实、禁复制 tests 的合成绑定、禁数值迭代、内部只用行主序）。

⚠️ 合成链是**测试数据、不是机台事实**（同 test_kinematics.py 的口径）：现场 machine.yaml 的
`links.axis／motion` 是 G18 占位、踏勘第 7 项回执未到，故现场链只做**结构性**断言（末端推导
唯一、被动连杆摘除、往返闭合、按配置累加），一切数值断言都落在本文件纸上手算过的合成链上。
"""

from __future__ import annotations

import ast
import dataclasses
import pathlib

import pytest

from core.config import REPO_ROOT, Axis, Coupling, Link, load_machine
from core.kinematics import (PRISMATIC, REVOLUTE, IkError, derive_chain, fk, ik, identity,
                             multiply, resolve_positions, rotation, tool_link, translation)

MINIMAL = pathlib.Path(__file__).resolve().parent / "fixtures" / "ok_minimal.yaml"
IK_SOURCE = (REPO_ROOT / "core" / "kinematics" / "ik.py").read_text(encoding="utf-8")
SITE_CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
# 求解路径上的函数：卡片与 03 §3 禁的「数值迭代」只可能出现在这里，故守卫按函数名核对
SOLVER_FUNCS = ("ik", "_solve_positions", "_allocate", "_solve_orientation", "_to_input")
ITERATION_TOKENS = ("jacobian", "newton", "ccd", "gradient", "scipy", "numpy", "max_iter")


def _axis(axis_id, kind, span, join=None):
    """造一根合成轴：span＝行程（移动副 mm／回转副 deg）、join＝耦合（占位零点／正方向 +1）。"""
    return Axis(axis_id, kind, "trajectory", tuple(span), 0.0, 1, None, join, False)


def _cfg(axes, links):
    """按合成轴表与连杆表换掉 ok_minimal 的两节（其余节不参与 ik，沿用夹具即可）。"""
    return dataclasses.replace(load_machine(str(MINIMAL)),
                               axes={item.id: item for item in axes}, links=links)


def _close(got, want):
    """逐键核对逆解结果（键集合与数值都要对，abs=1e-9＝纯数学量级的浮点回代误差）。"""
    assert sorted(got) == sorted(want), f"解出的轴集合不符：{sorted(got)} ≠ {sorted(want)}"
    for axis_id, value in want.items():
        assert got[axis_id] == pytest.approx(value, abs=1e-9), f"{axis_id}: {got[axis_id]} ≠ {value}"


# ── 合成链 A：base → gantry(SX,x) → column(SZ,z，连杆长 50) → head(WR，绕 z 回转) ──────────
#    手算基准（fk 语义＝先沿 motion 偏 length_mm、再叠加轴运动）：
#      关节 {SX:200, SZ:100, WR:30} → head 位姿 = translation(200,0,150) ∘ rotation(z,30)
#      故逆解该位姿应还原同一组关节：x 方程 SX=200−0；z 方程 SZ=150−50=100；姿态 atan2→30。
AXES_A = (_axis("SX", PRISMATIC, (0.0, 500.0)), _axis("SZ", PRISMATIC, (0.0, 300.0)),
          _axis("WR", REVOLUTE, (-90.0, 90.0)))
LINKS_A = (Link("base", 0.0, None, None, None), Link("gantry", 0.0, "base", "SX", "x"),
           Link("column", 50.0, "gantry", "SZ", "z"), Link("head", 0.0, "column", "WR", "z"))
CHAIN_A = derive_chain(_cfg(AXES_A, LINKS_A))
POSE_A = multiply(translation(200.0, 0.0, 150.0), rotation("z", 30.0))
JOINTS_A = {"SX": 200.0, "SZ": 100.0, "WR": 30.0}

# ── 合成链 B（多解）：base → gantry(SX,x) → flange(被动，长 0) → tip(SX2,x) ─────────────────
#    被动连杆摘除后 tip 重挂到 gantry；x 向两根轴 ⇒ 一个方程两个未知量，解由 seed 与行程定。
#    手算：目标 150 mm、零位 seed → 均分 SX=SX2=75；seed SX=500 → 先把 SX2 钉在下界 0、
#    余量全给 SX ⇒ SX=150／SX2=0；目标 1500 mm > 行程合计 900 mm ⇒ 不可达。
AXES_B = (_axis("SX", PRISMATIC, (0.0, 500.0)), _axis("SX2", PRISMATIC, (0.0, 400.0)))
LINKS_B = (Link("base", 0.0, None, None, None), Link("gantry", 0.0, "base", "SX", "x"),
           Link("flange", 0.0, "gantry", None, None), Link("tip", 0.0, "flange", "SX2", "x"))
CHAIN_B = derive_chain(_cfg(AXES_B, LINKS_B))

# ── 合成链 C（驱动级倍速）：base → gantry(SX,x) → tube(DUP,x；DUP 的 ratio master 指向自身）──
#    手算：目标 300 mm、零位 seed → 工程位置均分 DUP=SX=150；DUP 是自指倍速轴 ⇒ 返回**驱动
#    位移** 150 ÷ 2 = 75（倍率读配置，禁写死）。fk 回代时 resolve_positions 把 75 放大回 150。
DUP_RATIO = Coupling("ratio", None, None, "DUP", 2.0)
AXES_C = (_axis("SX", PRISMATIC, (0.0, 500.0)), _axis("DUP", PRISMATIC, (0.0, 1000.0), DUP_RATIO))
LINKS_C = (Link("base", 0.0, None, None, None), Link("gantry", 0.0, "base", "SX", "x"),
           Link("tube", 0.0, "gantry", "DUP", "x"))
CHAIN_C = derive_chain(_cfg(AXES_C, LINKS_C))


def test_known_pose_inverts_to_the_hand_computed_joints():
    """用例①：手算位姿 → 逆解 → 逐轴对上纸面数值（含连杆长 50 的偏置与 atan2 姿态）。"""
    _close(ik(POSE_A, CHAIN_A), JOINTS_A)


def test_fk_of_ik_returns_the_target_pose():
    """用例①：fk∘ik 往返——逆解出的关节喂回 fk，末端 16 元逐位回到目标位姿（行主序同口径）。"""
    pose = fk(ik(POSE_A, CHAIN_A), CHAIN_A.model)[CHAIN_A.effective_end]
    for index in range(16):
        assert pose[index] == pytest.approx(POSE_A[index], abs=1e-9), f"元素 {index}"


def test_negative_and_zero_angles_invert_within_travel():
    """用例①：姿态取负角与零角（θ 在行程内直接命中，不需 ±一整圈的备选支）。"""
    for angle in (0.0, -45.0, 90.0):
        target = multiply(translation(0.0, 0.0, 50.0), rotation("z", angle))
        _close(ik(target, CHAIN_A), {"SX": 0.0, "SZ": 0.0, "WR": angle})


def test_multi_turn_picks_the_branch_continuous_with_the_seed():
    """用例②：把 WR 行程放宽到 ±一整圈后，θ 与 θ−一整圈同为解 ⇒ 按 seed 选连续的那一支。

    手算：目标姿态 30°、行程 (−360,360) ⇒ 候选 {30, −330, 390}，390 出界；
    零位 seed → |30−0| < |−330−0| 取 30；seed=−330 → 取 −330（不跨圈翻转）。
    """
    axes = {**CHAIN_A.model.cfg.axes, "WR": _axis("WR", REVOLUTE, (-360.0, 360.0))}
    chain = derive_chain(dataclasses.replace(CHAIN_A.model.cfg, axes=axes))
    assert ik(POSE_A, chain)["WR"] == pytest.approx(30.0, abs=1e-9)
    assert ik(POSE_A, chain, {"WR": -330.0})["WR"] == pytest.approx(-330.0, abs=1e-9)


def test_underdetermined_axis_pair_splits_evenly_from_the_zero_seed():
    """用例②：x 向两根轴、一个方程 ⇒ 零位 seed 下均分（Σ 恰等于目标，不是近似收敛）。"""
    _close(ik(translation(150.0, 0.0, 0.0), CHAIN_B), {"SX": 75.0, "SX2": 75.0})


def test_seed_pulls_the_solution_onto_the_nearest_feasible_corner():
    """用例②：seed 偏向 SX 满行程 ⇒ SX2 被钉在**下界原值** 0、余量全给 SX（手算 150／0）。

    钉住必须赋边界原值：若按 seed+λ 的浮点结果留着 −1e-16 一类残差，T08 的 check_limits 会把
    一个本可达的点判成越界（limits.py 的 travel 判据是严格不等式）。
    """
    got = ik(translation(150.0, 0.0, 0.0), CHAIN_B, {"SX": 500.0, "SX2": 0.0})
    _close(got, {"SX": 150.0, "SX2": 0.0})
    assert got["SX2"] == 0.0, "钳位须落在边界原值上，不得留浮点残差"


def test_self_referential_ratio_axis_returns_drive_displacement():
    """用例②：自指 ratio 轴（master == 自身）＝驱动级倍速 ⇒ 返回驱动位移＝工程位置 ÷ ratio。

    手算：目标 300 mm 均分 ⇒ DUP 工程 150、SX 150；DUP 的 ratio=2 读自配置 ⇒ 返回 75。
    ⛔ 禁读成跨轴约束（03 §4／T04 定案口径），故 fk 回代必须仍是 300 mm。
    """
    got = ik(translation(300.0, 0.0, 0.0), CHAIN_C)
    _close(got, {"DUP": 75.0, "SX": 150.0})
    positions = resolve_positions(got, CHAIN_C.model.cfg)
    assert positions["DUP"] == pytest.approx(150.0, abs=1e-9)
    assert fk(got, CHAIN_C.model)[CHAIN_C.effective_end][3] == pytest.approx(300.0, abs=1e-9)


def test_unreachable_total_is_rejected_with_the_travel_sum():
    """用例③：目标超出同向各轴行程合计 ⇒ IkError，消息含轴名与合计区间（供路径段标红）。"""
    with pytest.raises(IkError) as caught:
        ik(translation(1500.0, 0.0, 0.0), CHAIN_B)
    assert "合不出 1500 mm" in str(caught.value)
    assert "SX／SX2" in str(caught.value) and "[0, 900] mm" in str(caught.value)


def test_direction_without_a_prismatic_joint_is_rejected():
    """用例③：链上没有沿 y 的移动副却要 y 分量 ⇒ 拒（⛔ 禁静默按 0 处理，那会算错位姿）。"""
    with pytest.raises(IkError, match="链上没有沿 y 的移动副"):
        ik(translation(0.0, 80.0, 0.0), CHAIN_A)


def test_orientation_beyond_a_single_revolute_axis_is_rejected():
    """用例③：单回转轴合不出绕 x 的姿态——闭式解只读两个矩阵元，故必须回代核对全 9 元。

    平移取 z=50＝column 的连杆偏置，好让位置方程恰好可达，剩下的不通过项只能是姿态。
    """
    with pytest.raises(IkError, match="单回转轴合不出目标姿态"):
        ik(multiply(translation(0.0, 0.0, 50.0), rotation("x", 30.0)), CHAIN_A)


def test_chain_without_any_revolute_axis_only_accepts_pure_translation():
    """用例③：链 B 全移动副（工具姿态由安装固定）⇒ 带旋转的目标一律拒。"""
    with pytest.raises(IkError, match="链上没有回转副"):
        ik(multiply(translation(100.0, 0.0, 0.0), rotation("z", 30.0)), CHAIN_B)
    _close(ik(translation(100.0, 0.0, 0.0), CHAIN_B), {"SX": 50.0, "SX2": 50.0})


def test_malformed_target_pose_is_rejected():
    """用例③：位姿不是 16 元素行主序 ⇒ 拒（列主序误传会在姿态上静默出错，故先挡形状）。"""
    with pytest.raises(IkError, match="应为 16 元素行主序位姿"):
        ik(identity()[:12], CHAIN_A)


def test_end_link_outside_the_links_table_is_rejected():
    """用例③：请求的末端连杆不在 links 表内 ⇒ 拒并列出表内 id（不猜最近的）。"""
    with pytest.raises(IkError, match="不在 links 表内"):
        derive_chain(CHAIN_A.model.cfg, "tcp")


def test_two_revolute_axes_are_refused_instead_of_guessed():
    """用例③：≥2 根回转副（球腕）需腕偏置与三轴交点，而臂链在 links 表里没有连杆、G19 禁自行
    补链 ⇒ 遇到即 IkError，⛔ 不静默按某个腕解处理。"""
    axes = AXES_A + (_axis("WR2", REVOLUTE, (-90.0, 90.0)),)
    links = LINKS_A + (Link("wrist", 0.0, "head", "WR2", "z"),)
    with pytest.raises(IkError, match="2 根回转副"):
        ik(POSE_A, derive_chain(_cfg(axes, links), "wrist"))


def test_prismatic_after_a_revolute_axis_is_refused():
    """用例③：移动副排在回转副之后 ⇒ 其平移会被旋到别的方向、位置方程不再线性，解析解不成立。"""
    links = LINKS_A + (Link("tip", 0.0, "head", "SX2", "x"),)
    axes = AXES_A + (_axis("SX2", PRISMATIC, (0.0, 400.0)),)
    with pytest.raises(IkError, match="移动副排在回转副之后"):
        ik(translation(100.0, 0.0, 60.0), derive_chain(_cfg(axes, links), "tip"))


def test_cross_axis_ratio_follower_is_referred_to_ruling():
    """用例③：跨轴 ratio（master 指向别的轴）的工程位置被主动轴定死 ⇒ 不是自由未知量，交裁决。"""
    slave = Coupling("ratio", None, None, "SX2", 2.0)
    axes = (_axis("SLAVE", PRISMATIC, (0.0, 500.0), slave), _axis("SX2", PRISMATIC, (0.0, 400.0)))
    links = (Link("base", 0.0, None, None, None), Link("slide", 0.0, "base", "SLAVE", "x"))
    with pytest.raises(IkError, match="跨轴倍速从动轴"):
        ik(translation(100.0, 0.0, 0.0), derive_chain(_cfg(axes, links)))


def test_passive_link_with_a_nonzero_offset_is_refused():
    """用例③：无驱动轴的连杆带非零 length_mm ⇒ 摘除即静默丢掉一段偏置，故拒（现场全为 0 占位）。"""
    links = LINKS_A + (Link("tool", 100.0, "head", None, None),)
    with pytest.raises(IkError, match="无驱动轴却有 length_mm=100 mm"):
        derive_chain(_cfg(AXES_A, links), "tool")


def test_tied_deepest_leaves_are_refused_instead_of_picked():
    """用例③：两个同深叶节点 ⇒ 末端推导不唯一即拒（machine.yaml 无 tool／tcp 键，禁静默挑一个）。"""
    links = (Link("base", 0.0, None, None, None), Link("arm_l", 0.0, "base", "SX", "x"),
             Link("arm_r", 0.0, "base", "SX2", "x"))
    with pytest.raises(IkError, match="末端连杆推导不唯一"):
        tool_link(_cfg(AXES_B, links))


def test_site_chain_drops_the_passive_flange_and_keeps_the_deepest_leaf():
    """用例①（现场链，结构性）：flange 无驱动轴被摘除，其位姿与最深的存活连杆 tube3 同源。"""
    assert tool_link(SITE_CFG) == "flange"
    chain = derive_chain(SITE_CFG)
    assert chain.end_link == "flange" and chain.effective_end == "tube3"
    assert chain.path[0] == "base" and chain.path[-1] == chain.effective_end
    assert "flange" not in chain.model.links
    assert chain.model.joints[chain.effective_end].axis_id in SITE_CFG.axes


def test_site_chain_round_trips_a_known_translation():
    """用例①（现场链，数值按配置累加、不写死轴号）：目标 (300,0,0) → ik → fk 回到同一平移。"""
    chain = derive_chain(SITE_CFG)
    joints = ik(translation(300.0, 0.0, 0.0), chain)
    pose = fk(joints, chain.model)[chain.effective_end]
    assert (pose[3], pose[7], pose[11]) == pytest.approx((300.0, 0.0, 0.0), abs=1e-9)
    positions = resolve_positions(joints, SITE_CFG)
    driven = [link.axis for link in SITE_CFG.links if link.motion == "x" and link.axis]
    assert sum(positions[axis_id] for axis_id in driven) == pytest.approx(300.0, abs=1e-9)


def test_ik_source_hardcodes_no_machine_fact():
    """守卫：ik.py 里不得出现任何现场轴号／连杆号的字符串字面量（G18 立案点名的失败模式）。

    清单从配置现取 ⇒ machine.yaml 增删轴或连杆，本守卫自动跟着扩，不用改测试。
    """
    names = set(SITE_CFG.axes) | {link.id for link in SITE_CFG.links}
    hits = sorted(name for name in names
                  if f'"{name}"' in IK_SOURCE or f"'{name}'" in IK_SOURCE)
    assert not hits, f"ik.py 写死了机台事实：{hits}（拓扑只准读 machine.yaml）"


def test_ik_source_does_not_copy_the_test_side_sample_binding():
    """守卫：ik.py 不得引用 tests 里的合成绑定（卡片明禁把 SAMPLE_JOINTS 当机台事实复制）。"""
    assert "SAMPLE_JOINTS" not in IK_SOURCE
    assert not [node for node in ast.walk(ast.parse(IK_SOURCE))
                if isinstance(node, ast.ImportFrom) and (node.module or "").startswith("tests")]


def test_solver_functions_have_no_unbounded_loop():
    """守卫：求解函数里**一个 while 都没有**——闭式解的有限步只能由有界 for 表达。

    出现 while 即意味着引入了「跑到收敛为止」的数值迭代（卡片与 03 §3 明禁）。链上溯一类的
    while 不在求解路径上（其轮次由 links 表长度封顶），故按函数名分别核对，不搞一刀切。
    """
    offenders = []
    for node in ast.parse(IK_SOURCE).body:
        if isinstance(node, ast.FunctionDef) and node.name in SOLVER_FUNCS:
            offenders += [f"{node.name}:{item.lineno}" for item in ast.walk(node)
                          if isinstance(item, ast.While)]
    assert not offenders, f"求解函数内出现无界循环：{offenders}"


def test_solver_has_no_numeric_iteration_dependency():
    """守卫：不引 numpy／scipy、不用雅可比／牛顿／CCD 一类迭代法（闭式解的正面判据）。"""
    names = set()
    for node in ast.walk(ast.parse(IK_SOURCE)):
        if isinstance(node, ast.Name):
            names.add(node.id.lower())
        elif isinstance(node, ast.Attribute):
            names.add(node.attr.lower())
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.add((getattr(node, "module", "") or "").lower())
            names.update((alias.name or "").lower() for alias in node.names)
    hits = sorted(token for token in ITERATION_TOKENS
                  if any(token in name for name in names if name))
    assert not hits, f"ik.py 出现数值迭代迹象：{hits}"


def test_ik_stays_row_major_and_never_emits_column_major():
    """守卫：ik 内部一律行主序（矩阵口径＝卡内红线③），故不得调用 to_column_major。

    上屏前的列主序转换属 view 侧的职责；同一函数里混用两种口径＝姿态静默错。
    """
    assert "to_column_major" not in IK_SOURCE
    pose = fk(ik(POSE_A, CHAIN_A), CHAIN_A.model)[CHAIN_A.effective_end]
    assert pose[3] == pytest.approx(200.0, abs=1e-9), "行主序的平移应在元素 3／7／11"
