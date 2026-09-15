"""core.kinematics.fk —— 运动学链与正解（T04）。

单位与坐标系（S-1 契约第 7 章）：长度 **mm**、角度 **deg**；设备坐标系为**右手系**、
Z 竖直向上为正；fk 输出的每部件位姿均在**设备坐标系**内（根连杆＝设备原点），要上屏再经
`transform.device_to_scene`。

⚠️ **一处输入数据缺口（不是本单能推断的，已在交付汇报里登记）**：「哪根轴驱动哪根连杆、
沿哪个坐标轴动」在 `machine.yaml` 里**只存在于注释**——03 §4 的字段表是
`links: [{id, length_mm, parent}]`，没有轴绑定与运动方向；而《踏勘确认清单》第 7 项写明它
「**决定运动学链的正确定义**」＝待回执（ZA1／ZA2 的层级关系、RC 的旋转基准轴）。故本模块把
这份绑定当**显式输入**（`Joint` 表，`build_model` 的入参），代码内**不写死任何机台拓扑**；
样例绑定只活在 tests。回执到达后只改配置（或调用方给的绑定表），**不改本文件**。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from core.config.schema import AXIS_TYPES, Axis, Link, MachineConfig
from core.kinematics.transform import AXES_XYZ, Transform4x4, identity, multiply, rotation, \
    translation

PRISMATIC, REVOLUTE = AXIS_TYPES  # 移动副／回转副；取自 schema 常量以免代码里散写字面量


@dataclass(frozen=True)
class Joint:
    """一根连杆的驱动绑定。**这是机台数据、不是代码可推断的**（见模块 docstring）。

    link_id＝`links` 表内 id；axis_id＝`axes` 表内 id（None＝该连杆无驱动轴，如 base／flange）；
    motion＝"x"|"y"|"z"，移动副的平移方向／回转副的转轴，**在设备坐标系内**（右手系）。
    `links.length_mm` 亦沿 motion 施加——03 §4 未定义它的方向，契约 Q-11 图纸回执前按
    「与该级运动同轴」处理（当前全为占位 0.0，故数值上无影响；回执后只改配置）。
    """

    link_id: str
    motion: str
    axis_id: str | None = None


@dataclass(frozen=True)
class KinematicModel:
    """已解析的运动学链（fk 每次调用复用，避免 T07／T08 高频重算拓扑）。

    order＝父先于子的拓扑序；joints／links 均以连杆 id 为键；cfg 为整份定型配置。
    """

    cfg: MachineConfig
    order: tuple[str, ...]
    joints: Mapping[str, Joint]
    links: Mapping[str, Link]


def build_model(cfg: MachineConfig, joints: Sequence[Joint]) -> KinematicModel:
    """把 `machine.yaml` 的 links 拓扑与调用方给定的驱动绑定解析成 fk 可复用的链。

    校验四条，任一不成立即 ValueError（**禁静默降级**）：① links 恰有一个根；② 除根外每根
    连杆都有绑定、且绑定里没有 links 表外的 id；③ motion 合法、axis_id 在 axes 表内；
    ④ parent 关系无环且连通（否则有连杆永远算不到位姿）。
    """
    links = {link.id: link for link in cfg.links}
    bound = {joint.link_id: joint for joint in joints}
    roots = [link.id for link in cfg.links if link.parent is None]
    if len(roots) != 1:
        raise ValueError(f"links 应恰有 1 个根（parent 为 null），实得 {len(roots)} 个：{roots}")
    outside = sorted(set(bound) - set(links))
    unbound = sorted(set(links) - set(bound) - set(roots))
    if outside or unbound:
        raise ValueError(f"驱动绑定与 links 表不符：表外 {outside}；未绑定 {unbound}")
    for joint in joints:
        if joint.motion not in AXES_XYZ:
            raise ValueError(f"links[{joint.link_id}] 的 motion 应为 {AXES_XYZ} 之一，"
                             f"实得 {joint.motion!r}")
        if joint.axis_id is not None and joint.axis_id not in cfg.axes:
            raise ValueError(f"links[{joint.link_id}] 绑定的轴 `{joint.axis_id}` 不在 axes 表内")
    return KinematicModel(cfg, _chain_order(cfg.links, roots[0]), bound, links)


def _chain_order(links: Sequence[Link], root: str) -> tuple[str, ...]:
    """按 parent 关系广度优先，返回父先于子的拓扑序；有环或不连通即 ValueError。"""
    children: dict[str | None, list[str]] = {}
    for link in links:
        children.setdefault(link.parent, []).append(link.id)
    order: list[str] = []
    queue = [root]
    while queue:
        current = queue.pop(0)
        order.append(current)
        queue.extend(children.get(current, ()))
    if len(order) != len(links):
        raise ValueError(f"links 有环或不连通：自根可达 {len(order)} 个、表内 {len(links)} 个")
    return tuple(order)


def fk(joint_values: Mapping[str, float], model: KinematicModel) -> dict[str, Transform4x4]:
    """正解：每根连杆在**设备坐标系**内的位姿，行主序 16 元素；平移 mm、回转 deg。

    `joint_values` 以轴 id 为键，值为该轴输入（缺项按 0.0＝全零位）；**键的语义随耦合而定**
    ——`ratio` 自指轴（X3 三级筒）给的是驱动位移，其余轴给的是工程位置，见 `resolve_positions`。
    每级局部位姿＝沿该级 motion 轴偏移 `length_mm`，再叠加移动副位移或绕 motion 轴的回转；
    倍率一律取自配置，**禁在代码里写死**。
    """
    positions = resolve_positions(joint_values, model.cfg)
    poses: dict[str, Transform4x4] = {}
    for link_id in model.order:
        link = model.links[link_id]
        joint = model.joints.get(link_id)
        axis = model.cfg.axes[joint.axis_id] if joint is not None and joint.axis_id else None
        value = positions[axis.id] if axis is not None else 0.0
        local = _local_transform(link, joint, axis, value)
        parent = poses[link.parent] if link.parent is not None else None
        poses[link_id] = local if parent is None else multiply(parent, local)
    return poses


def _local_transform(link: Link, joint: Joint | None, axis: Axis | None,
                     value: float) -> Transform4x4:
    """单级局部位姿（mm／deg，右手系）：先沿 motion 轴偏移 length_mm，再叠加该轴的运动。"""
    if joint is None:
        return identity()
    shift = link.length_mm
    if axis is not None and axis.type == PRISMATIC:
        shift += value
    pose = _shift_along(joint.motion, shift)
    if axis is not None and axis.type == REVOLUTE:
        pose = multiply(pose, rotation(joint.motion, value))
    return pose


def _shift_along(motion: str, distance_mm: float) -> Transform4x4:
    """沿设备坐标系 motion 轴平移 distance_mm（mm）。"""
    vector = [0.0, 0.0, 0.0]
    vector[AXES_XYZ.index(motion)] = distance_mm
    return translation(*vector)


def resolve_positions(joint_values: Mapping[str, float],
                      cfg: MachineConfig) -> dict[str, float]:
    """关节输入 → 各轴**工程位置**（移动副 mm、回转副 deg）；两型耦合都在此展开。

    - `ratio` 且 master **指向自身** ⇒ 驱动级倍速（03 §4／T04 卡 2026-09-16 定案）：输入是
      **驱动位移**，工程位置 = 输入 × ratio（X3 三级筒即此支）。⛔ 禁读成跨轴约束。
    - `ratio` 且 master 指向别的轴 ⇒ 跨轴约束：从动轴工程位置 = 主动轴工程位置 × ratio，
      **输入里给从动轴的值被覆盖**（约束优先，避免调用方传进自相矛盾的一对值）。
    - `sync` ⇒ 不改位置（同步偏差属校核，见 `limits.check_limits`）。
    ratio 一律读配置；踏勘第 4 项回执若定为「软件下发三级筒实际位置」，届时改掉该轴的
    coupling 即可（**只改 `machine.yaml`、不改本文件**）。master 链成环即 ValueError。
    """
    pending = dict(cfg.axes)
    out: dict[str, float] = {}
    for _ in range(len(pending) + 1):
        for axis_id, axis in list(pending.items()):
            coupling = axis.coupling
            drive = float(joint_values.get(axis_id, 0.0))
            if coupling is None or coupling.type != "ratio":
                out[axis_id] = drive
            elif coupling.master == axis_id:
                out[axis_id] = drive * coupling.ratio
            elif coupling.master in out:
                out[axis_id] = out[coupling.master] * coupling.ratio
            else:
                continue
            del pending[axis_id]
        if not pending:
            return out
    raise ValueError(f"ratio 耦合的 master 链成环，无法解析：{sorted(pending)}")


def raw_to_eng(axis: Axis, raw: float) -> float:
    """PLC 原始计数 → 工程值（移动副 mm、回转副 deg）；契约 §7.4「最高危项」的换算式。

    契约原文＝(原始值 − 零点原始值) × 比例系数 × 方向符号，其中零点以**计数**为单位；而
    `machine.yaml` 的字段是 `zero_offset_mm|deg`（键名后缀即单位＝工程值）。二者等价：令
    zero_offset ≡ 零点原始值 × scale × direction（＝机械零点处的工程读数），代入即得
        **工程值 = 原始值 × scale × direction − zero_offset**
    本实现按此式，故配置里填的是**工程单位**的零点偏移。`scale` 为 null＝回读已是工程值
    （03 §4）⇒ 按 1.0 处理。⚠️ 三参属标定四要素（规程 W-7.2），**现场逐项实测前不得据此
    判定零点**；当前 22 轴全为占位（scale null、零点 0、正方向 +1）。
    """
    scale = 1.0 if axis.scale is None else axis.scale
    return raw * scale * axis.direction - axis.zero_offset
