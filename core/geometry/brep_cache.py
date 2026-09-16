"""core.geometry.brep_cache —— 几何真身（.brep）二进制缓存与 face_index 重建（T05 整改-1）。

派单卡目标③／步骤 4-① 要求「双缓存」：除显示网格 mesh.npz 外，须把每个零件叶子的几何真身
（B-Rep 形状）以 ``.brep`` 二进制落盘，键＝源文件哈希，落 ``paths.cache_dir`` 仓外（⛔ 绝不落仓内，
04 §7.1-10：缓存里是甲方模型几何，远端为公开仓）。显示网格缓存**全命中**时若不再解析源文件，
``face_index``（face_id→活 TopoDS_Face）会空着——T06 由拾取三角形反查真值法向就失去**唯一依据**，
而 criterion 6 仍会通过（这是「秒开」路径悄悄挖空 T06 的隐患）。本模块的 ``.brep`` 缓存让命中路径
无需源文件即可重建活形状与 ``face_index``。

本机实测（pythonocc-core **7.9.3**，2026-09-16）：``breptools.Write(shape, str(path))`` 落盘、
``breptools.Read(shape, str(path), BRep_Builder())`` 读回（**第三参 BRep_Builder 必需**），面序与
三角化均保留（centroids 按序相等、读回仍 all-triangulated）⇒ 由 ``face_map`` 重建 ``face_index``
精确：每部件起始 face_id＝``face_map.min()``，按 ``TopExp_Explorer`` 面序、**只对有三角化的面**递增
（与 ``tessellate._tessellate_part`` 的 face_id 分配口径逐字一致）。

⚠️ OCC 符号是小写模块级函数（``breptools``／``topods``）；CamelCase 类名（``BRepTools``／``TopoDS``）
在本机 build **不存在**。OCAF ``TDocStd_Document`` 确无 ``SaveAs``（仅 ``GetSavedTime/IsSaved/
SetSaved/SetSavedTime``），故几何真身落盘走 ``.brep`` 而非 OCAF ``SaveAs``。
"""

from __future__ import annotations

import logging
import pathlib

from OCC.Core.BRep import BRep_Builder, BRep_Tool
from OCC.Core.BRepTools import breptools
from OCC.Core.TopAbs import TopAbs_FACE
from OCC.Core.TopExp import TopExp_Explorer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import TopoDS_Shape, topods

from core.geometry.import_model import _cache_root

log = logging.getLogger(__name__)


def _brep_dir(key: str, *, create: bool = False) -> pathlib.Path | None:
    """``.brep`` 缓存目录 ``cache_dir/brep/{key}/``；缓存不可用返回 None（**绝不回落仓内**）。"""
    root = _cache_root()
    if root is None:
        return None
    d = root / "brep" / key
    if create:
        d.mkdir(parents=True, exist_ok=True)
    return d


def save_shapes(assembly) -> bool:
    """把每个零件叶子的几何真身写为 ``{node_id}.brep``（命中后二次导入无需源文件即可重建活形状）。

    仅实体模型（is_brep=True）有 B-Rep 真身可缓存；STL 面片模型直接跳过。全部成功返回 True，
    缓存不可用或任一写失败返回 False（仅告警、不影响主流程——显示仍走 mesh.npz）。
    """
    if not assembly.is_brep:
        return False
    d = _brep_dir(assembly.source_hash, create=True)
    if d is None:
        return False
    ok = True
    for node in assembly.iter_parts():
        if node.shape is None:
            ok = False
            continue
        path = d / f"{node.node_id}.brep"
        try:
            if not breptools.Write(node.shape, str(path)):
                log.warning("写 .brep 失败：%s", path.name)
                ok = False
        except Exception as exc:  # noqa: BLE001 - 缓存失败不得拖垮导入
            log.warning("写 .brep 异常（忽略）：%s", exc)
            ok = False
    return ok


def load_shapes(assembly) -> bool:
    """从 ``.brep`` 缓存读回每个零件叶子的活形状并附着到 node。全部成功 True，否则 False。"""
    if not assembly.is_brep:
        return False
    d = _brep_dir(assembly.source_hash)
    if d is None:
        return False
    ok = True
    for node in assembly.iter_parts():
        path = d / f"{node.node_id}.brep"
        if not path.is_file():
            ok = False
            continue
        shape = TopoDS_Shape()
        try:
            if breptools.Read(shape, str(path), BRep_Builder()) and not shape.IsNull():
                node.shape = shape
            else:
                ok = False
        except Exception as exc:  # noqa: BLE001
            log.warning("读 .brep 异常（忽略）：%s", exc)
            ok = False
    return ok


def rebuild_face_index(assembly, parts) -> None:
    """由活形状按 ``face_map`` 重建每个 MeshPart 的 ``face_index``（face_id→TopoDS_Face）。

    face_id 全局递增、每部件起始＝``face_map.min()``；``.brep`` 读回后面序与三角化保留（本机实测），
    故按 ``TopExp_Explorer`` 面序、只对有三角化的面依次赋 face_id，与原三角化口径完全一致。
    无活形状的部件跳过（调用方须先 ``load_shapes`` 或重新解析源文件附着形状）。
    """
    nodes = {n.node_id: n for n in assembly.iter_parts()}
    for p in parts:
        if p.face_index or p.face_map.size == 0:
            continue
        node = nodes.get(p.id)
        if node is None or node.shape is None or node.shape.IsNull():
            continue
        start = int(p.face_map.min())
        offset = 0
        exp = TopExp_Explorer(node.shape, TopAbs_FACE)
        while exp.More():
            face = topods.Face(exp.Current())
            loc = TopLoc_Location()
            if BRep_Tool.Triangulation(face, loc) is not None:
                p.face_index[start + offset] = face
                offset += 1
            exp.Next()
