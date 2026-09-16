"""core.geometry.face_point —— 由拾取三角形反查 B-Rep 面上的真实 3D 点与真值法向（T06）。

03 §3「取点／面心」两行的落码件。视口 raycaster 命中后回传 ``{mesh_id, face_id, u, v}``
（03 §5 ``pick.face`` 协议），本模块据此换算**模型坐标系（mm）**下的真实点与法向：

  ``face_point_from_tri(parts, mesh_id, face_id, u, v) -> FacePoint``  重心坐标→真实 3D 点＋真法向
  ``face_center(parts, mesh_id, face_id) -> FacePoint``                所命中 B-Rep 面的面心＋真法向

⚠️ **协议字段语义（与前端实现对齐，禁望文生义）**：``face_id`` 是**显示网格里三角形的序号**
（three.js ``intersect.faceIndex``），**不是** B-Rep 面 id——前端只拿到顶点／索引（``face_map``／
``face_index`` 一律不下发，03 §3），无从知道 B-Rep 面 id。本模块内部经 ``part.face_map[face_id]``
把三角形序号翻成 B-Rep 面 id，再经 ``part.face_index[brep_fid]`` 拿活 ``TopoDS_Face``。

**法向取自 B-Rep 面真值，⛔ 不是三角形法向**（03 §3、T06 卡关键点 1）：
``BRep_Tool.Surface(face)`` → ``ShapeAnalysis_Surface.ValueOfUV`` 把真实点投影回曲面参数 →
``GeomLProp_SLProps`` 求该参数处法向。圆柱侧面上真法向与三角形法向实测差 **2.318°**（弦高偏差）；
若两者恒等即说明取成了网格法向（打回判据，T06 卡 ③）。

**朝向口径**：返回的是曲面**参数化法向**（``GeomLProp_SLProps.Normal()``），与显示三角形绕向**同侧**
（自造基本体 box／cylinder 全 112 个三角面实测点积 >0、零翻转）。⛔ **不按 ``face.Orientation()``
翻转**——翻转会把「真法向 vs 三角形法向」的夹角从弦高偏差（≈2.3°）变成朝向差（≈177.7°），与本单判据
及 T05 记录的 2.318° 口径相悖。

⚠️ **数据源入参 ``parts``（对 03 §3 冻结签名的回填，同 T04 ``fk(joint_values, model)`` 先例）**：
原签名 ``face_point_from_tri(mesh_id,face_id,u,v)`` **没有任何几何来源**——顶点／三角形／``face_map``／
``face_index`` 全在 ``tessellate`` 产出的 ``list[MeshPart]`` 里，按字面无法实现。故取**损害最小**的第三条
路（同 03 §3 V1.5-③ 裁决）：把数据源 ``parts`` 作**显式首参**，零硬编码、调用方（壳）持有 ``parts`` 即可。
返回类型由 ``Point`` 改名 ``FacePoint``：``core.kinematics.Point`` 已是裸 ``(x,y,z)`` 元组别名，同名异义会
重蹈 ``Frame``／``CoordFrame`` 覆辙（03 §3 消歧注）。**两处均属请指挥方回填 §3 的报备项，本件不擅改文档。**

⚠️ 本机环境实测（pythonocc-core **7.9.3**，2026-09-16）：``GeomLProp_SLProps`` 收 ``Geom_Surface``
**句柄**（非 adaptor）；OCC 符号是**模块级小写函数** ``breptools``／``topods``／``brepgprop``，CamelCase
类名在本机 build 不存在；``BRep_Tool.Surface(face)`` 返回的曲面与 ``MeshPart.vertices`` **同处模型／世界
坐标系**（location 已并入），故真实点可直接喂 ``ValueOfUV``、法向无需再乘 location（移动圆柱实测验证）。

``face_index`` 在缓存**全命中**路径由 ``.brep`` 重建（T05 整改-1），故本模块在冷／热两条路径下同样可用
（收单必检：全命中真法向与冷路径逐面一致、点积≈1，见 tests/test_face_point.py）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

from OCC.Core.BRep import BRep_Tool
from OCC.Core.BRepGProp import brepgprop
from OCC.Core.GProp import GProp_GProps
from OCC.Core.GeomLProp import GeomLProp_SLProps
from OCC.Core.ShapeAnalysis import ShapeAnalysis_Surface
from OCC.Core.gp import gp_Pnt

from core.geometry.import_model import GeometryError

if TYPE_CHECKING:  # 仅类型注解用，运行期不导入（避免与 tessellate 形成不必要的运行期耦合）
    from core.geometry.tessellate import MeshPart

log = logging.getLogger(__name__)

# GeomLProp_SLProps 求法向：1 阶导即可定法向；分辨率 1e-6 对 mm 级模型足够（曲面参数容差）。
_PROP_ORDER = 1
_PROP_RESOLUTION = 1e-6


@dataclass(frozen=True)
class FacePoint:
    """B-Rep 面上一点的真值。``pos_mm``＝模型坐标系真实 3D 点（mm）；``normal``＝单位真法向；
    ``source_face``＝该点所属 B-Rep 面 id（``face_index`` 的键），供 ``Waypoint`` 记录来源面。

    ⚠️ 不命名为 ``Point``——``core.kinematics.Point`` 是裸 ``(x,y,z)`` 元组别名，同名异义会重蹈
    ``Frame``／``CoordFrame`` 覆辙（见模块 docstring）。
    """

    pos_mm: tuple[float, float, float]
    normal: tuple[float, float, float]
    source_face: int


@dataclass
class Waypoint:
    """示教点位（T06 数据模型，右栏列表与视口标号牌共用；T07 ``gen_path`` 的输入）。

    ``id`` 稳定不重排（删除点位后序号不回收，02 §2 步骤②）；``name`` 默认 P1／P2…、可手改；
    ``pos_mm``／``normal`` 取自 ``FacePoint``（**真值唯一在 core**，前端不存）；``source_face``＝来源
    B-Rep 面 id。GUI-free（无 PySide6 依赖），故落 core 而非 app（core 不得 import GUI，03 §3 铁律）。
    """

    id: int
    name: str
    pos_mm: tuple[float, float, float]
    normal: tuple[float, float, float]
    source_face: int


def face_point_from_tri(parts: list[MeshPart], mesh_id: int, face_id: int,
                        u: float, v: float) -> FacePoint:
    """由拾取三角形的重心坐标换算 B-Rep 面上的真实 3D 点与真法向。

    ``mesh_id``＝部件 id（选中 ``MeshPart``）；``face_id``＝**三角形序号**（见模块 docstring）；
    ``u``／``v``＝三角形第 2／第 3 顶点的重心权重（第 1 顶点权重＝``1-u-v``）。点由 core 权威顶点
    重建（前端只给权重，不存真值）；法向取自 B-Rep 面真值。
    """
    part, brep_fid, face = _resolve_face(parts, mesh_id, face_id)
    pos = _barycentric_point(part, face_id, u, v)
    return FacePoint(pos_mm=pos, normal=_surface_normal(face, pos), source_face=brep_fid)


def face_center(parts: list[MeshPart], mesh_id: int, face_id: int) -> FacePoint:
    """``face_id``（三角形序号）所属 B-Rep 面的**面心**（面积质心）与该处真法向。

    面心走 ``brepgprop.SurfaceProperties`` 的 B-Rep 面积质心（真值，与三角化疏密无关），非三角形顶点平均。
    """
    part, brep_fid, face = _resolve_face(parts, mesh_id, face_id)
    pos = _face_centroid(face)
    return FacePoint(pos_mm=pos, normal=_surface_normal(face, pos), source_face=brep_fid)


def _resolve_face(parts: list[MeshPart], mesh_id: int,
                  face_id: int) -> tuple[MeshPart, int, object]:
    """定位部件与活 B-Rep 面：``mesh_id``→``MeshPart``，``face_id``（三角形序号）→``face_map``→
    B-Rep 面 id→``face_index``→``TopoDS_Face``。任一缺位即抛 ``GeometryError``（人话原因）。"""
    part = next((p for p in parts if p.id == mesh_id), None)
    if part is None:
        raise GeometryError(f"mesh_id={mesh_id} 不在显示网格部件中（共 {len(parts)} 个部件）")
    n_tris = int(part.tris.shape[0])
    if not 0 <= face_id < n_tris:
        raise GeometryError(f"face_id（三角形序号）{face_id} 超出部件 {mesh_id} 范围 [0,{n_tris})")
    brep_fid = int(part.face_map[face_id])
    face = part.face_index.get(brep_fid)
    if face is None:
        raise GeometryError(
            f"face_index 缺 B-Rep 面 {brep_fid}：缓存全命中路径未重建 face_index（T05 整改-1 失效）")
    return part, brep_fid, face


def _barycentric_point(part: MeshPart, face_id: int, u: float, v: float) -> tuple[float, float, float]:
    """重心坐标→真实 3D 点（mm）：``P = (1-u-v)·V0 + u·V1 + v·V2``，顶点取 core 权威 ``MeshPart.vertices``。"""
    i0, i1, i2 = (int(x) for x in part.tris[face_id])
    v0 = part.vertices[i0].astype(np.float64)
    v1 = part.vertices[i1].astype(np.float64)
    v2 = part.vertices[i2].astype(np.float64)
    p = (1.0 - u - v) * v0 + u * v1 + v * v2
    return float(p[0]), float(p[1]), float(p[2])


def _face_centroid(face: object) -> tuple[float, float, float]:
    """B-Rep 面的面积质心（模型坐标系 mm）——``brepgprop.SurfaceProperties`` 真值，与三角化无关。"""
    props = GProp_GProps()
    brepgprop.SurfaceProperties(face, props)
    c = props.CentreOfMass()
    return c.X(), c.Y(), c.Z()


def _surface_normal(face: object, pos_mm: tuple[float, float, float]) -> tuple[float, float, float]:
    """B-Rep 面在 ``pos_mm`` 处的**真值单位法向**（⛔ 非三角形法向）。

    曲面与 ``pos_mm`` 同处模型坐标系（见模块 docstring），故直接投影：``ValueOfUV`` 求曲面参数 →
    ``GeomLProp_SLProps`` 求法向。返回参数化法向（与三角形绕向同侧，不按 orientation 翻转）。
    """
    surf = BRep_Tool.Surface(face)
    tol = BRep_Tool.Tolerance(face)
    uv = ShapeAnalysis_Surface(surf).ValueOfUV(gp_Pnt(*pos_mm), tol)
    props = GeomLProp_SLProps(surf, uv.X(), uv.Y(), _PROP_ORDER, _PROP_RESOLUTION)
    if not props.IsNormalDefined():
        raise GeometryError("B-Rep 面在该点法向未定义（退化面／奇异点）")
    n = props.Normal()
    return n.X(), n.Y(), n.Z()
