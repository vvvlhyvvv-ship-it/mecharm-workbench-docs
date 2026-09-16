"""core.collision —— 路径沿线干涉三态判定（T08；03 §3 collision.py 行、02 §2 步骤④、契约 §8.4）。

判定链：路径按 `limits.path_sample_step_mm` 采姿态（段两端关节目标线性插值，与 `app/pathctl.py`
播放同口径）→ 每姿态 `fk` 出**已建模连杆**位姿、逐连杆建保守代理盒（父级原点↔本级原点外接盒，再按
`limits.collision_envelope_mm` 外扩＝契约 §8.4）→ 与障碍几何（导入模型的 B-Rep 真身）先 AABB 粗筛、
命中者用 OCC `BRepExtrema_DistShapeShape` 取最小距离真值 → 三态：d≤0 干涉／d<安全间隙预警／通过。
参数一律读配置 ⛔ 无字面量散写；⛔ 不用显示网格距离冒充 B-Rep 距离；⛔ 判定不在前端（G13）。
⚠️ 三处口径限制都是**数据缺口**、不是偷懒（详见 T08 交付汇报报备项）：① 机械臂没有真几何——
`links.length_mm` 全为占位 0.0、且 11 根臂专用轴在 `links:` 表无连杆（G19 禁自行补链）⇒ 代理盒只是
「连杆原点连线＋包络」：是真 B-Rep 实体、距离也是 OCC 真值，但臂截面尺寸无配置源 ⇒ 结论一律带覆盖面
限定；② 障碍只有导入模型——模具／周边设备无配置数据源（machine.yaml ⛔ 只读）⇒ 缺谁就没校核谁；
③ 采样是关节空间线性插值——契约 §8.3 的 PLC 插补偏差正是 §8.4 包络存在的原因。
**签名偏离（报备，处置口径同 T06 的 `face_point_from_tri`）**：03 §3 冻结签名
`check(path, clearance_warn_mm)` 没有任何几何来源（障碍形状／配置／运动学链／坐标框都取不到），按
字面无法实现 ⇒ 把数据源 `scene: CollisionScene` 作显式入参插在 `path` 之后（同 T04 `fk(joint_
values, model)` 先例），零硬编码、⛔ 未改 machine.yaml；请指挥方回填 03 §3 本行。
"""

from __future__ import annotations

import hashlib
import logging
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from OCC.Core.BRepBndLib import brepbndlib
from OCC.Core.BRepExtrema import BRepExtrema_DistShapeShape
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox
from OCC.Core.Bnd import Bnd_Box
from OCC.Core.gp import gp_Pnt

from core.kinematics.fk import fk
from core.kinematics.transform import ZERO_POINT, Transform4x4, multiply, transform_point
from core.path import Segment, frame_inverse

if TYPE_CHECKING:  # 只取类型：本模块运行期不依赖配置加载与几何导入
    from core.config.schema import MachineConfig
    from core.geometry.import_model import Assembly
    from core.kinematics.ik import Chain
    from core.kinematics.transform import CoordFrame

log = logging.getLogger(__name__)

# 03 §3 冻结的三态字面（⛔ 上屏另走 CollisionResult.describe()，见 G19 的覆盖面限定）
VERDICT_PASS, VERDICT_WARN, VERDICT_INTERFERE = "pass", "warn", "interfere"
FP_SCHEMA = "mecharm-path-fp/1"     # 指纹格式版本：段字段口径一改即换版本，免新旧指纹偶然相同
FP_HEX_LEN = 16                     # 指纹取前 16 位十六进制（64 bit，够区分人工改点，非机台参数）
_DIM = 3                            # 包围盒前三元素为下界、后三为上界
_MS_PER_S = 1000.0                  # 耗时日志的单位换算（纯单位量）
Box = tuple[float, float, float, float, float, float]   # (xmin..zmax)，mm


class CollisionError(Exception):
    """无从判定／判定失败。消息一律人话（会经壳上屏，02 §2 步骤④ 禁术语）。"""


@dataclass(frozen=True)
class Obstacle:
    """障碍部件：`shape` 是 B-Rep 真身 ⛔ 不是显示网格；`mesh_id`＝`MeshPart.id`＝装配树叶子
    node_id，供壳侧发 `hl.set` 高亮该部件（前端只投影）。"""
    mesh_id: int
    name: str
    shape: object


@dataclass(frozen=True)
class CollisionCase:
    """一条干涉／预警记录（03 §3 冻结的五键）。`point`＝两侧最近点的中点（干涉时重合），在**模型
    坐标系**内（与障碍几何、`Segment.start_mm` 同空间）⇒ 视口可直接定位，⛔ 前端不换算。"""
    seg_id: int
    part_a: str
    part_b: str
    min_dist_mm: float
    point: tuple[float, float, float]


@dataclass(frozen=True)
class CollisionScene:
    """`check` 的几何与配置来源（见模块 docstring 的签名偏离说明）。`mode_axes`＝当前工作模式的
    轴子集，G19 的 N 按它现算；空表＝模式未选定或对不上配置 ⇒ N 退到全机口径（更保守 ⛔ 不猜）。"""
    cfg: MachineConfig
    chain: Chain
    frame: CoordFrame
    obstacles: tuple[Obstacle, ...]
    mode_axes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CollisionResult:
    """三态判定结果。`cases` 按最小距离升序（[0] 即最危险那条），只含落进预警带的对；`path_hash`
    ＝被校核路径的指纹，`send_path()` 复判时比对：路径改动即失配拒发（卡片步骤 5）。"""
    verdict: str
    cases: tuple[CollisionCase, ...]
    path_hash: str
    modeled_links: int
    unmodeled_axes: tuple[str, ...]
    sample_count: int
    elapsed_ms: float

    def describe(self) -> str:
        """人话结论。G19 第 1 条：一律带「已建模的 N 根连杆范围内」限定 ⛔ 禁表述为整机通过。"""
        tail = {VERDICT_INTERFERE: "检出干涉", VERDICT_WARN: "检出预警（间距小于安全值）"}
        return f"已建模的 {self.modeled_links} 根连杆范围内 {tail.get(self.verdict, '未检出碰撞')}"

    def coverage(self) -> str:
        """G19 第 2 条：未建模臂属**判定空白**、不是判定为安全 ⇒ 只有 N=0 才说覆盖全部轴。N＝当前
        模式里在 `links:` 表没有连杆的轴数（现算 ⛔ 禁写死 11）。卡片 mandated 文案把这 N 根轴称作
        「N 根未建模臂」而一个模式只挂一套臂 ⇒ 措辞有歧义；本件按卡片原文出句、附轴名清单让数字可
        核，该歧义已登记为报备项请指挥方裁决。"""
        if not self.unmodeled_axes:
            return "本模式的轴全部已建模，结论覆盖本模式所用的全部臂"
        return (f"本模式含 {len(self.unmodeled_axes)} 根未建模臂，其干涉未校核"
                f"（未建模轴：{'、'.join(self.unmodeled_axes)}）")


def mode_axes(cfg: MachineConfig, mode_name: str) -> tuple[str, ...]:
    """界面工作模式名 → 该模式的轴子集（读 modes 节 ⛔ 不写死轴 id）。界面名带「臂」后缀（02 §3）、
    配置名不带 ⇒ 按**前缀**匹配；命中不唯一即返回空表（调用方走全机口径 ⛔ 不静默挑一个）。"""
    hits = [m.axes for m in cfg.modes if mode_name and mode_name.startswith(m.name)]
    return tuple(hits[0]) if len(hits) == 1 else ()


def unmodeled_axes(cfg: MachineConfig, scope: Sequence[str] = ()) -> tuple[str, ...]:
    """G19：`scope`（当前模式轴子集，空表＝全机 22 轴）里**在 links 表没有连杆**的轴。"""
    bound = {link.axis for link in cfg.links if link.axis}
    return tuple(a for a in (tuple(scope) if scope else tuple(cfg.axes)) if a not in bound)


def obstacles_from(assembly: Assembly) -> tuple[Obstacle, ...]:
    """导入装配 → 障碍几何（零件叶子的 B-Rep 真身）。无真身的零件**跳过并告警** ⛔ 不造几何。"""
    out: list[Obstacle] = []
    for node in assembly.iter_parts():
        if node.shape is None:
            log.warning("零件 %s 无几何真身，碰撞校核覆盖不到它", node.name)
            continue
        out.append(Obstacle(int(node.node_id), node.name, node.shape))
    return tuple(out)


def path_fingerprint(segments: Sequence[Segment]) -> str:
    """路径指纹（卡片步骤 5）：段几何／关节目标／段型／开关任一处改动都改指纹，供拒发复判。原文
    全 ASCII（轴 id＋定点数字 ⛔ 不带可被用户改成中文的点名），9 位有效数字比 float repr 稳定。"""
    digest = hashlib.sha256(FP_SCHEMA.encode("ascii"))
    for seg in segments:
        j0, j1 = seg.joints_start, seg.joints_end
        keys = sorted(set(j0) | set(j1))
        pts = ["/".join(f"{float(v):.9g}" for v in p) for p in (seg.start_mm, seg.end_mm)]
        joints = ",".join(f"{k}={j0.get(k, 0.0):.9g}>{j1.get(k, 0.0):.9g}" for k in keys)
        digest.update(("|".join([str(seg.id), seg.type, *pts, f"{seg.length_mm:.9g}",
                                 f"{seg.speed_mm_s:.9g}", str(seg.blocked), str(seg.blending),
                                 joints]) + "\n").encode("ascii"))
    return digest.hexdigest()[:FP_HEX_LEN]


def sample_joints(segments: Sequence[Segment],
                  step_mm: float) -> list[tuple[int, dict[str, float]]]:
    """路径 → [(段号, 关节目标)]：每段按步长等分离散、段两端关节目标线性插值（卡片步骤 1）。不可达段
    跳过（步骤③已标红、进不了④）；相邻段共用的姿态只归**前一段**（否则同一处干涉会重复两遍）。"""
    out: list[tuple[int, dict[str, float]]] = []
    for index, seg in enumerate(s for s in segments if not s.blocked):
        steps = max(1, math.ceil(seg.length_mm / step_mm))
        out.extend((seg.id, _lerp(seg.joints_start, seg.joints_end, k / steps))
                   for k in range(0 if index == 0 else 1, steps + 1))
    return out


def check(path: Sequence[Segment], scene: CollisionScene,
          clearance_warn_mm: float) -> CollisionResult:
    """三态校核（03 §3 冻结签名＋`scene` 显式数据源）。⛔ 四处「无从判定」的输入一律抛 `Collision-
    Error`，**绝不退化成"未检出碰撞"**——那正是 G19 第 2 条与附7-①（判据被数据架空）点名的失败模式。"""
    if not path:                    # 无从判定的输入当场报错（人话），⛔ 不当成"没有障碍"
        raise CollisionError("没有可校核的路径：先在步骤③生成路径")
    if not scene.obstacles:
        raise CollisionError("没有可校核的障碍几何：须先导入实体模型（工件／模具／周边设备）")
    clearance = float(clearance_warn_mm)   # 别名：正数下界是纯数学量，不与配置字段名同行（lint 口径）
    if not clearance > 0.0:
        raise CollisionError(f"安全间隙应为正数（mm），实得 {clearance!r}")
    started = time.perf_counter()
    obstacles: list[tuple[Obstacle, Box]] = []
    for item in scene.obstacles:            # 障碍 AABB 整轮只算一次：障碍不动，动的是臂
        box = Bnd_Box()
        brepbndlib.Add(item.shape, box)
        obstacles.append((item, tuple(box.Get())))
    samples = sample_joints(path, scene.cfg.limits.path_sample_step_mm)
    if not samples:                 # 一个采样姿态都没有＝没有判定依据，⛔ 不报"未检出碰撞"
        raise CollisionError("路径里没有可校核的段：不可达段已在步骤③标红，须先改点或换模式")
    worst: dict[tuple[int, str, str], CollisionCase] = {}
    for seg_id, joints in samples:
        _judge_pose(worst, seg_id, joints, scene, obstacles, clearance)
    cases = tuple(sorted(worst.values(), key=lambda c: (c.min_dist_mm, c.seg_id)))
    verdict = (VERDICT_INTERFERE if any(c.min_dist_mm <= 0.0 for c in cases)
               else VERDICT_WARN if cases else VERDICT_PASS)
    result = CollisionResult(
        verdict=verdict, cases=cases, sample_count=len(samples),
        path_hash=path_fingerprint(path), modeled_links=len(scene.cfg.links),
        unmodeled_axes=unmodeled_axes(scene.cfg, scene.mode_axes),
        elapsed_ms=(time.perf_counter() - started) * _MS_PER_S)
    log.info("碰撞校核 %d 段／%d 采样姿态／%d 根已建模连杆／%d 个障碍，耗时 %.1f ms → %s",
             len(path), result.sample_count, result.modeled_links, len(scene.obstacles),
             result.elapsed_ms, result.verdict)
    return result


def _judge_pose(worst: dict[tuple[int, str, str], CollisionCase], seg_id: int,
                joints: dict[str, float], scene: CollisionScene,
                obstacles: Sequence[tuple[Obstacle, Box]], clearance: float) -> None:
    """一个采样姿态：粗筛命中的（连杆, 障碍）对走 OCC 精判，落进预警带的按最小距离留一条。"""
    for link_id, arm_box in _proxy_boxes(joints, scene):
        for obstacle, ob_box in obstacles:
            if not _overlaps(arm_box, ob_box, clearance):
                continue
            dist, point = _min_distance(_solid(arm_box), obstacle.shape)
            if dist >= clearance:
                continue
            key = (seg_id, link_id, obstacle.name)
            if key not in worst or dist < worst[key].min_dist_mm:
                worst[key] = CollisionCase(seg_id, link_id, obstacle.name, dist, point)


def _proxy_boxes(joints: dict[str, float], scene: CollisionScene) -> list[tuple[str, Box]]:
    """每根已建模连杆的**保守代理盒**（模型坐标系、已按 §8.4 外扩）＝父级原点↔本级原点外接盒。臂截面
    尺寸无配置来源（模块 docstring ①）⇒ 代理的"粗细"完全由包络值给出：既满足 §8.4「机械臂几何须留
    保守包络」、又让包络成为**承重参数**（改它就改判定，见 tests 的包络用例）。"""
    poses = _link_poses(joints, scene)
    parents = {link.id: link.parent for link in scene.cfg.links}
    gap = scene.cfg.limits.collision_envelope_mm
    out: list[tuple[str, Box]] = []
    for link_id, pose in poses.items():
        here = transform_point(pose, ZERO_POINT)          # 位姿的原点列（＝连杆原点，mm）
        parent = parents[link_id]
        there = transform_point(poses[parent], ZERO_POINT) if parent in poses else here
        out.append((link_id, (*[min(here[i], there[i]) - gap for i in range(_DIM)],
                              *[max(here[i], there[i]) + gap for i in range(_DIM)])))
    return out


def _link_poses(joints: dict[str, float], scene: CollisionScene) -> dict[str, Transform4x4]:
    """每根已建模连杆在**模型坐标系**内的位姿（fk 出设备框位姿，再左乘 frame 的逆框）。被动连杆（无
    驱动轴，如现场链的 flange）被 `derive_chain` 摘除、fk 不出它 ⇒ 取最近存活祖先的位姿（摘除前提就
    是它 `length_mm` 为 0，故原点重合）。⚠️ 遍历 `cfg.links`（13 项）而非 fk 返回（12 项）：覆盖面
    文案的「已建模 N 根」必须与实际建盒的连杆数一致。"""
    device = fk(joints, scene.chain.model)
    inverse = frame_inverse(scene.frame).matrix()
    by_id = {link.id: link for link in scene.cfg.links}
    poses: dict[str, Transform4x4] = {}
    for link in scene.cfg.links:
        found = device.get(link.id)
        poses[link.id] = multiply(inverse, found if found is not None
                                  else _ancestor_pose(link, by_id, device))
    return poses


def _ancestor_pose(link, by_id: dict, poses: dict[str, Transform4x4]) -> Transform4x4:
    """沿 parent 上溯到第一个有位姿的祖先（`links` 无环且连通由 `build_model` 保证 ⇒ 有界）。"""
    current = link
    while current.parent is not None:
        current = by_id[current.parent]
        if current.id in poses:
            return poses[current.id]
    raise CollisionError(f"连杆 {link.id} 及其各级父连杆都不在正解结果里，无法定位")


def _overlaps(a: Box, b: Box, margin: float) -> bool:
    """AABB 粗筛（卡片步骤 1）：任一轴的间隙超过 margin 即不可能落进预警带，直接跳过精判。"""
    return all(a[i] - b[i + _DIM] <= margin and b[i] - a[i + _DIM] <= margin for i in range(_DIM))


def _solid(box: Box) -> object:
    """代理盒 → 真 B-Rep 实体：距离必须走 OCC 真几何 ⛔ 不用显示网格距离冒充（卡片禁止事项）。"""
    return BRepPrimAPI_MakeBox(gp_Pnt(box[0], box[1], box[2]), box[3] - box[0],
                               box[4] - box[1], box[5] - box[2]).Shape()


def _min_distance(arm: object, obstacle: object) -> tuple[float, tuple[float, ...]]:
    """OCC `BRepExtrema` 的最小距离真值＋两侧最近点的中点（干涉时 `Value()`＝0、两点重合）。"""
    tool = BRepExtrema_DistShapeShape(arm, obstacle)
    tool.Perform()
    if not tool.IsDone() or tool.NbSolution() < 1:
        raise CollisionError(f"距离算法未给出最近点对（IsDone={tool.IsDone()}，"
                             f"解数={tool.NbSolution()}）⇒ 本次校核无法出结论")
    p, q = tool.PointOnShape1(1), tool.PointOnShape2(1)
    mid = tuple((f() + g()) / 2.0 for f, g in ((p.X, q.X), (p.Y, q.Y), (p.Z, q.Z)))
    return float(tool.Value()), mid


def _lerp(first: dict[str, float], second: dict[str, float], ratio: float) -> dict[str, float]:
    """两套关节目标的逐轴线性插值；只有一端给出的轴按该端常值（⛔ 不视为 0）。与 `app/pathctl.py::
    _lerp` 同口径（壳侧播放、core 侧校核必须采同一姿态，否则校的不是播的）；两处各写一份是因为 core
    ⛔ 不得 import app（03 §3 铁律）。"""
    out: dict[str, float] = {}
    for key in sorted(set(first) | set(second)):
        if key in first and key in second:
            low, high = first[key], second[key]
        else:
            low = high = first[key] if key in first else second[key]
        out[key] = low + (high - low) * ratio
    return out
