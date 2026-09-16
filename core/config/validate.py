"""core.config.validate —— machine.yaml 各节的强校验（T03）。

统一纪律（03 §4「缺项拒绝启动并列明细」）：所有校验函数都往调用方传入的 ``problems``
列表里**追加**字段路径＋问题描述，**不就地抛异常**；由 loader.load_machine 收齐后一次性
抛 ConfigError，使现场能一次改完全部问题，而不是改一条跑一次。

返回 None／空集合表示「该节有致命问题，问题已记入 problems」，调用方不再重复报。
"""

from __future__ import annotations

import os
import pathlib
from collections.abc import Mapping, Sequence

from core.config.schema import (AXIS_ROLES, AXIS_TYPES, COUPLING_TYPES, LIMIT_KEYS, PACK_PROFILES,
                                READ_NODE_SPEC, REPO_ROOT, TRAJECTORY_AXES_MAX, UNIT_BY_TYPE,
                                WRITE_NODE_SPEC, ZERO_OFFSET_KEY, Axis, Coupling, Limits, Link,
                                Machine, Mode, OpcUa, Paths)

Problems = list[str]


def _mapping(problems: Problems, where: str, src: object,
             null_ok_keys: Sequence[str] = ()) -> bool:
    """校验 src 是映射，并报 `null_ok_keys`（必填、但值允许显式写 null）的缺键。

    其余必填键的缺失**由各自的字段校验器报**（它们本来就要对 None 值报错），此处不重复报——
    否则同一处缺陷会出现两条消息，使「共 N 项问题」计数虚高、现场误判要改几处。
    返回 True 即**保证** src 是 Mapping，故调用方可直接 ``src.get(...)`` 无需再判类型。
    """
    if not isinstance(src, Mapping):
        problems.append(f"{where}: 应为映射，实得 {type(src).__name__}")
        return False
    for key in null_ok_keys:
        if key not in src:
            problems.append(f"{where}: 缺必填字段 `{key}`（值可写 null，但键必须显式列出）")
    return True


def _num(problems: Problems, where: str, key: str, raw: object, *,
         allow_none: bool = False, positive: bool = False) -> float | None:
    """取数值字段；类型错（bool 不算数值）或取值域错记入 problems 并返回 None。"""
    if raw is None:
        if allow_none:
            return None
        problems.append(f"{where}.{key}: 缺必填字段或值为 null（应为数值）")
        return None
    if isinstance(raw, bool) or not isinstance(raw, (int, float)):
        problems.append(f"{where}.{key}: 应为数值，实得 {type(raw).__name__}={raw!r}")
        return None
    value = float(raw)
    if positive and value <= 0.0:
        problems.append(f"{where}.{key}: 应为正数，实得 {value}")
        return None
    return value


def _text(problems: Problems, where: str, key: str, raw: object,
          choices: Sequence[str] | None = None) -> str | None:
    """取字符串字段；choices 非空时限定取值集合（type／role／pack_profile 等）。"""
    if not isinstance(raw, str) or not raw:
        problems.append(f"{where}.{key}: 缺必填字段或应为非空字符串，实得 {raw!r}")
        return None
    if choices and raw not in choices:
        problems.append(f"{where}.{key}: 取值应为 {'|'.join(choices)} 之一，实得 {raw!r}")
        return None
    return raw


def _travel(problems: Problems, where: str, raw: object) -> tuple[float, float] | None:
    """行程 [min, max]（单位随轴型：mm／deg）；元素非数值或 min ≥ max 即拒。"""
    if isinstance(raw, (str, bytes)) or not isinstance(raw, Sequence) or len(raw) != 2:
        problems.append(f"{where}.travel: 缺必填字段或应为 [min, max] 两元素数组，实得 {raw!r}")
        return None
    bounds = [_num(problems, where, f"travel[{index}]", value)
              for index, value in enumerate(raw)]
    if any(bound is None for bound in bounds):
        return None
    low, high = bounds
    if low >= high:
        problems.append(f"{where}.travel: min 必须 < max，实得 [{low}, {high}]")
        return None
    return (low, high)


def _zero_offset(problems: Problems, where: str, axis_type: str | None,
                 raw: Mapping) -> float | None:
    """零点偏移；键名后缀必须与轴型单位一致（prismatic→_mm、revolute→_deg）。"""
    if axis_type not in ZERO_OFFSET_KEY:
        return None  # 轴型本身已报错，不重复报
    key = ZERO_OFFSET_KEY[axis_type]
    if key not in raw:
        problems.append(f"{where}: 缺必填字段 `{key}`（{axis_type} 轴零点，"
                        f"单位 {UNIT_BY_TYPE[axis_type]}）")
        return None
    return _num(problems, where, key, raw.get(key))


def _direction(problems: Problems, where: str, raw: object) -> int | None:
    """运动方向符号，只允许 ±1（标定四要素之一；契约 §7.4：不得推断）。"""
    if isinstance(raw, bool) or not isinstance(raw, int) or raw not in (1, -1):
        problems.append(f"{where}.direction: 缺必填字段或应为 1／-1，实得 {raw!r}")
        return None
    return raw


def _coupling(problems: Problems, where: str, raw: object) -> Coupling | None:
    """coupling：null｜{type: sync, group, sync_tol_mm}｜{type: ratio, master, ratio}。"""
    if raw is None:
        return None
    if not _mapping(problems, where, raw):
        return None
    kind = _text(problems, where, "type", raw.get("type"), COUPLING_TYPES)
    if kind == "sync":
        group = _text(problems, where, "group", raw.get("group"))
        tol = _num(problems, where, "sync_tol_mm", raw.get("sync_tol_mm"), positive=True)
        return Coupling(kind, group=group, sync_tol_mm=tol) if group and tol else None
    if kind == "ratio":
        master = _text(problems, where, "master", raw.get("master"))
        ratio = _num(problems, where, "ratio", raw.get("ratio"), positive=True)
        return Coupling(kind, master=master, ratio=ratio) if master and ratio else None
    return None


def _axis(raw: object, index: int, problems: Problems) -> Axis | None:
    """单轴；返回 None 表示该轴有致命问题（问题已记入 problems）。"""
    where = f"axes[{index}]"
    if not _mapping(problems, where, raw, ("scale", "coupling")):
        return None
    axis_id = _text(problems, where, "id", raw.get("id"))
    axis_type = _text(problems, where, "type", raw.get("type"), AXIS_TYPES)
    role = _text(problems, where, "role", raw.get("role"), AXIS_ROLES)
    travel = _travel(problems, where, raw.get("travel"))
    offset = _zero_offset(problems, where, axis_type, raw)
    direction = _direction(problems, where, raw.get("direction"))
    scale = _num(problems, where, "scale", raw.get("scale"), allow_none=True, positive=True)
    coupling = _coupling(problems, f"{where}.coupling", raw.get("coupling"))
    if offset is None or not all((axis_id, axis_type, role, travel, direction)):
        return None
    return Axis(axis_id, axis_type, role, travel, offset, direction, scale, coupling,
                bool(raw.get("pending", False)))


def axes_section(problems: Problems, raw: object) -> dict[str, Axis]:
    """轴表；id 重复即拒（modes 子集与 coupling.master 都按 id 引用）。"""
    if not isinstance(raw, list) or not raw:
        problems.append(f"axes: 应为非空数组，实得 {type(raw).__name__}")
        return {}
    table: dict[str, Axis] = {}
    for index, item in enumerate(raw):
        axis = _axis(item, index, problems)
        if axis is None:
            continue
        if axis.id in table:
            problems.append(f"axes[{index}].id: 轴 id `{axis.id}` 重复")
            continue
        table[axis.id] = axis
    return table


def modes_section(problems: Problems, raw: object, axes: Mapping[str, Axis]) -> tuple[Mode, ...]:
    """工作模式→轴子集：子集必须 ⊆ axes，且轨迹级轴计数 ≤ TRAJECTORY_AXES_MAX。"""
    if not isinstance(raw, list) or not raw:
        problems.append(f"modes: 应为非空数组，实得 {type(raw).__name__}")
        return ()
    out: list[Mode] = []
    for index, item in enumerate(raw):
        where = f"modes[{index}]"
        if not _mapping(problems, where, item):
            continue
        mode_id = _text(problems, where, "id", item.get("id"))
        name = _text(problems, where, "name", item.get("name"))
        members = item.get("axes")
        if not isinstance(members, list) or not members:
            problems.append(f"{where}.axes: 应为非空数组，实得 {members!r}")
            continue
        unknown = [str(member) for member in members if member not in axes]
        if unknown:
            problems.append(f"{where}.axes: 轴 id 不在 axes 表内 → {', '.join(unknown)}")
        trajectory = [m for m in members if axes.get(m) and axes[m].role == "trajectory"]
        if len(trajectory) > TRAJECTORY_AXES_MAX:
            problems.append(f"{where}.axes: 轨迹级轴 {len(trajectory)} 个 > 上限 "
                            f"{TRAJECTORY_AXES_MAX}（{', '.join(map(str, trajectory))}）")
        if mode_id and name and not unknown:
            out.append(Mode(mode_id, name, tuple(str(member) for member in members)))
    return tuple(out)


def links_section(problems: Problems, raw: object) -> tuple[Link, ...]:
    """连杆表（length_mm 单位 mm）；parent／axis 为表内 id 或 null，motion 取 x|y|z 或 null（G18）。"""
    if not isinstance(raw, list) or not raw:
        problems.append(f"links: 应为非空数组，实得 {type(raw).__name__}")
        return ()
    out: list[Link] = []
    for index, item in enumerate(raw):
        where = f"links[{index}]"
        if not _mapping(problems, where, item, ("parent", "axis", "motion")):
            continue
        link_id = _text(problems, where, "id", item.get("id"))
        length = _num(problems, where, "length_mm", item.get("length_mm"))
        parent = item.get("parent")
        if parent is not None and not isinstance(parent, str):
            problems.append(f"{where}.parent: 应为 links 表内 id 或 null，实得 {parent!r}")
            parent = None
        if link_id and length is not None and "axis" in item and "motion" in item:
            out.append(Link(link_id, length, parent, item.get("axis"), item.get("motion")))
    known = {link.id for link in out}
    for link in out:
        if link.parent is not None and link.parent not in known:
            problems.append(f"links[{link.id}].parent: `{link.parent}` 不在 links 表内")
    return tuple(out)


def limits_section(problems: Problems, raw: object) -> Limits | None:
    """limits 节：8 个字段全部必填且为正数（单位见键名后缀）。"""
    if not _mapping(problems, "limits", raw):
        return None
    values = {key: _num(problems, "limits", key, raw.get(key), positive=True)
              for key in LIMIT_KEYS}
    if any(value is None for value in values.values()):
        return None
    return Limits(**values)


def _nodes(problems: Problems, where: str, raw: object,
           spec: Sequence[tuple[str, bool]]) -> Mapping[str, object] | None:
    """节点子表：spec 里 (键, True) 为非空 NodeId 数组，(键, False) 为单个 NodeId 字符串。"""
    if not _mapping(problems, where, raw):
        return None
    out: dict[str, object] = {}
    for key, is_list in spec:
        value = raw.get(key)
        if not is_list:
            node = _text(problems, where, key, value)
            if node is None:
                return None
            out[key] = node
            continue
        if not isinstance(value, list) or not value or \
                not all(isinstance(item, str) and item for item in value):
            problems.append(f"{where}.{key}: 应为非空 NodeId 字符串数组，实得 {value!r}")
            return None
        out[key] = tuple(value)
    return out


def opcua_section(problems: Problems, raw: object) -> OpcUa | None:
    """opcua 节：节点表按契约 DB 布局自造（模拟期占位，Q 回执后改此文件不改代码）。"""
    if not _mapping(problems, "opcua", raw):
        return None
    url = _text(problems, "opcua", "endpoint_url", raw.get("endpoint_url"))
    policy = _text(problems, "opcua", "security_policy", raw.get("security_policy"))
    profile = _text(problems, "opcua", "pack_profile", raw.get("pack_profile"), PACK_PROFILES)
    ns_index = raw.get("ns_index")
    if isinstance(ns_index, bool) or not isinstance(ns_index, int) or ns_index < 0:
        problems.append(f"opcua.ns_index: 应为非负整数，实得 {ns_index!r}")
        ns_index = None
    interval = _num(problems, "opcua", "publish_interval_ms", raw.get("publish_interval_ms"),
                    positive=True)
    read_nodes = _nodes(problems, "opcua.read_nodes", raw.get("read_nodes"), READ_NODE_SPEC)
    write_nodes = _nodes(problems, "opcua.write_nodes", raw.get("write_nodes"), WRITE_NODE_SPEC)
    if not all((url, policy, profile, ns_index is not None, interval, read_nodes, write_nodes)):
        return None
    return OpcUa(url, policy, ns_index, profile, read_nodes, write_nodes, interval)


def paths_section(problems: Problems, raw: object) -> Paths | None:
    """paths.cache_dir：必须是**仓外绝对路径**（涉密边界；相对路径或落仓根内一律拒载）。"""
    if not _mapping(problems, "paths", raw):
        return None
    value = raw.get("cache_dir")
    if not isinstance(value, str) or not value.strip():
        problems.append(f"paths.cache_dir: 缺必填字段或应为非空字符串，实得 {value!r}")
        return None
    expanded = os.path.expandvars(value.strip())
    if not os.path.isabs(expanded):
        problems.append("paths.cache_dir: 必须是仓外绝对路径（默认 "
                        "%LOCALAPPDATA%\\mecharm\\cache），实得相对路径 "
                        f"{value!r}")
        return None
    resolved = pathlib.Path(expanded).resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        problems.append(f"paths.cache_dir: 不得落在仓根目录内（仓根 {REPO_ROOT}），实得 "
                        f"{resolved}——缓存是甲方模型几何真身，远端为公开仓")
        return None
    return Paths(str(resolved))


def machine_section(problems: Problems, raw: object) -> Machine | None:
    """machine 节：设备名与配置结构版本号。"""
    if not _mapping(problems, "machine", raw):
        return None
    name = _text(problems, "machine", "name", raw.get("name"))
    version = _text(problems, "machine", "schema_ver", raw.get("schema_ver"))
    return Machine(name, version) if name and version else None
