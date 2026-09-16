"""tests/test_public_api_geometry.py —— 03 §3 core.geometry 公开接口冻结测试（T05）。

断言派单卡 §3 列出的公开符号都能从**包根** ``core.geometry`` 直接导入（拆包后调用形态与
拆包前一字不变），且 ``__all__`` 与实际可导入符号一致、私有子模块名不外泄。文件名带
``geometry`` 后缀，避免与 T04 的 ``test_public_api.py`` 撞名（派单卡 §4.5-⑦ 要求）。
"""

from __future__ import annotations

import core.geometry as geo

# 03 §3 公开符号清单（与包 __init__.__all__ 对应）。
PUBLIC = [
    "import_model", "tessellate", "encode_mesh_parts",
    "Assembly", "AssemblyNode", "MeshPart", "GeometryError", "SUPPORTED_EXT",
]


def test_all_public_symbols_importable_from_package_root() -> None:
    for name in PUBLIC:
        assert hasattr(geo, name), f"core.geometry 缺少公开符号 {name}"


def test_all_matches_public_symbols() -> None:
    assert sorted(geo.__all__) == sorted(PUBLIC)


def test_callables_and_types() -> None:
    assert callable(geo.import_model)
    assert callable(geo.tessellate)
    assert callable(geo.encode_mesh_parts)
    assert isinstance(geo.GeometryError, type) and issubclass(geo.GeometryError, Exception)
    assert isinstance(geo.SUPPORTED_EXT, tuple)
    for ext in (".step", ".stp", ".iges", ".igs", ".stl"):
        assert ext in geo.SUPPORTED_EXT


def test_submodules_still_directly_importable() -> None:
    """拆包后子模块路径仍可直接导入（调用方两种写法都不破坏）。"""
    from core.geometry.import_model import import_model as im
    from core.geometry.tessellate import tessellate as ts
    assert callable(im) and callable(ts)


def test_private_names_not_in_all() -> None:
    """__init__ 只 re-export，不应把私有实现名塞进 __all__。"""
    for priv in ("_parse", "_cache_root", "_CFG_CACHE", "_build_tree"):
        assert priv not in geo.__all__
