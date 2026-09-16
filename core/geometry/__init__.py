"""core.geometry —— 模型导入、装配树还原、三角化与显示网格（T05）。

公开接口（03 架构 §3，调用形态与拆包前一字不变）：
  ``import_model(path) -> Assembly``                 STEP/IGES/STL 导入，还原装配树，判 is_brep
  ``tessellate(assembly, deflection) -> [MeshPart]``  按部件三角化，附 ``face_map``
  ``encode_mesh_parts(parts) -> [dict]``             序列化为桥 ``mesh.load`` 载荷（base64）

单位与坐标系（与 config.schema 一致）：长度 mm，右手系、Z 竖直向上；顶点为模型自身坐标系下的
mm 值；三角化弦高容差 ``deflection`` 单位 mm（来自 machine.yaml ``limits.tessellate_deflection_mm``，
禁在本包散写字面量）。

本包是**拆包形态**：原单文件 ``core/geometry.py`` 实测 511 行 > 04 §4.5-① 的 300 行上限，
按 T05 派单卡预授权结构（04 §4.5-⑦）拆为 ``import_model.py``（导入/装配树/is_brep/装配树清单缓存）、
``tessellate.py``（三角化/face_map/显示网格缓存/序列化）与 ``brep_cache.py``（几何真身 ``.brep`` 缓存
与命中路径 face_index 重建）。本文件**只做 re-export 与 __all__，禁写业务逻辑**（§4.5-⑦ 硬要求 1）。

⚠️ 本机环境实测约束（pythonocc-core **7.9.3**，2026-09-16；详见各子模块 docstring）：
  · XCAF **可用**（``STEPCAFControl_Reader``／``XCAFDoc_ShapeTool`` 等模块均能 import，遍历 API 为
    ``GetComponents``／``GetSubShapes``／``IsAssembly``，无 ``GetChildren``／``GetUserName``）。本包仍走
    ``STEPControl_Reader`` + compound 递归分解，真实原因有二：① ``TDocStd_Document(TCollection_ExtendedString(...))``
    这一构造重载在本机退出码 127（须改传 plain ``str``）；② **原始 STEP 零件名读不出**——``TDataStd_Name``
    只有 ``DownCast/Dump/GetID/Set/SetID``、无 ``Get``/``Find``，故零件名无法保留，自动命名兜底（层级仍保住）。
  · 几何真身**能落盘**：走 ``.brep``（``breptools.Write`` / ``breptools.Read(shape, path, BRep_Builder())``
    本机实测可往返、面序与三角化均保留，见 ``brep_cache.py``）。OCAF ``SaveAs`` 确不可用（``TDocStd_Document``
    无 ``Save*``，仅 ``GetSavedTime/IsSaved/SetSaved/SetSavedTime``），故不用 OCAF 落盘。双缓存（manifest.json
    + mesh.npz + ``.brep``，源文件哈希为键）落 ``paths.cache_dir`` 仓外；``face_index``（face_id→活 TopoDS_Face）
    解析路径于内存构建、命中路径由 ``.brep`` 重建，供 T06/T08 取真值法向。
  · ⚠️ OCC 符号是小写模块级函数（``breptools``/``topods``）；CamelCase 类名（``BRepTools``/``TopoDS``）在本机
    build **不存在**。``OCC.__init__.VERSION`` 硬写 7.9.0 是已知陷阱，⛔ 不得据此写版本号（环境注册为 7.9.3）。
"""

from core.geometry.import_model import (SUPPORTED_EXT, Assembly, AssemblyNode, GeometryError,
                                        import_model)
from core.geometry.tessellate import MeshPart, encode_mesh_parts, tessellate

__all__ = [
    "import_model", "tessellate", "encode_mesh_parts",
    "Assembly", "AssemblyNode", "MeshPart", "GeometryError", "SUPPORTED_EXT",
]
