"""tests/test_collision.py —— T08 碰撞三态与禁发的**承重用例**（卡片步骤 6／完成标准①②③）。

① 三态由**手算间隙**驱动（板从 398／408／903 起 ⇒ 干涉 0.0／预警 5.0／未检出），断言值纸面算出、
⛔ 不是跑一遍抄回来的（04 §5.5 附7-①：判据不得被数据架空）② 精判走 B-Rep 真几何：斜向逼近自造圆柱
＝√2·17−5＝19.0416，按包围盒算＝√2·12＝16.9706 ⇒ 断前者即同时排除「AABB 冒充」与「显示网格冒充」
（网格偏差 0.5 mm 级）③ 包络是**承重参数**（3.0→干涉／1.0→预警 1.0 mm）④ 采样：段内等分、共用姿
态只归前一段、不可达段跳过、**无可校核段即抛错**（⛔ 不报"未检出碰撞"）⑤ 指纹 golden 值锁字段口径
（改口径必须换 `FP_SCHEMA`）⑥ G19：五模式未建模轴 3/3/3/1/1 与全机 11 **现算**、N=0 对照另给、文案
恒带「已建模的 N 根连杆范围内」且 ⛔ 不出现"通过" ⑦ 守卫：core 纯净、只用 B-Rep、无魔法数字、签名偏
离已报备、结果不可变。⚠️ 几何与点位一律自造基本体（⛔ 禁甲方模型／名称／尺寸）；夹具不落盘。
"""

from __future__ import annotations

import ast
import dataclasses
import importlib.util
import inspect
import math
import pathlib
import re
from types import SimpleNamespace

import pytest
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCC.Core.gp import gp_Ax2, gp_Dir, gp_Pnt

from core.collision import (FP_HEX_LEN, VERDICT_INTERFERE, VERDICT_PASS, VERDICT_WARN,
                            CollisionError, CollisionResult, CollisionScene, Obstacle, check,
                            mode_axes, obstacles_from, path_fingerprint, sample_joints,
                            unmodeled_axes)
from core.config import REPO_ROOT, Axis, Link, Mode, load_machine
from core.geometry.face_point import Waypoint
from core.kinematics import PRISMATIC, axis_swap_frame, derive_chain
from core.path import KIND_CONTOUR, KIND_POINT, gen_path

SOURCE = (REPO_ROOT / "core" / "collision.py").read_text(encoding="utf-8")
MINIMAL = load_machine(str(pathlib.Path(__file__).resolve().parent / "fixtures" / "ok_minimal.yaml"))
SITE_CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
FRAME = axis_swap_frame({"x": "+x", "y": "+y", "z": "+z"})   # 模型框＝设备框（契约 §7.1 待确认）
FORBIDDEN = ("PySide6", "Qt", "app", "view", "comm", "numpy")   # ⚠️ OCC 允许：精判就得用它

# ── 可手算的合成链：base → slide（X1 沿 x、行程 [0,1000]、length_mm 0）──────────────────────
#    关节 X1=x ⇒ slide 原点 (x,0,0)；代理盒＝两原点的外接盒按包络 3.0 外扩 ⇒ 走 P1(100)→P2(400)
#    时臂扫过的盒恒为 x∈[-3,403]、y∈[-3,3]、z∈[-3,3]（纸面可算）。于是板的间隙是**手算**的：
#    板从 398 起＝相交、408 起＝间隙 5、903 起＝间隙 500。
ONE = dataclasses.replace(
    MINIMAL,
    axes={"X1": Axis("X1", PRISMATIC, "trajectory", (0.0, 1000.0), 0.0, 1, None, None, False)},
    links=(Link("base", 0.0, None, None, None), Link("slide", 0.0, "base", "X1", "x")))
CLEARANCE = ONE.limits.clearance_warn_mm    # 20.0：取自夹具配置，⛔ 判定阈值不在测试里写死
STEP = ONE.limits.path_sample_step_mm       # 50.0：同上
FAR_X = 903.0                               # 板从此处起 ⇒ 间隙 500 mm（远超安全值 ⇒ 未检出）
GOLDEN_FP = "bf2d688d4748551f"              # P1(100)→P2(400) 点位型的指纹（锁 FP_SCHEMA 口径）
SITE_MODES = [("打磨臂", ("ZA1", "ZA2", "RA")), ("氧化皮吸附臂", ("ZB", "FB1", "FB2")),
              ("脱模剂喷涂臂", ("ZC", "FC", "RC")), ("氧化皮破碎臂", ("ZD",)),
              ("玻璃垫放置臂", ("KE",))]


def _wp(index, x_mm):
    """一个点位（T06 的 `Waypoint`）：只动 x，法向用不上故给 +z。"""
    return Waypoint(index, f"P{index}", (float(x_mm), 0.0, 0.0), (0.0, 0.0, 1.0), index)


def _path(*xs, cfg=ONE, kind=KIND_POINT):
    """按 x 序列造路径（链随 cfg 现推，⛔ 不与别的配置串用）。"""
    points = [_wp(i, x) for i, x in enumerate(xs, 1)]
    return gen_path(points, cfg, derive_chain(cfg), FRAME, kind=kind)


def _plate(x0, thick=20.0, half=50.0, mesh_id=2001, name="自造板"):
    """自造平板：y／z 各 ±half 完全罩住臂的扫掠面 ⇒ 最小距离就等于 x 向间隙（可手算）。"""
    shape = BRepPrimAPI_MakeBox(gp_Pnt(x0, -half, -half), thick, 2 * half, 2 * half).Shape()
    return Obstacle(mesh_id, name, shape)


def _scene(obstacles, cfg=ONE, axes=()):
    return CollisionScene(cfg, derive_chain(cfg), FRAME, tuple(obstacles), tuple(axes))


def _result(verdict, modeled=13, unmodeled=("ZA1", "ZA2", "RA")):
    """直接造结果对象：文案是字段的纯函数，测文案不必再跑一遍几何。"""
    return CollisionResult(verdict, (), "0" * FP_HEX_LEN, modeled, unmodeled, 7, 1.0)


class _Assembly:
    """替身装配：只提供 `iter_parts()`；零件叶子用 `SimpleNamespace` 顶替（只读三个属性）。"""

    def __init__(self, nodes):
        self._nodes = nodes

    def iter_parts(self):
        return iter(self._nodes)


PATH = _path(100.0, 400.0)                    # 1 段、7 个采样姿态（300／50＝6 等分）
THERE_AND_BACK = _path(100.0, 400.0, 100.0)   # 2 段、13 个采样姿态（共用姿态只归前一段）


# ── ① 三态：手算间隙 → 🔴／🟡／🟢 ─────────────────────────────────────────────────────────
@pytest.mark.parametrize("x0, verdict, dist", [
    (398.0, VERDICT_INTERFERE, 0.0),    # 板切进臂的扫掠盒（盒到 x=403）⇒ 相交，距离 0
    (408.0, VERDICT_WARN, 5.0),         # 间隙 5 mm < 安全间隙 20 mm ⇒ 预警
    (FAR_X, VERDICT_PASS, None),        # 间隙 500 mm ⇒ 未检出碰撞、无记录
])
def test_three_verdicts_follow_the_hand_computed_gap(x0, verdict, dist):
    """承重用例①：三态与最小距离都由纸面手算的间隙决定，⛔ 不是跑一遍把输出抄进断言。"""
    result = check(PATH, _scene([_plate(x0)]), CLEARANCE)
    assert result.verdict == verdict
    assert result.sample_count == 7 and result.modeled_links == 2
    if dist is None:
        assert result.cases == ()
        return
    assert len(result.cases) == 1
    case = result.cases[0]
    assert case.min_dist_mm == pytest.approx(dist, abs=1e-9)
    assert (case.seg_id, case.part_a, case.part_b) == (1, "slide", "自造板")


def test_precise_distance_is_b_rep_not_a_bounding_box_or_a_mesh():
    """承重用例②：臂盒角到自造圆柱柱面＝√2·17−5＝19.0416，按柱的 AABB 算＝16.9706 ⇒ 断前者即证明精判走 B-Rep 真几何、不是包围盒或显示网格。"""
    cylinder = Obstacle(2002, "自造圆柱", BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(420.0, 20.0, -20.0), gp_Dir(0.0, 0.0, 1.0)), 5.0, 40.0).Shape())
    result = check(PATH, _scene([cylinder]), CLEARANCE)
    want = math.sqrt(2.0) * 17.0 - 5.0
    boxed = math.sqrt(2.0) * 12.0
    assert result.verdict == VERDICT_WARN
    assert result.cases[0].min_dist_mm == pytest.approx(want, abs=1e-9)
    assert abs(result.cases[0].min_dist_mm - boxed) > 1.0, "若退化成 AABB 距离，本条必挂"


def test_collision_envelope_is_a_load_bearing_parameter():
    """承重用例③：同一块板（x=402 起）包络 3.0→干涉、1.0→预警 1.0 mm ⇒ 包络真参与判定，且是配置项。"""
    thin = dataclasses.replace(
        ONE, limits=dataclasses.replace(ONE.limits, collision_envelope_mm=1.0))
    assert (ONE.limits.collision_envelope_mm, thin.limits.collision_envelope_mm) == (3.0, 1.0)
    hit = check(PATH, _scene([_plate(402.0)]), CLEARANCE)
    near = check(PATH, _scene([_plate(402.0)], cfg=thin), CLEARANCE)
    assert (hit.verdict, hit.cases[0].min_dist_mm) == (VERDICT_INTERFERE, 0.0)
    assert near.verdict == VERDICT_WARN
    assert near.cases[0].min_dist_mm == pytest.approx(1.0, abs=1e-9)


def test_cases_are_sorted_worst_first_and_one_per_link_obstacle_pair():
    """记录按最小距离升序（[0] 即最危险）；同一（段, 连杆, 障碍）只留最小那条 ⇒ 来回穿板 13 姿态出 2 条。"""
    two = check(PATH, _scene([_plate(408.0), _plate(413.0, mesh_id=2002, name="自造板乙")]),
                CLEARANCE)
    assert [(c.part_b, round(c.min_dist_mm, 6)) for c in two.cases] == \
        [("自造板", 5.0), ("自造板乙", 10.0)]
    through = check(THERE_AND_BACK, _scene([_plate(200.0)]), CLEARANCE)
    assert through.verdict == VERDICT_INTERFERE and through.sample_count == 13
    assert [(c.seg_id, c.min_dist_mm) for c in through.cases] == [(1, 0.0), (2, 0.0)]


# ── ④ 采样口径 ───────────────────────────────────────────────────────────────────────────
def test_sampling_splits_segments_and_never_repeats_a_shared_pose():
    """300 mm 段按 50 mm 步长＝6 等分 ⇒ 7 姿态；两段路 ⇒ 7＋6＝13（共用姿态只归前一段）；关节值线性递进、首末＝起终点（校的就是播的）。"""
    one = sample_joints(PATH, STEP)
    both = sample_joints(THERE_AND_BACK, STEP)
    assert [seg for seg, _ in one] == [1] * 7
    assert [seg for seg, _ in both] == [1] * 7 + [2] * 6
    assert [joints["X1"] for _, joints in one] == [100.0 + 50.0 * k for k in range(7)]
    assert both[-1][1]["X1"] == 100.0
    assert all(a[1] != b[1] for a, b in zip(both, both[1:])), "共用姿态重复计入 ⇒ 同一处干涉会刷屏"


def test_blocked_segments_are_skipped_and_an_all_blocked_path_refuses_to_verdict():
    """不可达段不采样；**整条都不可达 ⇒ 无从判定，抛错而不是报"未检出碰撞"**（附7-①／G19-2 点名的失败模式）。"""
    broken = _path(100.0, 5000.0)                  # 5000 超出 X1 行程 [0,1000] ⇒ 该段 blocked
    assert broken[0].blocked and sample_joints(broken, STEP) == []
    with pytest.raises(CollisionError, match="不可达"):
        check(broken, _scene([_plate(FAR_X)]), CLEARANCE)
    mixed = _path(100.0, 400.0, 5000.0)            # 第 1 段可达、第 2 段不可达 ⇒ 只校第 1 段
    assert [seg for seg, _ in sample_joints(mixed, STEP)] == [1] * 7


def test_unjudgeable_inputs_raise_instead_of_reporting_no_collision():
    """空路径／无障碍几何／安全间隙非正 ⇒ 一律抛 `CollisionError`（消息是人话，可直接上屏）。"""
    with pytest.raises(CollisionError, match="先在步骤③生成路径"):
        check([], _scene([_plate(FAR_X)]), CLEARANCE)
    with pytest.raises(CollisionError, match="须先导入实体模型"):
        check(PATH, _scene([]), CLEARANCE)
    for bad in (0.0, -1.0):
        with pytest.raises(CollisionError, match="安全间隙应为正数"):
            check(PATH, _scene([_plate(FAR_X)]), bad)


# ── ⑤ 路径指纹（下发前失配拒发的判据）────────────────────────────────────────────────────
def test_fingerprint_is_reproducible_and_moves_with_the_path():
    """golden 值锁指纹字段口径（改口径必须换 `FP_SCHEMA`）；改点位／段型都换指纹；16 位小写十六进制、全 ASCII（要过桥）。"""
    assert path_fingerprint(PATH) == GOLDEN_FP == path_fingerprint(_path(100.0, 400.0))
    assert path_fingerprint(_path(100.0, 401.0)) != GOLDEN_FP, "改点位不换指纹 ⇒ 失配拒发形同虚设"
    assert path_fingerprint(_path(100.0, 400.0, kind=KIND_CONTOUR)) != GOLDEN_FP
    assert re.fullmatch(rf"[0-9a-f]{{{FP_HEX_LEN}}}", GOLDEN_FP) and GOLDEN_FP.isascii()
    assert check(PATH, _scene([_plate(FAR_X)]), CLEARANCE).path_hash == GOLDEN_FP


# ── ⑥ G19 覆盖面：N 现算、N=0 对照、文案限定 ─────────────────────────────────────────────
@pytest.mark.parametrize("mode_name, unmodeled", SITE_MODES)
def test_unmodeled_axes_are_counted_from_config_per_mode(mode_name, unmodeled):
    """G19：N **现算**（⛔ 禁写死 11）——五模式各 3/3/3/1/1 根轴无连杆，未选定退到全机 11 根；轴名逐字列出 ⇒ 配置一改就挂。"""
    assert unmodeled_axes(SITE_CFG, mode_axes(SITE_CFG, mode_name)) == unmodeled
    assert len(unmodeled_axes(SITE_CFG)) == 11
    assert unmodeled_axes(SITE_CFG, ()) == unmodeled_axes(SITE_CFG)


def test_mode_axes_matches_by_prefix_and_refuses_to_guess():
    """界面名带「臂」后缀 ⇒ 前缀匹配；未选定／对不上／**命中不唯一**一律返回空表（调用方退到全机口径，⛔ 不静默挑一个）。"""
    assert mode_axes(SITE_CFG, "打磨臂") == SITE_CFG.modes[0].axes
    assert mode_axes(SITE_CFG, "") == () and mode_axes(SITE_CFG, "不存在的臂") == ()
    ambiguous = dataclasses.replace(SITE_CFG, modes=SITE_CFG.modes + (Mode("dup", "打", ("X1",)),))
    assert mode_axes(ambiguous, "打磨臂") == ()


def test_verdict_wording_never_reads_as_an_overall_pass():
    """G19 第 1—2 条：文案恒带「已建模的 N 根连杆范围内」⛔ 不出现"通过"；N>0 必须说「未校核」，只有 N=0 才许说覆盖全部轴。"""
    tails = ((VERDICT_INTERFERE, "检出干涉"), (VERDICT_WARN, "检出预警（间距小于安全值）"),
             (VERDICT_PASS, "未检出碰撞"))
    for verdict, tail in tails:
        text = _result(verdict).describe()
        assert text == f"已建模的 13 根连杆范围内 {tail}"
        assert "通过" not in text and "整机" not in text
    assert _result(VERDICT_PASS).coverage() == \
        "本模式含 3 根未建模臂，其干涉未校核（未建模轴：ZA1、ZA2、RA）"
    assert _result(VERDICT_PASS, unmodeled=()).coverage() == \
        "本模式的轴全部已建模，结论覆盖本模式所用的全部臂"


def test_site_config_run_counts_every_modeled_link_including_passive_ones():
    """现场配置端到端：建模连杆数＝`links:` 表现算的 13 ⛔ 不是 fk 的 12——被动连杆 flange 被摘除但照样建盒、照样计入覆盖面文案。"""
    scene = _scene([_plate(5000.0, mesh_id=3001, name="远处自造板")], cfg=SITE_CFG,
                   axes=mode_axes(SITE_CFG, "打磨臂"))
    result = check(_path(100.0, 400.0, cfg=SITE_CFG), scene, SITE_CFG.limits.clearance_warn_mm)
    assert result.verdict == VERDICT_PASS
    assert result.modeled_links == len(SITE_CFG.links) == 13 and result.sample_count == 7
    assert result.describe() == "已建模的 13 根连杆范围内 未检出碰撞"
    assert result.coverage() == "本模式含 3 根未建模臂，其干涉未校核（未建模轴：ZA1、ZA2、RA）"


def test_coverage_contrast_case_has_zero_unmodeled_axes():
    """G19 要求的 **N=0 对照工况**：现场配置下不存在（五套工装臂都无连杆），故用合成配置造一个，走同一条 `check`→`coverage()` 通路。"""
    full = dataclasses.replace(ONE, modes=(Mode("one", "打磨", ("X1",)),))
    assert unmodeled_axes(full, mode_axes(full, "打磨臂")) == ()
    result = check(PATH, _scene([_plate(FAR_X)], cfg=full, axes=mode_axes(full, "打磨臂")),
                   CLEARANCE)
    assert result.verdict == VERDICT_PASS
    assert result.coverage() == "本模式的轴全部已建模，结论覆盖本模式所用的全部臂"


# ── ⑦ 障碍取材与常驻守卫 ─────────────────────────────────────────────────────────────────
def test_obstacles_come_from_b_rep_and_shapeless_parts_are_skipped(caplog):
    """障碍取零件叶子的 B-Rep 真身（⛔ 不是显示网格）；没有真身的零件**跳过并告警**——缺谁就没校核谁。"""
    shape = _plate(FAR_X).shape
    got = obstacles_from(_Assembly([SimpleNamespace(node_id=7, name="自造件甲", shape=shape),
                                    SimpleNamespace(node_id=8, name="自造件乙", shape=None)]))
    assert [(o.mesh_id, o.name, o.shape is shape) for o in got] == [(7, "自造件甲", True)]
    assert "自造件乙" in caplog.text and "覆盖不到" in caplog.text


def test_collision_module_has_no_magic_axis_numbers():
    """守卫：直接调用常驻复查①的**权威工具**（04 §5.5-①），不另写一套判定（两套＝两个口径）。"""
    tool = REPO_ROOT / "tools" / "lint_no_magic.py"
    spec = importlib.util.spec_from_file_location("lint_no_magic", tool)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    hits, _ = module.scan()
    assert not [hit for hit in hits if hit.startswith("core/collision.py")], hits


def test_module_keeps_core_pure_and_judges_with_b_rep_only():
    """守卫：① 运行期不引 GUI／app／view／comm／numpy（OCC **允许**）② 精判只用 B-Rep ⛔ 不引显示网格；② 走 ast 取标识符而非 grep。"""
    tree = ast.parse(SOURCE)
    names = []
    for node in tree.body:
        if isinstance(node, ast.Import):
            names += [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    hits = sorted(name for name in names if name.split(".")[0] in FORBIDDEN)
    assert not hits, f"core/collision.py 运行期依赖越界：{hits}"
    used = {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}
    used |= {node.attr for node in ast.walk(tree) if isinstance(node, ast.Attribute)}
    assert "BRepExtrema_DistShapeShape" in used
    meshy = sorted(u for u in used if "tessellate" in u.lower() or "meshpart" in u.lower())
    assert not meshy, f"精判不得走显示网格：{meshy}"


def test_check_keeps_the_frozen_parameter_names():
    """守卫：冻结的 `check(path, …, clearance_warn_mm)` 参数名不动；多出的 `scene` 是**已报备的签名偏离**（原签名没有几何来源）。"""
    assert list(inspect.signature(check).parameters) == ["path", "scene", "clearance_warn_mm"]


def test_results_are_immutable_so_the_ui_cannot_drift_from_the_verdict():
    """守卫：结果与记录都是 frozen dataclass——改一处即抛，杜绝「界面显示已改、判定没改」的静默不一致（03 §3 单向数据流）。"""
    with pytest.raises(dataclasses.FrozenInstanceError):
        check(PATH, _scene([_plate(FAR_X)]), CLEARANCE).verdict = VERDICT_INTERFERE
    with pytest.raises(dataclasses.FrozenInstanceError):
        check(PATH, _scene([_plate(408.0)]), CLEARANCE).cases[0].min_dist_mm = 999.0
