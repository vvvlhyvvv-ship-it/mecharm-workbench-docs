"""core.project —— 工程文件的保存／加载与版本兼容（T10 卡片步骤 5）。

**落盘的是「快照」不是「第二份真值」**（03 §3 单向数据流）：点位（`Waypoint`）是重新生成路径的**输入**，
故按原样存；路径段与校核结论是**派生结果**，存下来只为「这份工程当时算出了什么」可追溯——加载后
一律按结果作废处理（点位一恢复，步骤③④由既有作废链自动清空），⛔ 不把快照当现成结论继续用。

版本口径（卡片步骤 5「按版本兼容策略迁移」）：
  · `$schema` ＝ **`proj/v1`**（本件唯一在产版本）。
  · 缺 `$schema`／格式不认 ⇒ `ProjectError` 人话拒载（⛔ 不猜版本、⛔ 不按 v1 硬读）。
  · 比本软件**新**（`proj/v2` 及以后）⇒ 拒载并提示升级软件：新版本可能带本件读不懂的字段，
    静默丢弃＝给用户一份看着完整、实则缺项的工程（同 04 §5.5 附7-③「掏空下游契约」那一族）。
  · 比本软件**旧** ⇒ 走 `_MIGRATIONS` 逐级升到 `proj/v1` 再读。⚠️ 该表**当前为空**：v1 是首个
    在产版本、仓内没有更早的工程文件，⛔ 不为「让迁移看起来有内容」而虚构一个 v0 格式；
    机制本身由 `tests/test_project.py` 用临时注册的迁移步验证（真出旧版本时只加表项、不改读法）。

`config_ver` 存 `machine.yaml` 的 `machine.schema_ver`：加载时与当前配置比对，不一致即人话告警
（参数体系换过版，旧工程的行程／零点口径可能已不同，须重新生成路径与校核）。

GUI-free ⇒ 落 `core/` 而非 `app/`（03 §3 铁律：core 不得 import GUI）。本单只交 core 侧的读写与版本
策略（派单 §3 步 5）；文件选择对话框、确认弹窗、告警上屏属 UI 口径，由 app 层控制器调本模块 API。
"""

from __future__ import annotations

import json
import pathlib
import re
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass
from datetime import datetime

from core.collision import CollisionResult
from core.config.schema import MachineConfig
from core.geometry.face_point import Waypoint
from core.path import PathSummary, Segment

SCHEMA = "proj/v1"          # 本件在产的工程文件版本（`$schema` 字段值）
SCHEMA_RE = re.compile(r"^proj/v(\d+)$")
SCHEMA_MAJOR = 1            # 与 SCHEMA 同步；比它新即拒载（见模块 docstring）
EXTENSION = ".mproj"        # 工程文件后缀；正文仍是 JSON，可直接文本查看（对话框过滤串属 UI 口径，由 app 层拼）


class ProjectError(Exception):
    """工程文件读写失败：版本不认／结构缺项／类型不对／磁盘错误。消息一律人话、可直上屏。"""


@dataclass(frozen=True)
class ModelRef:
    """步骤①导入模型的**出处记录**（⛔ 不存几何：模型本体在磁盘与 core 的 B-Rep 缓存里）。"""

    source_path: str
    is_brep: bool
    part_count: int


@dataclass(frozen=True)
class PathSnap:
    """步骤③路径的快照：生成选项＋汇总人话＋逐段摘要（供「当时算出了什么」追溯）。"""

    kind: str
    blending: bool
    summary: str
    segments: tuple[Mapping[str, object], ...]


@dataclass(frozen=True)
class CheckSnap:
    """步骤④校核结论的快照（卡片步骤 5 点名的「校核结论快照」）。"""

    verdict: str
    sentence: str
    coverage: str
    path_hash: str
    elapsed_ms: float


@dataclass(frozen=True)
class Project:
    """一份工程文件的全部内容。全 frozen：加载后只读，改动只能另存新文件。"""

    schema: str
    saved_at: str
    config_name: str
    config_ver: str
    mode: str | None
    model: ModelRef | None
    waypoints: tuple[Waypoint, ...]
    path: PathSnap | None
    check: CheckSnap | None


# 旧版本 → 新版本的**单级**迁移步（入参＝刚解析出的 dict，返回改写后的 dict）。当前为空，理由见 docstring。
_MIGRATIONS: dict[str, Callable[[dict], dict]] = {}


def path_snapshot(segments: list[Segment], summary: PathSummary, kind: str, blending: bool) -> PathSnap:
    """段序列 → 快照。只取可追溯字段（段号／段型／长度／可达性与人话原因），⛔ 不存关节目标——
    那由点位＋配置重新生成，存进文件只会造出第二份可能过期的真值。"""
    return PathSnap(kind=kind, blending=blending, summary=summary.describe(),
                    segments=tuple({"id": seg.id, "type": seg.type, "length_mm": seg.length_mm,
                                    "from": seg.start_name, "to": seg.end_name,
                                    "blocked": seg.blocked, "reason": seg.reason}
                                   for seg in segments))


def check_snapshot(result: CollisionResult) -> CheckSnap:
    """校核结论 → 快照。`sentence`／`coverage` 取 core 的**人话原文**（G19 覆盖面标注一并存下来，
    免得日后只看文件把「未检出碰撞」误读成「通过」）。"""
    return CheckSnap(verdict=result.verdict, sentence=result.describe(),
                     coverage=result.coverage(), path_hash=result.path_hash,
                     elapsed_ms=result.elapsed_ms)


def save(project: Project, path: str | pathlib.Path) -> pathlib.Path:
    """写盘（UTF-8、缩进 2 便于现场用文本编辑器核对）。返回实际写入的路径。"""
    target = pathlib.Path(path)
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(to_dict(project), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        raise ProjectError(f"工程文件写不出去：{exc}") from exc
    return target


def load(path: str | pathlib.Path) -> Project:
    """读盘并定型。任何不认的情形都抛 `ProjectError`（人话），⛔ 不返回半成品、⛔ 不塞默认值。"""
    source = pathlib.Path(path)
    try:
        raw = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProjectError(f"找不到工程文件：{source}") from exc
    except OSError as exc:
        raise ProjectError(f"工程文件读不进来：{exc}") from exc
    except json.JSONDecodeError as exc:
        raise ProjectError(f"工程文件不是合法 JSON（第 {exc.lineno} 行第 {exc.colno} 列）：{exc.msg}") from exc
    if not isinstance(raw, dict):
        raise ProjectError(f"工程文件顶层应是对象，实得 {type(raw).__name__}")
    return from_dict(migrate(raw, source))


def migrate(raw: dict, source: pathlib.Path | None = None) -> dict:
    """按 `$schema` 把旧版本工程逐级升到 `SCHEMA`；不认的版本一律拒（见模块 docstring）。"""
    where = f"（{source}）" if source else ""
    version = raw.get("$schema")
    if not isinstance(version, str):
        raise ProjectError(f"工程文件缺 $schema 字段，无法判定版本{where}：本软件只认 {SCHEMA} 及以后")
    match = SCHEMA_RE.match(version)
    if not match:
        raise ProjectError(f"工程文件版本「{version}」不是本软件的格式{where}：应为 {SCHEMA} 一类")
    major = int(match.group(1))
    if major > SCHEMA_MAJOR:
        raise ProjectError(f"工程文件版本 {version} 比本软件支持的 {SCHEMA} 新{where}："
                           f"请升级软件后再打开（新版本可能含本软件读不懂的字段，硬读会丢内容）")
    seen: list[str] = []
    while version != SCHEMA:
        step = _MIGRATIONS.get(version)
        if step is None:
            raise ProjectError(f"工程文件版本 {version} 无迁移步可升到 {SCHEMA}{where}："
                               f"已尝试 {' → '.join(seen) or '（无）'}")
        seen.append(version)
        raw = step(raw)
        version = raw.get("$schema")
        if not isinstance(version, str):
            raise ProjectError(f"迁移步 {seen[-1]} 之后丢了 $schema 字段{where}")
        if version in seen:
            raise ProjectError(f"工程文件版本迁移成环{where}：{' → '.join(seen + [version])}")
    return raw


def to_dict(project: Project) -> dict:
    """Project → 可 JSON 序列化的 dict。用 `dataclasses.asdict` 递归展开，⛔ **不手抄字段表**：抄一份
    就会与数据类定义走岔，日后加字段时静默漏存＝给用户一份看着完整、实则缺项的工程（04 §5.5 附7-③
    「掏空下游契约」那一族）。只做两处收拾：`schema` 改名成 JSON 惯例的 `$schema`，并提到首位
    （版本字段要在文件头一眼看到）。"""
    raw = asdict(project)
    return {"$schema": raw.pop("schema"), **raw}


def from_dict(raw: Mapping[str, object]) -> Project:
    """dict → Project。缺项／类型不对即 `ProjectError` 人话，⛔ 不用默认值把窟窿填平。读的键与
    `to_dict`（＝`asdict` 的扁平输出）严格对称，两边任一处改字段名都会被 `tests/test_project.py`
    的存→读回环用例当场抓住。"""
    return Project(schema=_need(raw, "$schema", str), saved_at=_need(raw, "saved_at", str),
                   config_name=_need(raw, "config_name", str), config_ver=_need(raw, "config_ver", str),
                   mode=_need(raw, "mode", str, nullable=True), model=_model(raw.get("model")),
                   waypoints=tuple(_waypoints(raw.get("waypoints"))),
                   path=_path(raw.get("path")), check=_check(raw.get("check")))


def build_project(cfg: MachineConfig, mode: str | None, model: ModelRef | None, waypoints: list[Waypoint],
                  path: PathSnap | None, check: CheckSnap | None) -> Project:
    """装配一份待存工程：`saved_at` 取本机时钟（ISO 8601 带时区，现场对时用），配置版本取自 cfg。"""
    return Project(schema=SCHEMA, saved_at=datetime.now().astimezone().isoformat(timespec="seconds"),
                   config_name=cfg.machine.name, config_ver=cfg.machine.schema_ver, mode=mode,
                   model=model, waypoints=tuple(waypoints), path=path, check=check)


def config_drift(project: Project, cfg: MachineConfig) -> str | None:
    """工程记录的配置版本与当前 `machine.yaml` 是否不一致；一致返回 None，不一致返回人话告警。"""
    if project.config_ver == cfg.machine.schema_ver:
        return None
    return (f"工程文件记录的参数版本是 {project.config_ver}，当前机台配置是 {cfg.machine.schema_ver}"
            f"：行程／零点口径可能已变，须重新生成路径并重新校核后才能下发")


# --- 定型辅助（每个都只认一种形状，错了就人话报错；`where` 是字段路径，供报错定位）----------- #
def _need(raw: Mapping[str, object], key: str, kind: type, where: str = "",
          nullable: bool = False) -> object:
    """取必填字段并验类型。`nullable=True` 只 `mode` 一处用：未选定工作模式的工程是合法的，
    其余字段缺了就是文件坏了 ⛔ 不填默认值。"""
    if key not in raw:
        raise ProjectError(f"工程文件缺字段 {where + '.' if where else ''}{key}")
    value = raw[key]
    if value is None and nullable:
        return None
    if not isinstance(value, kind):
        raise ProjectError(f"工程文件字段 {where + '.' if where else ''}{key} 应是 {kind.__name__}，"
                           f"实得 {type(value).__name__}")
    return value


def _seq(value: object, where: str) -> list:
    """数组字段（null＝空）。⚠️ list 与 tuple **都收**：从 JSON 读回来是 list，而 `to_dict`
    （`asdict`）在内存里给的是 tuple——只认 list 会让「存完不落地就直接定型」这条路假失败。"""
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ProjectError(f"工程文件字段 {where} 应是数组，实得 {type(value).__name__}")
    return list(value)


def _number(value: object, where: str) -> float:
    """数字字段：JSON 会把 `12.0` 写成 `12` ⇒ int 与 float 都收（⛔ 不因写法差异拒载合法工程）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ProjectError(f"工程文件字段 {where} 应是数字，实得 {type(value).__name__}")
    return float(value)


def _vec3(value: object, where: str) -> tuple[float, float, float]:
    """三元素数字数组 → (x, y, z)。长度不对／元素非数字都人话报错（⛔ 不补 0）。"""
    items = _seq(value, where)
    if len(items) != 3:
        raise ProjectError(f"工程文件字段 {where} 应是 3 个数，实得 {len(items)} 个")
    try:
        return (float(items[0]), float(items[1]), float(items[2]))
    except (TypeError, ValueError) as exc:
        raise ProjectError(f"工程文件字段 {where} 含非数字：{items!r}") from exc


def _obj(value: object, where: str) -> dict | None:
    """可空对象字段（model／path／check 三处共用，⛔ 各写一份判定会走岔）。"""
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ProjectError(f"工程文件字段 {where} 应是对象或 null，实得 {type(value).__name__}")
    return value


def _model(value: object) -> ModelRef | None:
    value = _obj(value, "model")
    if value is None:
        return None
    return ModelRef(source_path=_need(value, "source_path", str, "model"),
                    is_brep=_need(value, "is_brep", bool, "model"),
                    part_count=_need(value, "part_count", int, "model"))


def _waypoints(value: object) -> list[Waypoint]:
    out = []
    for index, item in enumerate(_seq(value, "waypoints")):
        where = f"waypoints[{index}]"
        if not isinstance(item, dict):
            raise ProjectError(f"工程文件字段 {where} 应是对象，实得 {type(item).__name__}")
        out.append(Waypoint(id=_need(item, "id", int, where), name=_need(item, "name", str, where),
                            pos_mm=_vec3(item.get("pos_mm"), f"{where}.pos_mm"),
                            normal=_vec3(item.get("normal"), f"{where}.normal"),
                            source_face=_need(item, "source_face", int, where)))
    return out


def _path(value: object) -> PathSnap | None:
    value = _obj(value, "path")
    if value is None:
        return None
    return PathSnap(kind=_need(value, "kind", str, "path"), blending=_need(value, "blending", bool, "path"),
                    summary=_need(value, "summary", str, "path"),
                    segments=tuple(dict(seg) for seg in _seq(value.get("segments"), "path.segments")
                                   if isinstance(seg, dict)))


def _check(value: object) -> CheckSnap | None:
    value = _obj(value, "check")
    if value is None:
        return None
    return CheckSnap(verdict=_need(value, "verdict", str, "check"),
                     sentence=_need(value, "sentence", str, "check"),
                     coverage=_need(value, "coverage", str, "check"),
                     path_hash=_need(value, "path_hash", str, "check"),
                     elapsed_ms=_number(value.get("elapsed_ms"), "check.elapsed_ms"))
