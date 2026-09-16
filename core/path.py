"""core.path —— 点位序列 → 段序列（T07；03 §3「path.py 生成」行、02 §2 步骤③）。

本单产物＝**轨迹参数**（当前工作模式轨迹级轴的段序列），**不是整机运动程序**——主要动作由
PLC 编程，软件只输出轨迹编程部分交 PLC 执行（03 §4「实机轴系口径」末条、契约第 8 章方案 A：
软件出关键点位、**PLC 负责段内插补**）。故本模块 ⛔ 不做圆弧／样条插补、⛔ 不细分密集点流。

段型两种（卡片步骤 1，界面可切）：
  点位型 `KIND_POINT`   → 段类型 **JOINT**（契约 §5.2 SegType 0=PTP）、速度取 `speed_rapid_mm_s`（空程）
  轮廓型 `KIND_CONTOUR` → 段类型 **LINE** （契约 §5.2 SegType 1=LIN）、速度取 `speed_work_mm_s`（作业）
速度一律读 `machine.yaml` 的 `limits`（并经 `speed_max_mm_s` 上界钳制），⛔ 代码内无速度字面量
（04 §5.5 常驻复查①）。契约 §5.2 SegType 2=CIRC 是**能力上限**，本期只出 0／1。

每段端点先过 `core.kinematics.ik`（解析闭式解）求关节目标、再过 `check_limits`（T04）：**无解或
超限的段 `blocked=True` 并带人话原因**，调用方据此标红且**阻断生成结果确认**（不得进入步骤④）。
`ik` 的上一次解作 seed 传入 ⇒ 多解按**连续性**选支（卡片步骤 2）。

⚠️ **三处口径限制，都是数据缺口造成的、不是偷懒**（详见 T07 交付汇报的登记项）：
  ① **点位法向不参与**。`Waypoint.normal` 是真值法向，但现配置的驱动链**全是移动副**（11 根臂
     专用轴在 `links` 表里没有连杆，G19 明禁自行补链）⇒ `ik` 对带旋转的目标位姿一律 IkError。
     故目标位姿按**纯平移**构造（工具姿态由安装固定）。回执补链后改此处即可，⛔ 不静默假装解出姿态。
  ② **模型框→设备框无配置源**（契约 §7.1 两条均「待确认」）⇒ `frame` 作**显式入参**、无默认值，
     由调用方给定（同 T04 `fk(joint_values, model)` 与 T06 `face_point_from_tri(parts, …)` 先例）。
  ③ **`Segment` 与 `comm.opcua_client.write.Segment` 同名异义**：那边是契约 §5.2 的**下发段**
     （`pos` 槽位＋`motion_mode`／`blend_tol`／`dwell_ms`），这边是**几何段**（起终点＋长度＋时长＋
     关节目标）。⛔ 两者禁互引、禁合并（同 `Frame`／`CoordFrame`、`Violation`／`CollisionResult`
     的处置口径）；下发时的适配属 T08／T10，本模块不 import comm（03 §3 铁律）。

`blending` ＝契约 §8.3 的连续过渡开关，**默认 False**＝按「逐段到达」设计；**电Q-8（下发轨迹段
格式）回执后再切**（卡片前置阅读与完成标准）。它只随段携带、不改本模块的几何与时长算法。
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.kinematics.fk import fk
from core.kinematics.ik import Chain, IkError, ik
from core.kinematics.limits import check_limits
from core.kinematics.transform import (CoordFrame, Point, Transform4x4, model_to_device, multiply,
                                       translation)

if TYPE_CHECKING:  # 只取类型：core.path ⛔ 不依赖 OCC／numpy（face_point 运行期要二者）
    from core.config.schema import MachineConfig
    from core.geometry.face_point import Waypoint
    from core.kinematics.limits import Violation

KIND_POINT = "point"        # 点位型（空程快速移动）
KIND_CONTOUR = "contour"    # 轮廓型（作业速度）
KINDS = (KIND_POINT, KIND_CONTOUR)

# 段类型用 03 §3 的 LINE／JOINT 字面（T08 的 collision.check 与右栏段清单同口径）；
# 速度键名按 machine.yaml 的 limits 字段取，⛔ 不在代码里写速度数值。
_SEG_TYPE = {KIND_POINT: "JOINT", KIND_CONTOUR: "LINE"}
_SPEED_KEY = {KIND_POINT: "speed_rapid_mm_s", KIND_CONTOUR: "speed_work_mm_s"}
_MM_PER_M = 1000.0          # 汇总行「总长 X m」的换算（纯单位量、非机台参数）


@dataclass(frozen=True)
class Segment:
    """一段轨迹（点位型＝空程 JOINT／轮廓型＝作业 LINE）。

    ``start_mm``／``end_mm`` 与**入参点位同坐标系**（模型／文件坐标系，mm）——右栏段清单与视口
    折线都直接用它，⛔ 前端不做任何坐标换算（03 §3 单向数据流）。长度与时长与框无关（`CoordFrame`
    是刚体变换），故不必另存设备坐标系副本；关节目标 ``joints_*`` 由设备坐标系内的 `ik` 解出，
    键语义与 `fk` 入参一致（`ratio` 自指轴＝驱动位移）。

    ``blocked`` 为真时 ``reason`` 必非空（人话、含轴号与数值），且该段**不得**参与结果确认。
    """

    id: int                       # 段号，1-based（右栏「段号」列、T08 的 seg_id 同源）
    type: str                     # "LINE"｜"JOINT"
    start_name: str               # 起点位名（P1…，用户可改）
    end_name: str
    start_mm: Point
    end_mm: Point
    length_mm: float
    speed_mm_s: float
    duration_s: float
    joints_start: dict[str, float]
    joints_end: dict[str, float]
    blocked: bool
    reason: str
    blending: bool = False        # 电Q-8 回执前恒 False（见模块 docstring）


@dataclass(frozen=True)
class PathSummary:
    """段序列汇总（右栏汇总行的数据源，02 §2 步骤③）。``ok`` ＝可进入步骤④的判据。"""

    count: int
    total_length_mm: float
    total_duration_s: float
    blocked_count: int

    @property
    def ok(self) -> bool:
        """有段且无阻断段才算通过（空路径不点亮步骤④）。"""
        return self.count > 0 and self.blocked_count == 0

    def describe(self) -> str:
        """人话汇总行：「共 N 段 · 总长 X m · 预估节拍 Y s」；有阻断段则追加红字口径。"""
        line = (f"共 {self.count} 段 · 总长 {self.total_length_mm / _MM_PER_M:.3f} m"
                f" · 预估节拍 {self.total_duration_s:.1f} s")
        if self.blocked_count:
            return f"{line} · ⛔ {self.blocked_count} 段不可达（已标红，无法进入校核）"
        return line


def gen_path(points: list[Waypoint], cfg: MachineConfig, chain: Chain, frame: CoordFrame,
             kind: str = KIND_POINT, blending: bool = False) -> list[Segment]:
    """点位序列 → 段序列（卡片步骤 1＋2）。

    ``frame`` ＝**模型框在设备框内**的定位（`core.kinematics.CoordFrame`），把点位送进 `ik` 前
    先 `model_to_device`；契约 §7.1 未回执 ⇒ 无默认值、由调用方显式给定（模块 docstring ②）。
    ``kind`` 决定段类型与速度（界面可切）；``blending`` 只随段携带，默认 False。

    少于两个点位 ⇒ 返回空表（调用方提示「点位不足」，⛔ 不静默造段）；`ik` 无解或 `check_limits`
    有违规 ⇒ **该段** `blocked=True`＋人话原因（点位为两段共用，故一个坏点会标红相邻两段）。
    """
    if kind not in KINDS:
        raise ValueError(f"kind 应为 {KINDS} 之一，实得 {kind!r}")
    if len(points) < 2:
        return []
    speed = _speed(cfg, kind)
    solved = _solve_points(points, cfg, chain, frame)
    out: list[Segment] = []
    for index in range(len(points) - 1):
        first, second = points[index], points[index + 1]
        (joints_a, why_a), (joints_b, why_b) = solved[index], solved[index + 1]
        length = _distance(first.pos_mm, second.pos_mm)
        # 两端常因**同一**原因不可达（如某根不在链上的轴全零位即越界）⇒ 按序去重，
        # 免得上屏把同一句话重复两遍；两端原因不同时仍两条都留。
        reason = "；".join(dict.fromkeys(why for why in (why_a, why_b) if why))
        out.append(Segment(
            id=index + 1, type=_SEG_TYPE[kind], start_name=first.name, end_name=second.name,
            start_mm=first.pos_mm, end_mm=second.pos_mm, length_mm=length, speed_mm_s=speed,
            duration_s=length / speed, joints_start=joints_a, joints_end=joints_b,
            blocked=bool(reason), reason=reason, blending=blending))
    return out


def summarize(segments: list[Segment]) -> PathSummary:
    """段序列 → 汇总（段数／总长／预估节拍／阻断段数）。阻断段**计入**段数与长度。"""
    return PathSummary(count=len(segments),
                       total_length_mm=sum(seg.length_mm for seg in segments),
                       total_duration_s=sum(seg.duration_s for seg in segments),
                       blocked_count=sum(1 for seg in segments if seg.blocked))


def frame_inverse(frame: CoordFrame) -> CoordFrame:
    """`CoordFrame` 的逆框（上层框→本框）：旋转取转置、原点取 −Rᵀ·origin。

    `transform` 只给**点**的逆变换（`device_to_model`），位姿的逆变换须自己组逆框——本函数只用
    公开 API 组框（建框即校验正交归一，故转置阵不合法时会当场拒），⛔ 不改 T04 已验收件。
    """
    rows = frame.rotation
    transposed = tuple(rows[col * 3 + row] for row in range(3) for col in range(3))
    origin = tuple(-sum(rows[col * 3 + row] * frame.origin_mm[col] for col in range(3))
                   for row in range(3))
    return CoordFrame(origin, transposed)


def tool_pose_in_model(joints: dict[str, float], chain: Chain, frame: CoordFrame) -> Transform4x4:
    """关节输入 → 工具安装面在**模型坐标系**内的位姿（16 元素**行主序**，mm）。

    ＝ `fk` 的设备框位姿左乘 `frame` 的逆框。播放每帧调一次：壳侧插值出关节、经此得到与视口里
    模型**同空间**的位姿，再 `to_column_major` 上屏（03 §5 口径：core 全链行主序、three.js 列主序）。
    末端取 `chain.effective_end`——请求的 `end_link`（如现场链的 flange）是被动连杆、已被摘除，
    其位姿与 effective_end 同源（见 `derive_chain`）。
    """
    device = fk(joints, chain.model)[chain.effective_end]
    return multiply(frame_inverse(frame).matrix(), device)


def _speed(cfg: MachineConfig, kind: str) -> float:
    """该段型的目标速度（mm/s）＝`limits` 里对应键，经 `speed_max_mm_s` 上界钳制。

    两键均由加载器强制为正数（`core/config/validate.py::limits_section`），故无需再判零。
    """
    speed = getattr(cfg.limits, _SPEED_KEY[kind])
    return min(speed, cfg.limits.speed_max_mm_s)


def _solve_points(points: list[Waypoint], cfg: MachineConfig, chain: Chain,
                  frame: CoordFrame) -> list[tuple[dict[str, float], str]]:
    """逐点求关节目标：返回 [(解, 人话原因)]，解不出时解为空表、原因非空。

    上一点的解作 seed 传给 `ik` ⇒ 多解里选**连续**的那一支（卡片步骤 2）。解出后立刻过
    `check_limits`：`ik` 只保证在自己读到的行程内选解，而 `check_limits` 还要查**双驱同步偏差**
    （T04 口径：禁发判据以返回空表为准），两道都过才算这点可用。
    """
    out: list[tuple[dict[str, float], str]] = []
    seed: dict[str, float] = {}
    for point in points:
        joints, why = _solve_one(point.pos_mm, cfg, chain, frame, seed)
        if joints:
            seed = joints
        out.append((joints, why))
    return out


def _solve_one(pos_mm: Point, cfg: MachineConfig, chain: Chain, frame: CoordFrame,
               seed: dict[str, float]) -> tuple[dict[str, float], str]:
    """单个点位 → (关节目标, 原因)。目标位姿按**纯平移**构造（模块 docstring ①）。"""
    device = model_to_device(pos_mm, frame)
    try:
        joints = ik(translation(*device), chain, seed)
    except IkError as exc:
        return {}, str(exc)
    violations = check_limits(joints, cfg)
    if violations:
        return {}, _describe_violations(violations)
    return joints, ""


def _describe_violations(violations: list[Violation]) -> str:
    """把 `check_limits` 的违规项写成人话（含轴号／数值／限值，禁上屏术语 02 §2）。"""
    parts = []
    for item in violations:
        low, high = item.limit
        if item.kind == "sync":
            parts.append(f"双驱 {item.group} 同步偏差 {item.value:g} mm 超容差 ±{high:g} mm")
        else:
            parts.append(f"轴 {item.axis_id} 目标 {item.value:g} {item.unit}"
                         f" 超行程 [{low:g}, {high:g}] {item.unit}")
    return "；".join(parts)


def _distance(a: Point, b: Point) -> float:
    """两点欧氏距离（mm）。`CoordFrame` 是刚体变换 ⇒ 模型框与设备框内数值相同。"""
    return math.sqrt(sum((a[index] - b[index]) ** 2 for index in range(3)))
