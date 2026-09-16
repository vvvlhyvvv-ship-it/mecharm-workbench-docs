"""core.geometry.tessellate —— 三角化、face_map 构建、显示网格缓存、桥载荷序列化。

``tessellate(assembly, deflection)`` 按部件出 ``MeshPart``：顶点 (n,3) float32（mm）、
索引 (m,3) uint32、``face_map`` (m,) int32（三角形→B-Rep 面 id）。face_id 全局唯一递增、
跨部件不冲突，并在 core 侧保留 ``face_index``（face_id→活 TopoDS_Face）——这是 T06 由拾取
三角形反查真值法向的**唯一依据**，不落此表 T06 做不了（03 §3）。``face_map``/``face_index``
**不下发前端**（禁前端做几何判定）。

双缓存（均落 ``paths.cache_dir`` 仓外、键＝源文件哈希）：① 显示网格 mesh.npz（每部件顶点/索引/
face_map + meta），命中即免三角化（二次导入秒开）；② 几何真身 ``.brep``（见 ``core.geometry.
brep_cache``），供命中路径重建活形状与 ``face_index``——否则全命中时 ``face_index`` 会空着，挖空
T06 反查真值法向的唯一依据。命中显示网格后，优先由 ``.brep`` 读回形状重建 ``face_index``，``.brep``
缺失才回退重新解析源文件。
"""

from __future__ import annotations

import base64
import json
import logging
import pathlib
from dataclasses import dataclass, field

import numpy as np

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import topods

from core.geometry.brep_cache import load_shapes, rebuild_face_index, save_shapes
from core.geometry.import_model import (Assembly, AssemblyNode, GeometryError, _cache_root,
                                        _parse)

log = logging.getLogger(__name__)

# 三角化角度容差（rad），OCCT 默认值；弦高容差 deflection 由调用方按配置传入。
_ANG_DEFLECTION = 0.5


@dataclass
class MeshPart:
    """单个零件的显示网格。``vertices`` (n,3) float32（mm）、``tris`` (m,3) uint32（顶点索引）、
    ``face_map`` (m,) int32（三角形所属 B-Rep 面 id）；``face_index`` face_id→活 TopoDS_Face，
    **不序列化、不下发前端**。"""

    id: int
    name: str
    vertices: np.ndarray
    tris: np.ndarray
    face_map: np.ndarray
    face_index: dict = field(default_factory=dict)


# --------------------------------------------------------------------------- #
# 显示网格缓存（mesh.npz）
# --------------------------------------------------------------------------- #
def _mesh_path(key: str, deflection: float) -> pathlib.Path | None:
    root = _cache_root()
    return None if root is None else root / "mesh" / f"{key}_{deflection:g}.npz"


def _save_mesh(key: str, deflection: float, parts: list[MeshPart]) -> None:
    """写显示网格缓存（每部件顶点/索引/face_map + meta）。失败仅告警。"""
    path = _mesh_path(key, deflection)
    if path is None:
        return
    arrays: dict[str, np.ndarray] = {}
    meta = []
    for i, p in enumerate(parts):
        arrays[f"v{i}"] = p.vertices
        arrays[f"t{i}"] = p.tris
        arrays[f"f{i}"] = p.face_map
        meta.append({"id": p.id, "name": p.name})
    arrays["meta"] = np.array(json.dumps(meta, ensure_ascii=False))
    try:
        np.savez(path, **arrays)
    except OSError as exc:
        log.warning("写显示网格缓存失败（忽略）：%s", exc)


def _load_mesh(key: str, deflection: float) -> list[MeshPart] | None:
    """读显示网格缓存；命中返回 MeshPart 列表（face_index 空，显示用），否则 None。"""
    path = _mesh_path(key, deflection)
    if path is None or not path.is_file():
        return None
    try:
        with np.load(path, allow_pickle=False) as z:
            meta = json.loads(str(z["meta"]))
            return [MeshPart(id=int(m["id"]), name=str(m["name"]), vertices=z[f"v{i}"],
                             tris=z[f"t{i}"], face_map=z[f"f{i}"], face_index={})
                    for i, m in enumerate(meta)]
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        log.warning("显示网格缓存损坏，按未命中处理：%s", exc)
        return None


# --------------------------------------------------------------------------- #
# 三角化主流程
# --------------------------------------------------------------------------- #
def tessellate(assembly: Assembly, deflection: float) -> list[MeshPart]:
    """按部件三角化，弦高容差 ``deflection``（mm，须为正）。命中显示网格缓存则免三角化。

    每个 MeshPart 附 ``face_map`` 与 core 侧 ``face_index``（face_id→活面），供 T06 取真值法向。
    """
    if deflection <= 0:
        raise GeometryError(f"弦高容差必须为正数（mm），收到 {deflection}")
    cached = _load_mesh(assembly.source_hash, deflection)
    if cached is not None:
        _fill_tris(assembly, cached)
        _ensure_face_index(assembly, cached, deflection)
        assembly.stats["cache"] = "hit"
        log.info("缓存命中（显示网格）：%s，%d 个三角面",
                 pathlib.Path(assembly.source_path).name, assembly.stats["tris"])
        return cached
    _attach_shapes_if_needed(assembly)
    parts: list[MeshPart] = []
    face_id = 0
    for node in assembly.iter_parts():
        mp, face_id = _tessellate_part(node, deflection, face_id)
        if mp is not None:
            parts.append(mp)
    _fill_tris(assembly, parts)
    _save_mesh(assembly.source_hash, deflection, parts)
    save_shapes(assembly)
    log.info("三角化完成：%s，%d 个部件，%d 个三角面，弦高 %.3g mm",
             pathlib.Path(assembly.source_path).name, len(parts),
             assembly.stats["tris"], deflection)
    return parts


def _ensure_face_index(assembly: Assembly, parts: list[MeshPart], deflection: float) -> None:
    """显示网格命中路径下重建非空 ``face_index``（T06 反查真值法向的唯一依据）。

    缓存命中的 MeshPart 来自 mesh.npz，``face_index`` 是空的。优先由 ``.brep`` 几何真身缓存读回
    活形状（其三角化随 ``.brep`` 一并保留，免解析源文件）；``.brep`` 缺失才回退重新解析源文件，
    并按同 deflection 重新三角化以恢复各面的三角化状态，最后按 ``face_map`` 重建 face_index。
    面片模型（is_brep=False）无 B-Rep 真值法向语义，跳过。
    """
    if not assembly.is_brep:
        return
    if not load_shapes(assembly):
        _attach_shapes_if_needed(assembly)
        for node in assembly.iter_parts():
            if node.shape is not None and not node.shape.IsNull():
                BRepMesh_IncrementalMesh(node.shape, deflection, False, _ANG_DEFLECTION, False)
    rebuild_face_index(assembly, parts)


def _fill_tris(assembly: Assembly, parts: list[MeshPart]) -> None:
    """把三角面总数回填进 stats['tris']（统计行「面数」用）。"""
    assembly.stats["tris"] = int(sum(p.tris.shape[0] for p in parts))


def _attach_shapes_if_needed(assembly: Assembly) -> None:
    """缓存命中重建的 Assembly 无活形状；三角化未命中显示缓存时重新解析源文件附着形状。"""
    if all(n.shape is not None for n in assembly.iter_parts()):
        return
    src = pathlib.Path(assembly.source_path)
    log.info("显示网格缓存未命中且无活形状，重新解析源文件：%s", src.name)
    fresh = _parse(src, assembly.source_hash, assembly.ext)
    assembly.tree = fresh.tree
    assembly.is_brep = fresh.is_brep


def _tessellate_part(node: AssemblyNode, deflection: float,
                     face_id: int) -> tuple[MeshPart | None, int]:
    """三角化单个零件叶子：对每个 B-Rep 面分配全局 face_id，提取顶点/三角形并记 face_map。"""
    shape = node.shape
    if shape is None or shape.IsNull():
        return None, face_id
    BRepMesh_IncrementalMesh(shape, deflection, False, _ANG_DEFLECTION, False)
    verts: list[tuple[float, float, float]] = []
    tris: list[tuple[int, int, int]] = []
    face_map: list[int] = []
    face_index: dict[int, object] = {}
    voffset = 0
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        face = topods.Face(exp.Current())
        loc = TopLoc_Location()
        tri = BRep_Tool.Triangulation(face, loc)
        if tri is not None:
            face_id += 1
            face_index[face_id] = face
            voffset = _extract_face(tri, loc.Transformation(), verts, tris, face_map,
                                    face_id, voffset)
        exp.Next()
    if not tris:
        return None, face_id
    return MeshPart(id=node.node_id, name=node.name,
                    vertices=np.asarray(verts, dtype=np.float32).reshape(-1, 3),
                    tris=np.asarray(tris, dtype=np.uint32).reshape(-1, 3),
                    face_map=np.asarray(face_map, dtype=np.int32),
                    face_index=face_index), face_id


def _extract_face(tri, trsf, verts, tris, face_map, face_id, voffset) -> int:
    """把一个 Poly_Triangulation 的节点（施加 location 变换）与三角形并入累积列表，返回新 voffset。
    三角形顶点序保持 OCC 原始绕向，供 T06 定法向。"""
    n_nodes = tri.NbNodes()
    for i in range(1, n_nodes + 1):
        p = tri.Node(i)
        p.Transform(trsf)
        verts.append((p.X(), p.Y(), p.Z()))
    for i in range(1, tri.NbTriangles() + 1):
        n1, n2, n3 = tri.Triangle(i).Get()
        tris.append((voffset + n1 - 1, voffset + n2 - 1, voffset + n3 - 1))
        face_map.append(face_id)
    return voffset + n_nodes


def encode_mesh_parts(parts: list[MeshPart]) -> list[dict]:
    """把 MeshPart 序列化为桥 ``mesh.load`` 载荷：顶点/索引转小端 base64（前端 Float32/Uint32 直解）。
    ``face_map`` 与 ``face_index`` 留 core 侧，**不下发前端**。"""
    out = []
    for p in parts:
        verts = np.ascontiguousarray(p.vertices, dtype="<f4").tobytes()
        tris = np.ascontiguousarray(p.tris, dtype="<u4").tobytes()
        out.append({
            "id": int(p.id), "name": p.name,
            "n_vertices": int(p.vertices.shape[0]), "n_tris": int(p.tris.shape[0]),
            "vertices": base64.b64encode(verts).decode("ascii"),
            "tris": base64.b64encode(tris).decode("ascii"),
        })
    return out
