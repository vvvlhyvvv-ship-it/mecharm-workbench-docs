"""tests/test_geometry.py —— T05 core.geometry 导入/装配树/三角化/face_map/缓存测试。

覆盖派单卡步骤5 全部要点：≥2 级装配树、STL is_brep=False、缺失/损坏引用不崩、缓存键
命中与失效、中文目录+中文名、不支持类型（**针对已存在的文件**，避免被“文件不存在”先拦）、
face_map 抽样核、二次导入计时、deflection 校验、encode 不下发 face_map/face_index。

样件纪律（项目记忆 test-fixture-invariants）：CAD 全部用 tests.cad_samples 现场生成到
tmp_path，**禁写死仓内绝对路径**；缓存经 autouse 夹具隔离到每测试私有 tmp 目录，既不污染
本机真实 cache_dir，又让命中/失效断言确定。
"""

from __future__ import annotations

import base64
import importlib
import pathlib

import numpy as np
import pytest

from core.geometry import (SUPPORTED_EXT, Assembly, AssemblyNode, GeometryError,
                           encode_mesh_parts, import_model, tessellate)
from tests import cad_samples as cs

# 取真正的子模块对象（包根的属性名 import_model 已被 re-export 的**函数**遮蔽）。
_im = importlib.import_module("core.geometry.import_model")
_ts = importlib.import_module("core.geometry.tessellate")

# 结构合法但无任何几何的 STEP——等价“装配引用的零件缺失/空”，用于验证读取侧优雅报错而非崩溃。
_EMPTY_STEP = (
    "ISO-10303-21;\nHEADER;\nFILE_DESCRIPTION((''),'2;1');\n"
    "FILE_NAME('empty.step','2026-09-16',(''),(''),'','','');\n"
    "FILE_SCHEMA(('AUTOMOTIVE_DESIGN'));\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n"
)


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """把缓存根重定向到每测试私有 tmp 目录（_cache_root 见 Path 即直接返回，需自备子目录）。"""
    root = tmp_path / "_cache"
    (root / "manifest").mkdir(parents=True)
    (root / "mesh").mkdir(parents=True)
    monkeypatch.setattr(_im, "_CFG_CACHE", root)
    return root


def _walk(nodes, depth=1):
    """产出 (node, depth)，用于统计装配层级与叶子零件。"""
    for n in nodes:
        yield n, depth
        yield from _walk(n.children, depth + 1)


# --------------------------------------------------------------------------- #
# 装配树 / is_brep
# --------------------------------------------------------------------------- #
def test_assembly_tree_has_two_levels(tmp_path) -> None:
    """≥2 级装配：根装配 → 子装配 → 零件叶子；命名走 零件_N / 子装配_N 口径。"""
    asm = import_model(str(cs.assembly_step(tmp_path / "asm.step")))
    assert asm.is_brep is True
    nodes = list(_walk(asm.tree))
    assemblies = [n for n, _ in nodes if n.is_assembly]
    leaves = [n for n, _ in nodes if not n.is_assembly]
    assert len(leaves) == asm.stats["parts"] == 3
    assert len(assemblies) >= 2, "至少两级装配（根 + 子装配）"
    assert max(d for _, d in nodes) >= 3, "树深≥3（根→子装配→零件）"
    assert any(n.name.startswith("零件_") for n in leaves)
    assert any(n.name.startswith("子装配_") for n in assemblies)


def test_simple_step_is_brep(tmp_path) -> None:
    """单实体 STEP：is_brep=True、1 个零件、sha256 内容哈希、扩展名归一。"""
    asm = import_model(str(cs.simple_step(tmp_path / "s.step")))
    assert asm.is_brep is True
    assert asm.stats["parts"] == 1
    assert asm.ext == ".step"
    assert len(asm.source_hash) == 64  # sha256 hex


def test_stl_is_mesh_not_brep(tmp_path) -> None:
    """STL 是面片模型：is_brep=False、整体作单一部件（不按三角面裂开）。"""
    asm = import_model(str(cs.write_stl(tmp_path / "b.stl")))
    assert asm.is_brep is False
    assert asm.stats["parts"] == 1
    parts = tessellate(asm, 0.5)
    assert len(parts) == 1 and parts[0].tris.shape[0] >= 1


def test_chinese_path_and_name(tmp_path) -> None:
    """中文目录+中文名 STEP 可导入（直读或短路径副本兜底），source_path 保留中文名。"""
    target = cs.chinese_step(tmp_path / "ascii.step", tmp_path / "中文目录" / "机架装配.step")
    asm = import_model(str(target))
    assert asm.is_brep is True and asm.stats["parts"] == 1
    assert "机架装配" in pathlib.Path(asm.source_path).name
    assert len(tessellate(asm, 0.5)) >= 1


# --------------------------------------------------------------------------- #
# 失败路径（不崩、优雅报错）
# --------------------------------------------------------------------------- #
def test_unsupported_ext_on_existing_file(tmp_path) -> None:
    """不支持类型必须针对**已存在**文件触发（否则会被“文件不存在”先拦，测不到类型分支）。"""
    bad = tmp_path / "model.xyz"
    bad.write_text("not a model", encoding="utf-8")
    assert bad.is_file() and bad.suffix.lower() not in SUPPORTED_EXT
    with pytest.raises(GeometryError, match="不支持的文件类型"):
        import_model(str(bad))


def test_missing_file_raises(tmp_path) -> None:
    with pytest.raises(GeometryError, match="不存在"):
        import_model(str(tmp_path / "nope.step"))


def test_empty_step_raises_not_crash(tmp_path) -> None:
    """结构合法但无几何的 STEP（等价缺失引用）→ GeometryError，不允许原生崩溃。"""
    empty = tmp_path / "empty.step"
    empty.write_text(_EMPTY_STEP, encoding="utf-8")
    with pytest.raises(GeometryError):
        import_model(str(empty))


# --------------------------------------------------------------------------- #
# 缓存：命中 / 失效
# --------------------------------------------------------------------------- #
def test_cache_hit_on_second_import(tmp_path) -> None:
    """二次导入命中清单缓存：cache=hit、更快、装配树与首次一致。"""
    path = cs.simple_step(tmp_path / "h.step")
    a1 = import_model(str(path))
    a2 = import_model(str(path))
    assert a1.stats["cache"] == "miss"
    assert a2.stats["cache"] == "hit"
    assert a2.stats["load_ms"] < a1.stats["load_ms"], "命中清单应显著快于首次解析"
    assert a2.tree_payload() == a1.tree_payload()


def test_cache_invalidated_by_content_change(tmp_path) -> None:
    """同名文件改内容 → 内容哈希变 → 旧缓存键失效（不吃陈旧命中）。"""
    path = tmp_path / "m.step"
    cs.simple_step(path)                       # box
    a1 = import_model(str(path))
    cs.write_step(cs.cylinder(6.0, 20.0), path)  # 覆盖为不同几何
    a2 = import_model(str(path))
    assert a1.source_hash != a2.source_hash
    assert a1.stats["cache"] == "miss" and a2.stats["cache"] == "miss"


def test_brep_cache_written_and_hit_path_rebuilds_face_index(tmp_path, monkeypatch,
                                                             _isolated_cache) -> None:
    """整改-1：显示网格**全命中**路径仍须给出非空 face_index（T06 反查真值法向的唯一依据）。

    首导入三角化同时落 mesh.npz（显示）与 ``.brep``（几何真身，键＝源哈希、仓外）；二次导入命中
    清单（形状留空）＋命中 mesh.npz（face_index 空），必须由 ``.brep`` 读回活形状重建 face_index。
    为证明走的是 ``.brep`` 而非「重新解析源文件」回退，把 tessellate 的 ``_parse`` 改成抛错——
    命中路径一旦回退到 _parse 即测试失败（旧 criterion 6 抓不到「秒开路径挖空 face_index」）。
    """
    path = cs.assembly_step(tmp_path / "asm.step")
    first = tessellate(import_model(str(path)), 0.5)
    assert all(p.face_index for p in first), "首导入各部件应有 face_index"

    # .brep 几何真身缓存须落盘到仓外 cache_dir，且每个零件叶子一个文件
    brep_files = sorted((_isolated_cache / "brep").rglob("*.brep"))
    assert len(brep_files) == 3, "3 个零件叶子各落一个 .brep（双缓存之几何真身）"
    assert all(f.is_file() and f.stat().st_size > 0 for f in brep_files)

    # 禁掉源文件重新解析：命中路径若回退到 _parse 即崩，反证 face_index 来自 .brep 缓存
    def _boom(*_a, **_k):
        raise AssertionError("命中路径不得回退重新解析源文件（应由 .brep 缓存重建）")

    monkeypatch.setattr(_ts, "_parse", _boom)
    second = tessellate(import_model(str(path)), 0.5)
    assert second is not first
    assert all(p.face_index for p in second), "全命中路径 face_index 不得为空（整改-1 核心判据）"
    for a, b in zip(first, second):
        assert set(b.face_index) == {int(x) for x in b.face_map}, "重建的 face_index 须覆盖 face_map 全部 face_id"
        assert set(a.face_index) == set(b.face_index), "重建结果与首次逐 face_id 一致（面序随 .brep 保留）"


# --------------------------------------------------------------------------- #
# 三角化 / face_map / 序列化
# --------------------------------------------------------------------------- #
def test_tessellate_box_face_map(tmp_path) -> None:
    """立方体三角化：顶点/索引/face_map 形状与 dtype 正确，face_map 全落在 face_index。"""
    asm = import_model(str(cs.simple_step(tmp_path / "f.step")))
    p = tessellate(asm, 0.5)[0]
    assert p.vertices.shape == (24, 3) and p.vertices.dtype == np.float32
    assert p.tris.shape == (12, 3) and p.tris.dtype == np.uint32
    assert p.face_map.shape == (12,) and p.face_map.dtype == np.int32
    fids = sorted({int(x) for x in p.face_map})
    assert len(fids) >= 3, "立方体至少 3 个不同 B-Rep 面（实为 6）"
    assert set(fids) == set(p.face_index), "face_map 的每个 face_id 都能在 face_index 反查到"
    for ti in (0, 6, 11):                       # 抽样三个三角形（首/中/尾）
        assert int(p.face_map[ti]) in p.face_index
    assert int(p.tris.min()) >= 0 and int(p.tris.max()) < p.vertices.shape[0]


def test_face_ids_globally_unique_across_parts(tmp_path) -> None:
    """face_id 全局唯一递增、跨部件不冲突（03 §3：T06 反查真值法向的唯一依据）。"""
    asm = import_model(str(cs.assembly_step(tmp_path / "g.step")))
    parts = tessellate(asm, 0.5)
    assert len(parts) == 3
    id_sets = [set(p.face_index) for p in parts]
    assert all(id_sets), "每个部件都应有面索引"
    union = set().union(*id_sets)
    assert len(union) == sum(len(s) for s in id_sets), "face_id 跨部件不得重复"


def _mem_assembly(shape, key: str):
    """把单个形状包成内存 Assembly（免落盘，直测三角化路径）。"""
    node = AssemblyNode(node_id=1, name="件", is_assembly=False, shape=shape)
    return Assembly(source_path="mem.step", source_hash=key, ext=".step", is_brep=True,
                    tree=[node], stats={"parts": 1})


def test_tessellate_applies_part_location_transform() -> None:
    """斜置件三角化后顶点须带上 location 变换——防“误差恒 0 的空跑”。

    轴对齐、原点起的 box 会让 ``p.Transform(loc)`` 退化成恒等变换，变换路径有 bug 也测不出。
    这里用绕 Z 转 45°＋无理数平移的斜置件：XY 投影变成 (20+12)/√2≈22.627（无理数，恒等给不出），
    Z 向不受绕 Z 旋转影响仍为 8，平移落在 5e/3π 上；并与未变换 box 对照，自证非空跑。
    """
    shape, off = cs.oblique_box()
    v = tessellate(_mem_assembly(shape, "oblique"), 0.5)[0].vertices
    ext = v.max(0) - v.min(0)
    assert ext[0] == pytest.approx(22.627, abs=1e-2), "绕 Z 转 45° 后 X 投影应为无理数 ≈22.627"
    assert ext[1] == pytest.approx(22.627, abs=1e-2), "绕 Z 转 45° 后 Y 投影应为无理数 ≈22.627"
    assert ext[2] == pytest.approx(8.0, abs=1e-3), "绕 Z 旋转不改变 Z 向尺寸"
    assert float(v.min(0)[2]) == pytest.approx(off[2], abs=1e-3), "Z 平移（5e）须生效"
    assert float(v.min(0)[1]) == pytest.approx(off[1], abs=1e-3), "Y 平移（3π）须生效"
    plain = tessellate(_mem_assembly(cs.box(20.0, 12.0, 8.0), "plain"), 0.5)[0].vertices
    assert not np.allclose(plain, v), "斜置件顶点必须区别于未变换 box，否则变换路径没被测到"


@pytest.mark.parametrize("bad", [0.0, -1.0])
def test_tessellate_rejects_nonpositive_deflection(tmp_path, bad) -> None:
    asm = import_model(str(cs.simple_step(tmp_path / "d.step")))
    with pytest.raises(GeometryError):
        tessellate(asm, bad)


def test_encode_excludes_face_map_and_index(tmp_path) -> None:
    """桥载荷只下发顶点/索引；face_map/face_index 留 core（禁前端做几何判定），base64 无损。"""
    asm = import_model(str(cs.simple_step(tmp_path / "e.step")))
    parts = tessellate(asm, 0.5)
    payload = encode_mesh_parts(parts)
    assert len(payload) == len(parts)
    p0, m0 = payload[0], parts[0]
    assert set(p0) == {"id", "name", "n_vertices", "n_tris", "vertices", "tris"}
    assert "face_map" not in p0 and "face_index" not in p0
    assert p0["n_vertices"] == m0.vertices.shape[0] and p0["n_tris"] == m0.tris.shape[0]
    v = np.frombuffer(base64.b64decode(p0["vertices"]), dtype="<f4")
    t = np.frombuffer(base64.b64decode(p0["tris"]), dtype="<u4")
    assert v.size == m0.vertices.size and t.size == m0.tris.size
    assert np.array_equal(v.reshape(-1, 3), m0.vertices), "float32 顶点应无损往返"
    assert np.array_equal(t.reshape(-1, 3), m0.tris), "uint32 索引应无损往返"
