"""core.geometry.edit_model —— 已导入装配的删除/重建纯函数（T13；裁决 6 授权新增）。

供装配树工具行「删除选中／删除整组／清空全部模型」用：输入导入结果（Assembly＋显示网格），
输出**删除指定叶子零件后**的新 Assembly／新网格表——本包只做纯函数（禁 I/O、禁桥、禁改入参），
「沿用现路径/校核失效机制」的接线在外壳（app/wiring.py）。⛔ 不改 T05/T06 已验收件的既有行为与
签名；本件与 import_model/tessellate 并列，经包 ``__init__`` re-export。

口径：``drop_ids`` 一律是**叶子零件 node_id**（装配树选中信号给的正是叶子 id；「删除整组」由
调用方把组内全部叶子 id 展开后传入——树控件 ``_leaf_ids`` 已有该展开）。子装配被删空则整节点
移除（不留空壳）；``stats['parts']`` 随之重算，其余统计键原样保留（tris 等显示值由重网格化更新，
本件不重算——纯函数不碰 tessellate 的缓存）。
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace

from core.geometry.import_model import Assembly, AssemblyNode
from core.geometry.tessellate import MeshPart

__all__ = ["part_count", "prune_tree", "drop_mesh_parts", "remove_parts"]


def part_count(nodes: Iterable[AssemblyNode]) -> int:
    """树里的叶子零件数（「件数」徽标/日志的单一算式；与 ``Assembly.iter_parts`` 同序同口径）。"""
    return sum(part_count(n.children) if n.is_assembly else 1 for n in nodes)


def prune_tree(nodes: Iterable[AssemblyNode], drop_ids: set[int]) -> list[AssemblyNode]:
    """返回删除 ``drop_ids`` 叶子后的新树（递归重建，不改入参；子装配删空即移除）。"""
    out: list[AssemblyNode] = []
    for node in nodes:
        if not node.is_assembly:
            if node.node_id not in drop_ids:
                out.append(node)
            continue
        children = prune_tree(node.children, drop_ids)
        if children:
            out.append(replace(node, children=children))
    return out


def drop_mesh_parts(parts: Iterable[MeshPart], drop_ids: set[int]) -> list[MeshPart]:
    """显示网格表同步删件（MeshPart.id＝node_id，与视口 mesh.load 的 id 同源）。"""
    return [p for p in parts if p.id not in drop_ids]


def remove_parts(asm: Assembly, drop_ids: Iterable[int]) -> Assembly:
    """删除指定叶子零件后的新 Assembly（纯函数）：树剪枝＋网格无关（网格另行 ``drop_mesh_parts``），
    ``stats['parts']`` 重算、其余统计键保留。删空 ⇒ 空 tree（调用方据此回退「未导入」门禁态）。"""
    ids = set(drop_ids)
    tree = prune_tree(asm.tree, ids)
    out = replace(asm, tree=tree)
    out.stats = {**asm.stats, "parts": part_count(tree)}
    return out
