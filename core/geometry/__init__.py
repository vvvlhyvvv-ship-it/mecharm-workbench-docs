"""core.geometry —— 模型导入、装配树还原、三角化与显示网格（T05）。

公开接口（03 架构 §3，调用形态与拆包前一字不变）：
  ``import_model(path) -> Assembly``                 STEP/IGES/STL 导入，还原装配树，判 is_brep
  ``tessellate(assembly, deflection) -> [MeshPart]``  按部件三角化，附 ``face_map``
  ``encode_mesh_parts(parts) -> [dict]``             序列化为桥 ``mesh.load`` 载荷（base64）

单位与坐标系（与 config.schema 一致）：长度 mm，右手系、Z 竖直向上；顶点为模型自身坐标系下的
mm 值；三角化弦高容差 ``deflection`` 单位 mm（来自 machine.yaml ``limits.tessellate_deflection_mm``，
禁在本包散写字面量）。

本包是**拆包形态**：原单文件 ``core/geometry.py`` 实测 511 行 > 04 §4.5-① 的 300 行上限，
按 T05 派单卡预授权结构（04 §4.5-⑦）拆为 ``import_model.py``（导入/装配树/is_brep/几何真身清单缓存）
与 ``tessellate.py``（三角化/face_map/显示网格缓存/序列化）。本文件**只做 re-export 与 __all__，
禁写业务逻辑**（§4.5-⑦ 硬要求 1）。

⚠️ 本机环境实测约束（pythonocc-core 7.9.0，2026-09-16；详见两子模块 docstring）：
  · XCAF（``STEPCAFControl_Reader`` / ``TDocStd_Document``）不可用 ⇒ 装配关系走
    ``STEPControl_Reader`` + compound 递归分解：**层级保住，原始 STEP 零件名无法保留**（自动命名）。
  · ``BRepTools`` 形状序列化 / OCAF ``SaveAs`` 不可用 ⇒ **几何真身无法落盘**；只实现「显示网格缓存」
    （manifest.json + mesh.npz，源文件哈希为键，落 ``paths.cache_dir`` 仓外）。``face_index``
    （face_id→活 TopoDS_Face）在解析路径于内存构建，供 T06/T08 当次会话取真值法向。
"""

from core.geometry.import_model import (SUPPORTED_EXT, Assembly, AssemblyNode, GeometryError,
                                        import_model)
from core.geometry.tessellate import MeshPart, encode_mesh_parts, tessellate

__all__ = [
    "import_model", "tessellate", "encode_mesh_parts",
    "Assembly", "AssemblyNode", "MeshPart", "GeometryError", "SUPPORTED_EXT",
]
