"""core.collision_report —— 干涉清单的**归并呈现层**（T16；01 蓝图 §3.4③/§3.8、卡面步骤 1）。

为什么单列一件：``core/collision.py`` 已满 300/300（99 台账 L-8，⛔ 一行都不许加），而「按设备
归并」只是校核结果的**再投影**——三态判定、包络、双阻断一行不动，本件只读 ``CollisionResult``
的现成类型与装配树，输出两份视图数据（设备组→涉事步数；干涉对明细），供右栏清单、报警模态与
轨迹清单「涉事设备」列共用同一份（单一口径，禁三处各算各的）。

设备组口径（演示稿画面 06：「压机立柱3 · 上横梁 11 步」）：涉事**零件**（``case.part_b``）在装配树
里所属的**父装配节点名**＝设备组；顶层零件（无父组）＝自身名。零件不在树里＝树已换而结果未作废的
异常态，**如实跳过并告警**（`skipped` 记录＋warning 日志），⛔ 禁造组名、⛔ 禁把它塞进任何组。
GUI-free（无 PySide6 import，03 §3 core 铁律）；⛔ 不算几何、不改判定、不缓存真值。
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.collision import CollisionCase, CollisionResult

if TYPE_CHECKING:  # 只取类型：本模块运行期不依赖几何导入（树按鸭子类型只读 name/children）
    from core.geometry.import_model import AssemblyNode

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class DeviceClash:
    """一个设备组的归并行：组名＋涉事零件＋该组涉事记录（按最小距离升序，沿 cases 原序）。"""

    group: str
    member: str
    cases: tuple[CollisionCase, ...]


@dataclass(frozen=True)
class ClashReport:
    """归并结果（frozen，一次算完多处只读）。``by_device`` 按涉事记录数降序（最危险设备在前，
    同数按组名稳定排序）；``skipped``＝不在装配树里的涉事零件名（已告警、未归组）。"""

    by_device: tuple[DeviceClash, ...]
    skipped: tuple[str, ...]

    def group_of(self, part_b: str) -> str | None:
        """零件名 → 设备组名（轨迹清单「涉事设备」列用）；不在任何组（含 skipped）⇒ None。"""
        for item in self.by_device:
            if item.member == part_b:
                return item.group
        return None

    def headline(self) -> str:
        """清单首行：设备归并摘要；无归组干涉（空结果或全 skipped）⇒ 空串由调用方显「—」。"""
        return "；".join(f"{item.group} · {item.member}（{len(item.cases)} 处）"
                        for item in self.by_device)


def group_by_device(result: CollisionResult,
                    tree: Sequence["AssemblyNode"]) -> ClashReport:
    """校核结果＋装配树 → 归并报告。cases 空即空报告（无干涉 ⛔ 不造行）；组内记录沿用
    ``result.cases`` 的最小距离升序（[0] 即该组最危险一条）。"""
    if not result.cases:
        return ClashReport(by_device=(), skipped=())
    parents = _group_names(tree)
    buckets: dict[tuple[str, str], list[CollisionCase]] = {}
    skipped: list[str] = []
    for case in result.cases:                       # cases 已按最小距离升序（core.collision.check）
        group = parents.get(case.part_b)
        if group is None:
            log.warning("涉事零件 %s 不在当前装配树里（模型已换而结果未作废？）：本组不归并、"
                        "只保留干涉对明细，请重新校核", case.part_b)
            if case.part_b not in skipped:
                skipped.append(case.part_b)
            continue
        buckets.setdefault((group, case.part_b), []).append(case)
    rows = tuple(sorted((DeviceClash(g, m, tuple(cs)) for (g, m), cs in buckets.items()),
                        key=lambda r: (-len(r.cases), r.group, r.member)))
    return ClashReport(by_device=rows, skipped=tuple(skipped))


def _group_names(tree: Sequence["AssemblyNode"]) -> dict[str, str]:
    """零件名 → 设备组名（父装配节点名；顶层零件＝自身名）。同名零件取**首个**出现组（确定性 ⛔
    不随机覆盖）；真实导入树的命名计数器保证叶名唯一（``import_model._Namer``），重名只见于替身。"""
    out: dict[str, str] = {}
    queue: list[tuple["AssemblyNode", str | None]] = [(n, None) for n in tree]
    while queue:
        node, parent = queue.pop(0)                # 广度优先＝「首个」按树序（同 iter_parts 口径）
        if node.is_assembly:
            queue.extend((child, node.name) for child in node.children)
        else:
            out.setdefault(node.name, parent or node.name)
    return out
