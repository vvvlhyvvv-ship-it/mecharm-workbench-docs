"""core.kinematics.limits —— 行程与双驱同步校核（T04）。

单位（S-1 契约第 7 章）：移动副行程 **mm**、回转副行程 **deg**；同步偏差与 `sync_tol_mm`
恒为 **mm**。校核对象是**工程位置**（耦合已按 `fk.resolve_positions` 展开），故 X3 这类
驱动级倍速轴先换算再比行程——**禁拿驱动位移去比**，那会少算一个倍率。

容差与行程**全部来自 `machine.yaml`**（`travel`／`coupling.sync_tol_mm`），本文件内
无任何硬编码数值（03 §4「界面零硬编码」、04 §5.5 附3）。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from core.config.schema import UNIT_BY_TYPE, Axis, MachineConfig
from core.kinematics.fk import resolve_positions


@dataclass(frozen=True)
class Violation:
    """一处校核不通过（`check_limits` 的返回项；含轴号／值／限值，T04 卡步骤 3）。

    kind＝"travel"（行程越界）｜"sync"（双驱同步偏差超差）；axis_id＝越界轴／偏差最大侧轴；
    value 与 limit 同单位（travel 随轴型 mm｜deg，sync 恒 mm）；limit＝(下界, 上界)，sync 型
    为 (−sync_tol_mm, +sync_tol_mm)，故两种 kind 都满足「value 出界即违规」；
    group＝sync 的 `coupling.group`（travel 为 None）。
    """

    kind: str
    axis_id: str
    value: float
    limit: tuple[float, float]
    unit: str
    group: str | None = None


def check_limits(joint_values: Mapping[str, float], cfg: MachineConfig) -> list[Violation]:
    """行程与双驱同步校核，一次返回**全部**不通过项（不逐条抛）；容差全来自配置。

    `joint_values` 的键语义与 fk 一致（缺项按全零位）。T07／T08 的「禁发」判据应以本函数
    返回**空表**为准——travel 与 sync 两类都在这里出，避免调用方只查行程漏掉同步偏差。
    """
    positions = resolve_positions(joint_values, cfg)
    out: list[Violation] = []
    for axis in cfg.axes.values():
        value = positions[axis.id]
        low, high = axis.travel
        if value < low or value > high:
            out.append(Violation("travel", axis.id, value, (low, high), UNIT_BY_TYPE[axis.type]))
    out.extend(_sync_violations(positions, cfg))
    return out


def _sync_violations(positions: Mapping[str, float], cfg: MachineConfig) -> list[Violation]:
    """同一 `coupling.group` 内各轴工程位置的极差 > sync_tol_mm 即报（配置驱动、无硬编码）。

    ⚠️ 现状：附录A「驱动形式」列的多驱动单元（大车四轮各一只液压马达、机架四只升降伺服
    油缸）**未被单列为轴**，故每个 group 现只有 1 根轴、极差恒 0，本函数不会触发；契约
    §6.4-bit3 亦声明 Q-9 回执前不启用该监视（`machine.yaml` 的 sync_tol_mm 同为占位）。
    回执把驱动单元列为轴后**本函数自动生效、不改码**。
    """
    groups: dict[str, list[Axis]] = {}
    for axis in cfg.axes.values():
        coupling = axis.coupling
        if coupling is not None and coupling.type == "sync" and coupling.group is not None:
            groups.setdefault(coupling.group, []).append(axis)
    out: list[Violation] = []
    for group, members in groups.items():
        readings = [(positions[axis.id], axis.id) for axis in members]
        high_value, high_id = max(readings)
        spread = high_value - min(readings)[0]
        first = members[0]
        tolerance = first.coupling.sync_tol_mm
        if spread > tolerance:
            out.append(Violation("sync", high_id, spread, (-tolerance, tolerance), "mm", group))
    return out
