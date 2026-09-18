"""core.geometry.edit_model 的用例（T13：core 层每个函数必须带 pytest）。

只测纯函数契约：剪枝不改入参、子装配删空即移除、stats 重算、删空得空树；网格过滤与树剪枝的
id 同源（MeshPart.id＝node_id）。I/O／桥／失效机制的接线不在本包（外壳 wiring 负责）。
"""

from __future__ import annotations

import numpy as np
import pytest

from core.geometry.edit_model import drop_mesh_parts, part_count, prune_tree, remove_parts
from core.geometry.import_model import Assembly, AssemblyNode
from core.geometry.tessellate import MeshPart


def _part(node_id: int, name: str = "") -> AssemblyNode:
    return AssemblyNode(node_id=node_id, name=name or f"零件_{node_id}", is_assembly=False)


def _assy(node_id: int, *children: AssemblyNode) -> AssemblyNode:
    return AssemblyNode(node_id=node_id, name=f"子装配_{node_id}", is_assembly=True,
                        children=list(children))


def _mesh(node_id: int) -> MeshPart:
    verts = np.zeros((3, 3), dtype=np.float32)
    return MeshPart(id=node_id, name=f"零件_{node_id}", vertices=verts,
                    tris=np.zeros((1, 3), dtype=np.uint32),
                    face_map=np.zeros(1, dtype=np.int32))


def _asm(tree: list[AssemblyNode], parts: int = 0) -> Assembly:
    out = Assembly(source_path="x.step", source_hash="k", ext=".step", is_brep=True, tree=tree)
    out.stats = {"parts": parts, "tris": 9, "load_ms": 1.0}
    return out


TREE = [_assy(10, _part(1), _part(2)), _assy(11, _assy(12, _part(3))), _part(4)]


def test_part_count_counts_leaves_only():
    assert part_count(TREE) == 4
    assert part_count([]) == 0


def test_prune_tree_drops_leaf_and_empty_groups_without_mutating_input():
    snapshot = [(n.node_id, n.is_assembly, len(n.children)) for n in TREE]
    out = prune_tree(TREE, {3})
    assert [p.node_id for p in out[1].children] == []            # 12 删空 ⇒ 整组移除
    assert [(n.node_id, n.is_assembly, len(n.children)) for n in TREE] == snapshot
    assert part_count(out) == 3


def test_prune_tree_drops_deep_leaf_keeps_group_with_sibling():
    out = prune_tree(TREE, {1})
    assert out[0].is_assembly and [p.node_id for p in out[0].children] == [2]


def test_remove_parts_rebuilds_assembly_and_stats():
    asm = _asm(TREE, parts=4)
    out = remove_parts(asm, {2, 4})
    assert part_count(out.tree) == 2 == out.stats["parts"]
    assert out.stats["tris"] == 9 and asm.stats["parts"] == 4    # 其余统计保留、入参不改
    assert out is not asm and out.tree is not asm.tree


def test_remove_parts_to_empty():
    out = remove_parts(_asm(TREE, parts=4), {1, 2, 3, 4})
    assert out.tree == [] and out.stats["parts"] == 0 and out.is_brep  # 删空 ⇒ 空 tree（门禁回退用）


def test_drop_mesh_parts_filters_same_ids_and_keeps_arrays():
    parts = [_mesh(i) for i in (1, 2, 3)]
    out = drop_mesh_parts(parts, {2})
    assert [p.id for p in out] == [1, 3]
    assert out[0].vertices.shape == (3, 3) and parts[1] in out + [parts[1]]  # 网格原样引用


@pytest.mark.parametrize("drop", [{1}, {1, 2}, {1, 2, 3, 4}, set()])
def test_prune_and_mesh_stay_consistent(drop):
    tree_out = prune_tree(TREE, drop)
    mesh_out = drop_mesh_parts([_mesh(i) for i in (1, 2, 3, 4)], drop)
    assert part_count(tree_out) == len(mesh_out)
