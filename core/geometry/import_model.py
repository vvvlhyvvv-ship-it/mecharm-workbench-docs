"""core.geometry.import_model —— STEP/IGES/STL 导入、装配树还原、is_brep 判定、几何清单缓存。

装配关系走 ``STEPControl_Reader`` / ``IGESControl_Reader`` + ``TopoDS`` compound 递归分解（XCAF 本身**可用**，
但 ``TDocStd_Document(TCollection_ExtendedString)`` 构造重载本机退出码 127、``TDataStd_Name`` 无 ``Get``/``Find``
读不出零件名，故不走 XCAF；详见包 ``__init__``）：层级保住、零件名自动命名。STL 走网格分支 is_brep=False。
坐标单位 mm、模型自身坐标系。

缓存：``_cache_root`` 解析 machine.yaml ``paths.cache_dir``（仓外），不可用即降级为不缓存并告警，
**绝不回落仓内**（缓存内是甲方模型几何，远端为公开仓，04 §7.1-10）。``import_model`` 命中
manifest 清单即免解析（二次导入秒开）。
"""

from __future__ import annotations

import hashlib
import json
import logging
import pathlib
import shutil
import tempfile
import time
from dataclasses import dataclass, field

from OCC.Core.IGESControl import IGESControl_Reader
from OCC.Core.STEPControl import STEPControl_Reader
from OCC.Core.StlAPI import StlAPI_Reader
from OCC.Core.TopAbs import TopAbs_COMPSOLID, TopAbs_COMPOUND
from OCC.Core.TopoDS import TopoDS_Iterator, TopoDS_Shape

log = logging.getLogger(__name__)

SUPPORTED_EXT = (".step", ".stp", ".iges", ".igs", ".stl")
_MESH_EXT = (".stl",)
_STEP_EXT = (".step", ".stp")
_MANIFEST_SCHEMA = 1


class GeometryError(Exception):
    """导入／三角化失败：文件缺失、类型不支持、读取无实体、缓存损坏等。"""


@dataclass
class AssemblyNode:
    """装配树节点。``is_assembly`` 为真＝子装配（children 非空、shape 为 None）；
    为假＝零件叶子（shape 持有 TopoDS_Shape；缓存命中重建时为 None，按需重新附着）。"""

    node_id: int
    name: str
    is_assembly: bool
    children: list["AssemblyNode"] = field(default_factory=list)
    shape: object | None = None

    def to_dict(self) -> dict:
        """转为可 JSON 序列化／可推给装配树控件的嵌套字典（不含 OCC 形状）。"""
        return {
            "id": self.node_id,
            "name": self.name,
            "is_assembly": self.is_assembly,
            "children": [c.to_dict() for c in self.children],
        }

    @classmethod
    def from_dict(cls, d: dict) -> "AssemblyNode":
        """``to_dict`` 的逆操作（shape 留空，由 tessellate 按需 _parse 重新附着）。"""
        return cls(
            node_id=int(d["id"]), name=str(d["name"]), is_assembly=bool(d["is_assembly"]),
            children=[cls.from_dict(c) for c in d.get("children", [])], shape=None,
        )


@dataclass
class Assembly:
    """导入结果。``tree`` 为根节点列表；``is_brep`` 区分实体模型（True，可拾取/算碰撞）与
    面片模型（False）；``stats`` 含 parts（零件数）/tris（三角面数，tessellate 回填）/load_ms。"""

    source_path: str
    source_hash: str
    ext: str
    is_brep: bool
    tree: list[AssemblyNode]
    stats: dict = field(default_factory=dict)

    def iter_parts(self):
        """广度优先产出全部零件叶子（顺序与 _parse 一致，node_id 稳定）。"""
        stack = list(self.tree)
        while stack:
            node = stack.pop(0)
            if node.is_assembly:
                stack = node.children + stack
            else:
                yield node

    def tree_payload(self) -> list[dict]:
        """装配树的 JSON 形态，供左栏 Qt Tree 与桥消息使用。"""
        return [n.to_dict() for n in self.tree]


# --------------------------------------------------------------------------- #
# 缓存原语（根目录 / 哈希 / 装配树清单）
# --------------------------------------------------------------------------- #
_CFG_CACHE: object = None  # None=未加载, False=不可用(禁缓存), Path=可用根目录


def _cache_root() -> pathlib.Path | None:
    """解析缓存根目录（仓外）。配置缺失／不可写 → None 并告警，**绝不回落仓内**。"""
    global _CFG_CACHE
    if _CFG_CACHE is False:
        return None
    if isinstance(_CFG_CACHE, pathlib.Path):
        return _CFG_CACHE
    try:
        from core.config import REPO_ROOT, load_machine

        cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
        root = pathlib.Path(cfg.paths.cache_dir).expanduser()
        (root / "manifest").mkdir(parents=True, exist_ok=True)
        (root / "mesh").mkdir(parents=True, exist_ok=True)
        probe = root / ".write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        _CFG_CACHE = root
        return root
    except Exception as exc:  # noqa: BLE001 - 任何失败都降级为不缓存
        log.warning("缓存目录不可用，降级为不缓存（绝不落仓内）：%s", exc)
        _CFG_CACHE = False
        return None


def _file_hash(path: pathlib.Path) -> str:
    """源文件内容的 sha256（分块读，避免大模型一次性入内存）。缓存键即此值。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _manifest_path(key: str) -> pathlib.Path | None:
    root = _cache_root()
    return None if root is None else root / "manifest" / f"{key}.json"


def _save_manifest(asm: Assembly) -> None:
    """写装配树清单（不含形状）。命中后二次导入免解析。失败仅告警、不影响主流程。"""
    path = _manifest_path(asm.source_hash)
    if path is None:
        return
    payload = {
        "schema": _MANIFEST_SCHEMA, "source_hash": asm.source_hash,
        "source_name": pathlib.Path(asm.source_path).name, "ext": asm.ext,
        "is_brep": asm.is_brep, "parts": asm.stats.get("parts", 0),
        "tree": [n.to_dict() for n in asm.tree],
    }
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        log.warning("写装配树清单失败（忽略）：%s", exc)


def _load_manifest(key: str) -> dict | None:
    """读装配树清单；哈希不符或损坏 → 视为未命中（None）。"""
    path = _manifest_path(key)
    if path is None or not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("装配树清单损坏，按未命中处理：%s", exc)
        return None
    if data.get("schema") != _MANIFEST_SCHEMA or data.get("source_hash") != key:
        return None
    return data


# --------------------------------------------------------------------------- #
# 导入主流程
# --------------------------------------------------------------------------- #
def import_model(path: str) -> Assembly:
    """导入 STEP/IGES/STL，还原装配树并判定 is_brep。

    返回 ``Assembly``：实体模型 is_brep=True，STL 面片模型 is_brep=False。坐标 mm、模型自身坐标系。
    命中缓存则免解析（load_ms 显著下降，stats['cache']='hit'）；缓存命中**不跳过** is_brep 与日志留痕。
    """
    src = pathlib.Path(path)
    if not src.is_file():
        raise GeometryError(f"模型文件不存在：{src}")
    ext = src.suffix.lower()
    if ext not in SUPPORTED_EXT:
        raise GeometryError(f"不支持的文件类型：{ext or '(无扩展名)'}（支持 STEP/IGES/STL）")
    key = _file_hash(src)
    t0 = time.perf_counter()
    manifest = _load_manifest(key)
    if manifest is not None:
        asm = _assembly_from_manifest(manifest, src, key, ext)
        log.info("缓存命中（装配树清单）：%s，%d 个零件，%s", src.name, asm.stats["parts"],
                 "实体模型" if asm.is_brep else "面片模型")
    else:
        asm = _parse(src, key, ext)
        _save_manifest(asm)
        log.info("解析完成：%s，%d 个零件，%s", src.name, asm.stats["parts"],
                 "实体模型" if asm.is_brep else "面片模型")
    asm.stats["load_ms"] = (time.perf_counter() - t0) * 1000.0
    return asm


def _assembly_from_manifest(manifest: dict, src: pathlib.Path, key: str, ext: str) -> Assembly:
    """由缓存清单重建 Assembly（形状留空，tessellate 需要时再 _parse 附着）。"""
    tree = [AssemblyNode.from_dict(d) for d in manifest["tree"]]
    return Assembly(source_path=str(src), source_hash=key, ext=ext,
                    is_brep=bool(manifest["is_brep"]), tree=tree,
                    stats={"parts": int(manifest["parts"]), "tris": 0, "cache": "hit"})


def _parse(src: pathlib.Path, key: str, ext: str) -> Assembly:
    """实际解析源文件，构建带活形状的装配树（缓存未命中、或需重新附着形状时调用）。"""
    if ext in _MESH_EXT:
        shape = _read_mesh_file(src)
        # STL 是三角面片汤、无装配/零件语义：整体作单一显示部件，避免每个三角面裂成一个 part
        roots = [AssemblyNode(node_id=1, name=src.stem, is_assembly=False, shape=shape)]
        is_brep = False
    else:
        roots = _read_cad_file(src, ext)
        is_brep = True
    asm = Assembly(source_path=str(src), source_hash=key, ext=ext, is_brep=is_brep, tree=roots)
    asm.stats.update(parts=sum(1 for _ in asm.iter_parts()), tris=0, cache="miss")
    return asm


def _read_cad_file(src: pathlib.Path, ext: str) -> list[AssemblyNode]:
    """读 STEP/IGES：先直读；非 ASCII 路径且无实体时，复制到 ASCII 短路径再读（兜底）。"""
    roots = _transfer_to_tree(_make_reader(ext), src, src.stem)
    if roots is None and not _is_ascii(str(src)):
        with tempfile.TemporaryDirectory(prefix="mecharm_") as td:
            short = pathlib.Path(td) / "model.tmp"
            shutil.copyfile(src, short)
            log.info("中文路径直读失败，改用短路径副本重试：%s", src.name)
            roots = _transfer_to_tree(_make_reader(ext), short, src.stem)
    if roots is None:
        raise GeometryError(f"读取失败或文件不含可用几何：{src.name}")
    return roots


def _make_reader(ext: str):
    return STEPControl_Reader() if ext in _STEP_EXT else IGESControl_Reader()


def _transfer_to_tree(reader, src: pathlib.Path, stem: str) -> list[AssemblyNode] | None:
    """驱动 reader 读盘并转移，把根形状分解为装配树；无实体返回 None。"""
    reader.ReadFile(str(src))
    reader.TransferRoots()
    n = reader.NbShapes()
    if n == 0:
        return None
    counters = _Counters()
    return [_build_tree(reader.Shape(i), counters, stem, top=(i == 1 and n == 1))
            for i in range(1, n + 1)]


def _read_mesh_file(src: pathlib.Path) -> TopoDS_Shape:
    """读 STL 为网格形状（面片模型）。失败抛 GeometryError。"""
    reader = StlAPI_Reader()
    shape = TopoDS_Shape()
    if not reader.Read(shape, str(src)) or shape.IsNull():
        raise GeometryError(f"STL 读取失败：{src.name}")
    return shape


class _Counters:
    """装配树命名计数器：零件与子装配各自递增，node_id 全局递增，保证名字稳定可读。"""

    def __init__(self) -> None:
        self.part = 0
        self.assy = 0
        self.node_id = 0

    def next_id(self) -> int:
        self.node_id += 1
        return self.node_id


def _build_tree(shape: TopoDS_Shape, c: _Counters, name: str, top: bool = False) -> AssemblyNode:
    """把 OCC 形状递归分解为装配树：compound/compsolid→子装配，solid/shell→零件叶子。"""
    if shape.ShapeType() in (TopAbs_COMPOUND, TopAbs_COMPSOLID):
        node = AssemblyNode(node_id=c.next_id(), is_assembly=True,
                            name=name if top else f"子装配_{c.assy + 1}")
        if not top:
            c.assy += 1
        it = TopoDS_Iterator(shape)
        while it.More():
            node.children.append(_build_tree(it.Value(), c, "", top=False))
            it.Next()
        return node
    c.part += 1
    return AssemblyNode(node_id=c.next_id(), name=f"零件_{c.part}", is_assembly=False, shape=shape)


def _is_ascii(text: str) -> bool:
    return text.isascii()
