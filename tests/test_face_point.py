"""tests/test_face_point.py —— T06 core.geometry.face_point 取真值点／法向测试。

覆盖派单卡步骤6 与 ⑤ 完成标准增补、③ 收单必检：
  · 手算换算 3 组（斜置件＋无理数重心坐标，⛔ 禁用误差恒 0 的轴对齐整数框——附7 形态①）
  · 法向取自 B-Rep 面真值：轴对齐 box 六面＝±X/±Y/±Z；圆柱侧面＝水平径向
  · 圆柱侧面**真法向 ≠ 三角形法向**（夹角明显非 0，T05 同情形实测 2.318°）；平面端面＝0 作对照
    ——若两者恒等即说明取成了网格法向（③ 打回判据）
  · 缓存**全命中**路径下真法向与**冷路径逐面一致**（点积 ≈1）——T05 整改-1 的下游消费者判据
    （③ 第一条；只在冷路径测＝附7 形态③会在本单复现）
  · face_index 缺位／mesh_id 不存在／face_id 越界 → GeometryError（人话原因）

样件纪律（项目记忆 test-fixture-invariants）：CAD 全部用 tests.cad_samples 现场生成、内存装配
或落 tmp_path，**禁写死仓内绝对路径**；缓存经 autouse 夹具隔离到每测试私有 tmp 目录，既不污染
本机真实 cache_dir，又让冷／热路径断言确定。
"""

from __future__ import annotations

import importlib
import math

import numpy as np
import pytest

from core.geometry import Assembly, AssemblyNode, GeometryError, import_model, tessellate
from core.geometry.face_point import face_center, face_point_from_tri
from tests import cad_samples as cs

# 取真正的子模块对象（包根属性名 import_model/tessellate 已被 re-export 的**函数**遮蔽，
# 直接 `import core.geometry.tessellate as _ts` 会绑到函数、monkeypatch 静默失效——卡 ④ 陷阱）。
_im = importlib.import_module("core.geometry.import_model")
_ts = importlib.import_module("core.geometry.tessellate")


@pytest.fixture(autouse=True)
def _isolated_cache(tmp_path, monkeypatch):
    """把缓存根重定向到每测试私有 tmp 目录（不污染本机真实 cache_dir，冷热路径断言确定）。"""
    root = tmp_path / "_cache"
    (root / "manifest").mkdir(parents=True)
    (root / "mesh").mkdir(parents=True)
    monkeypatch.setattr(_im, "_CFG_CACHE", root)
    return root


def _mem(shape, key: str) -> Assembly:
    """把单个形状包成内存 Assembly（免落盘，直测三角化→取点路径）。"""
    node = AssemblyNode(node_id=1, name="件", is_assembly=False, shape=shape)
    return Assembly(source_path="mem.step", source_hash=key, ext=".step",
                    is_brep=True, tree=[node], stats={"parts": 1})


def _faces_of(part) -> dict[int, list[int]]:
    """B-Rep 面 id → 该面上三角形序号列表（按 face_map 归组）。"""
    out: dict[int, list[int]] = {}
    for ti in range(part.tris.shape[0]):
        out.setdefault(int(part.face_map[ti]), []).append(ti)
    return out


def _tri_normal(part, ti: int) -> np.ndarray:
    """三角形（网格）法向：按 tris 绕向 cross(V1-V0, V2-V0) 归一——⛔ 非 B-Rep 真法向。"""
    i0, i1, i2 = (int(x) for x in part.tris[ti])
    v0, v1, v2 = (part.vertices[i].astype(np.float64) for i in (i0, i1, i2))
    n = np.cross(v1 - v0, v2 - v0)
    return n / np.linalg.norm(n)


def _angle_deg(a, b) -> float:
    """两向量夹角（度），点积裁剪到 [-1,1] 防 arccos 越界。"""
    return math.degrees(math.acos(max(-1.0, min(1.0, float(np.dot(a, b))))))


# --------------------------------------------------------------------------- #
# ⑤-3／附7①：手算换算 3 组（斜置件＋无理数重心坐标，误差不得恒 0）
# --------------------------------------------------------------------------- #
def test_barycentric_matches_hand_computed_3groups() -> None:
    """重心坐标→真实 3D 点：与**独立手算**（仿射式 V0+u(V1-V0)+v(V2-V0)）逐组吻合。

    用斜置件（绕 Z 转 45°＋无理数平移）⇒ 顶点含无理数；手算走仿射式、face_point 走重心式
    ``(1-u-v)V0+uV1+vV2``，两式代数相等但浮点运算次序不同 ⇒ 残差为 ~1e-14 的**非零**小量
    （恒 0 即空跑，附7①）。另验：结果含无理坐标、区别于 V0、且 u/v 不可互换（重心坐标有序）。
    """
    shape, _off = cs.oblique_box()
    part = tessellate(_mem(shape, "oblique"), 0.5)[0]
    groups = [(3, math.sqrt(2.0) / 3.0, math.pi / 7.0),
              (5, 1.0 / math.e, 0.25),
              (8, math.sqrt(3.0) / 5.0, 2.0 / 7.0)]
    residuals: list[float] = []
    print("\n  ti | face | (u,v)            | actual(mm)                 | 手算仿射(mm)               | 残差")
    for ti, u, v in groups:
        i0, i1, i2 = (int(x) for x in part.tris[ti])
        v0, v1, v2 = (part.vertices[i].astype(np.float64) for i in (i0, i1, i2))
        actual = np.array(face_point_from_tri([part], part.id, ti, u, v).pos_mm)
        expected = v0 + u * (v1 - v0) + v * (v2 - v0)
        res = float(np.abs(actual - expected).max())
        residuals.append(res)
        print(f"  {ti:>2} | {int(part.face_map[ti]):>4} | ({u:.5f},{v:.5f}) | "
              f"({actual[0]:8.4f},{actual[1]:8.4f},{actual[2]:7.4f}) | "
              f"({expected[0]:8.4f},{expected[1]:8.4f},{expected[2]:7.4f}) | {res:.3e}")
        assert res < 1e-6, f"组 ti={ti} 重心换算残差 {res:.3e} 超限"
        assert any(abs(c - round(c)) > 1e-6 for c in actual), "斜置件坐标应含无理数（防空跑）"
        assert not np.allclose(actual, v0), "换算结果须区别于第 0 顶点（否则等于没换算）"
        assert not np.allclose(actual, v0 + v * (v1 - v0) + u * (v2 - v0)), "u/v 不可互换"
    assert max(residuals) > 0.0, "误差列恒 0＝空跑（附7 形态①）"


# --------------------------------------------------------------------------- #
# 步骤6：法向与 B-Rep 面法向一致（box 六面 ±轴；圆柱侧面 水平径向）
# --------------------------------------------------------------------------- #
def test_normal_matches_analytic_brep_truth() -> None:
    """真法向须等于解析 B-Rep 面法向：轴对齐 box 六面＝±X/±Y/±Z；圆柱侧面＝水平、单位、朝外径向。"""
    box_part = tessellate(_mem(cs.box(20.0, 12.0, 8.0), "box"), 0.5)[0]
    axes = sorted(tuple(round(abs(float(c)), 6) for c in
                        np.array(face_center([box_part], box_part.id, tis[0]).normal))
                  for tis in _faces_of(box_part).values())
    expect = sorted([(1.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0),
                     (0.0, 1.0, 0.0), (0.0, 0.0, 1.0), (0.0, 0.0, 1.0)])
    assert axes == expect, f"轴对齐 box 六面法向应为 ±X/±Y/±Z，实测 {axes}"

    cyl = tessellate(_mem(cs.cylinder(5.0, 15.0), "cyl"), 0.5)[0]
    side_checked = 0
    for tis in _faces_of(cyl).values():
        cen = face_center([cyl], cyl.id, tis[0])
        if abs(cen.normal[2]) >= 0.5:                 # 端面（法向近竖直）跳过
            continue
        fp = face_point_from_tri([cyl], cyl.id, tis[0], 1.0 / 3.0, 1.0 / 3.0)
        n = np.array(fp.normal)
        assert abs(float(np.linalg.norm(n)) - 1.0) < 1e-9, "真法向应为单位向量"
        assert abs(n[2]) < 1e-6, "圆柱侧面真法向应水平（径向，无 Z 分量）"
        c = np.array(fp.pos_mm)
        radial = np.array([c[0], c[1], 0.0])
        radial = radial / np.linalg.norm(radial)
        assert _angle_deg(n, radial) < 1.0, "侧面真法向应沿径向朝外（指向轴线外）"
        side_checked += 1
    assert side_checked >= 1, "圆柱须有侧面（曲面）可验"


# --------------------------------------------------------------------------- #
# ⑤-2／③：圆柱侧面 真法向 ≠ 三角形法向（明显非 0）；平面端面＝0 作对照
# --------------------------------------------------------------------------- #
def test_cylinder_side_true_normal_differs_from_triangle_normal() -> None:
    """打回判据：圆柱侧面真法向与该三角形法向夹角须**明显非 0**（弦高偏差，T05 实测 2.318°）。

    若两者恒等＝取成了网格法向（不是 B-Rep 真值）⇒ 打回；平面端面夹角≈0 作对照，证明
    侧面的非零夹角来自真实曲率而非数值噪声。另排除朝向翻转（夹角不应 ≈180°）。
    """
    part = tessellate(_mem(cs.cylinder(5.0, 15.0), "cyl"), 0.5)[0]
    side_angs: list[float] = []
    planar_angs: list[float] = []
    for tis in _faces_of(part).values():
        curved = abs(face_center([part], part.id, tis[0]).normal[2]) < 0.5
        for ti in tis:
            true_n = np.array(face_point_from_tri([part], part.id, ti, 1.0 / 3.0, 1.0 / 3.0).normal)
            a = _angle_deg(true_n, _tri_normal(part, ti))
            (side_angs if curved else planar_angs).append(a)
    side_max = max(side_angs)
    planar_max = max(planar_angs)
    print(f"\n  圆柱侧面（曲面）真法向 vs 三角形法向：max={side_max:.3f}°  (n={len(side_angs)})")
    print(f"  圆柱端面（平面）同口径对照：           max={planar_max:.6f}°  (n={len(planar_angs)})")
    assert side_angs and planar_angs, "圆柱须同时有侧面与端面"
    assert side_max > 0.5, f"侧面真法向须明显偏离三角形法向（实测 {side_max:.3f}°）；恒等＝取成网格法向→打回"
    assert side_max < 90.0, f"侧面夹角应是弦高偏差(≈2.3°)而非朝向翻转(≈180°)，实测 {side_max:.3f}°"
    assert planar_max < 1e-6, f"平面端面真法向应与三角形法向一致（对照），实测 {planar_max:.6f}°"


# --------------------------------------------------------------------------- #
# ⑤-1／③：缓存全命中路径真法向 == 冷路径逐面一致（点积 ≈1）
# --------------------------------------------------------------------------- #
def test_cache_full_hit_normals_match_cold_path(tmp_path, monkeypatch) -> None:
    """二次导入（显示网格＋.brep 双命中）后取真法向，须与首次（冷路径）**逐面一致**（点积≈1）。

    为证明命中路径走的是 ``.brep`` 重建而非「重新解析源文件」回退，把 tessellate 的 ``_parse``
    改成抛错——命中路径一旦回退即测试失败。这是 T05 整改-1 的下游消费者判据（③ 第一条）。
    """
    path = cs.assembly_step(tmp_path / "asm.step")
    cold = tessellate(import_model(str(path)), 0.5)
    assert all(p.face_index for p in cold), "冷路径各部件应有 face_index"

    def _boom(*_a, **_k):
        raise AssertionError("命中路径不得回退重新解析源文件（应由 .brep 缓存重建 face_index）")

    monkeypatch.setattr(_ts, "_parse", _boom)
    hot = tessellate(import_model(str(path)), 0.5)
    assert all(p.face_index for p in hot), "全命中路径 face_index 不得为空（T05 整改-1）"

    checked = 0
    min_dot = 1.0
    for pc, ph in zip(cold, hot):
        assert pc.id == ph.id, "冷热路径部件 id 应一致"
        for fid in sorted(set(int(x) for x in pc.face_map)):
            tic = next(ti for ti in range(pc.tris.shape[0]) if int(pc.face_map[ti]) == fid)
            tih = next(ti for ti in range(ph.tris.shape[0]) if int(ph.face_map[ti]) == fid)
            nc = np.array(face_center([pc], pc.id, tic).normal)
            nh = np.array(face_center([ph], ph.id, tih).normal)
            dot = float(np.dot(nc, nh))
            min_dot = min(min_dot, dot)
            assert dot > 1.0 - 1e-9, f"面 {fid} 面心真法向 冷热点积 {dot:.12f} 偏离 1"
            fc = face_point_from_tri([pc], pc.id, tic, 1.0 / 3.0, 1.0 / 3.0)
            fh = face_point_from_tri([ph], ph.id, tih, 1.0 / 3.0, 1.0 / 3.0)
            assert np.allclose(fc.pos_mm, fh.pos_mm, atol=1e-6), f"面 {fid} 取点位置冷热不一致"
            assert _angle_deg(np.array(fc.normal), np.array(fh.normal)) < 1e-6, \
                f"面 {fid} 三角形取点真法向冷热不一致"
            checked += 1
    print(f"\n  逐面核验 {checked} 个 B-Rep 面：冷热真法向最小点积 = {min_dot:.12f}")
    assert checked >= 3, "装配样件应有多面可逐面核验"
    assert min_dot > 1.0 - 1e-9, "全命中路径真法向须与冷路径逐面一致"


# --------------------------------------------------------------------------- #
# 人话错误：face_index 缺位 / mesh_id 不存在 / face_id 越界
# --------------------------------------------------------------------------- #
def test_missing_face_index_raises_human_error() -> None:
    """face_index 空（模拟全命中路径未重建）→ GeometryError 直指 T05 整改-1，不静默给错法向。"""
    part = tessellate(_mem(cs.box(20.0, 12.0, 8.0), "box"), 0.5)[0]
    part.face_index = {}
    with pytest.raises(GeometryError, match="face_index"):
        face_point_from_tri([part], part.id, 0, 1.0 / 3.0, 1.0 / 3.0)


def test_resolve_face_guards_bad_ids() -> None:
    """mesh_id 不在部件中 / face_id（三角形序号）越界 → GeometryError（人话原因）。"""
    part = tessellate(_mem(cs.box(20.0, 12.0, 8.0), "box"), 0.5)[0]
    with pytest.raises(GeometryError, match="不在显示网格部件中"):
        face_point_from_tri([part], 999, 0, 0.0, 0.0)
    with pytest.raises(GeometryError, match="超出部件"):
        face_point_from_tri([part], part.id, 99999, 0.0, 0.0)
