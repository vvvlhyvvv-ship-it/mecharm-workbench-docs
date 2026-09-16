"""tests/cad_samples.py —— T05 几何测试的 CAD 样件工厂（pythonocc 现场生成，落 tmp_path）。

纪律（项目记忆 test-fixture-invariants）：**禁写死仓内绝对路径**——样件一律由调用方传入
tmp_path 目标路径，本模块只负责用 OCC 现造 box/cylinder 并写盘，绝不引用仓内既有模型。
所造几何仅为本厂自造基本体，不含任何甲方名称或工件尺寸（evidence 红线同理）。

中文路径样件经 ASCII 短路径写盘后 copyfile 到中文目标：规避 STEP **写**器对非 ASCII
路径的编码问题，同时仍能检验 import_model **读**侧的中文路径兜底（短路径副本重试）。
"""

from __future__ import annotations

import math
import pathlib
import shutil

from OCC.Core.BRep import BRep_Builder
from OCC.Core.BRepMesh import BRepMesh_IncrementalMesh
from OCC.Core.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCC.Core.IFSelect import IFSelect_RetDone
from OCC.Core.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCC.Core.StlAPI import StlAPI_Writer
from OCC.Core.TopLoc import TopLoc_Location
from OCC.Core.TopoDS import TopoDS_Compound
from OCC.Core.gp import gp_Ax1, gp_Dir, gp_Pnt, gp_Trsf, gp_Vec


def box(dx: float = 20.0, dy: float = 12.0, dz: float = 8.0):
    """一个长方体实体（mm），一角在原点。"""
    return BRepPrimAPI_MakeBox(gp_Pnt(0.0, 0.0, 0.0), dx, dy, dz).Shape()


def cylinder(radius: float = 5.0, height: float = 15.0):
    """一个圆柱实体（mm）。BRepPrimAPI_MakeCylinder 取 (R, H) 形式，非 gp_Pnt。"""
    return BRepPrimAPI_MakeCylinder(radius, height).Shape()


def oblique_box(dx: float = 20.0, dy: float = 12.0, dz: float = 8.0, deg: float = 45.0,
                offset=None):
    """斜置件：绕 Z 转 ``deg``° 再按无理数 ``offset`` 平移，返回 (形状, 实际偏移)。

    用 ``Moved()``（合成 TopLoc_Location）而非把变换烘焙进几何——三角化节点仍在局部坐标、
    变换留在 location 上，正好考 tessellate 的 ``p.Transform(loc)`` 路径。偏移默认取 √2/π/e
    的倍数，结果坐标含无理数：若变换路径退化成恒等（轴对齐原点 box 的通病），断言必挂。
    """
    off = tuple(offset) if offset is not None else (
        10.0 * math.sqrt(2.0), 3.0 * math.pi, 5.0 * math.e)
    rot = gp_Trsf()
    rot.SetRotation(gp_Ax1(gp_Pnt(0.0, 0.0, 0.0), gp_Dir(0.0, 0.0, 1.0)), math.radians(deg))
    tr = gp_Trsf()
    tr.SetTranslation(gp_Vec(*off))
    return box(dx, dy, dz).Moved(TopLoc_Location(tr.Multiplied(rot))), off


def compound(shapes: list) -> TopoDS_Compound:
    """把若干形状装进一个 compound（装配语义的最小载体）。"""
    comp = TopoDS_Compound()
    builder = BRep_Builder()
    builder.MakeCompound(comp)
    for shape in shapes:
        builder.Add(comp, shape)
    return comp


def write_step(shape, path) -> pathlib.Path:
    """把形状写成 STEP（AsIs 保结构）。返回落盘路径；失败抛 RuntimeError。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    if writer.Write(str(path)) != IFSelect_RetDone:
        raise RuntimeError(f"STEP 写盘失败：{path}")
    return path


def write_stl(path, dx: float = 20.0, dy: float = 12.0, dz: float = 8.0) -> pathlib.Path:
    """写一个三角化后的长方体 STL（面片模型）。返回落盘路径。"""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    shape = box(dx, dy, dz)
    BRepMesh_IncrementalMesh(shape, 0.5, False, 0.5, False)
    StlAPI_Writer().Write(shape, str(path))
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(f"STL 写盘失败：{path}")
    return path


def simple_step(path) -> pathlib.Path:
    """单实体 STEP（一个 box）。"""
    return write_step(box(), path)


def assembly_step(path) -> pathlib.Path:
    """≥2 级装配 STEP：顶层 compound → [子装配(box+cylinder), box2]。

    预期 import_model 还原为：装配根 → 子装配（2 叶子零件）＋ 1 叶子零件，共 3 个零件。
    """
    sub = compound([box(20.0, 12.0, 8.0), cylinder(5.0, 15.0)])
    top = compound([sub, box(10.0, 10.0, 10.0)])
    return write_step(top, path)


def chinese_step(ascii_tmp, target) -> pathlib.Path:
    """生成一个中文目录+中文名的 STEP：先写 ASCII 短路径，再 copyfile 到中文目标。"""
    written = simple_step(ascii_tmp)
    target = pathlib.Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(written, target)
    return target
