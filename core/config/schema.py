"""core.config.schema —— machine.yaml 的定型结构与取值常量（T03）。

只放：字段名常量、ConfigError、dataclass 定型。**不放任何校验逻辑**（在 validate.py）
与读写逻辑（在 loader.py），以保证三个子模块各自单一职责（04 §4.5-③）。

单位与坐标系按 S-1 契约第 7 章：长度 mm、角度 deg、线速度 mm/s、角速度 deg/s、
加速度 mm/s²、时间 ms；场景为右手系、Z 竖直向上。移动副的零点键为 ``zero_offset_mm``、
回转副为 ``zero_offset_deg``——**键名后缀即单位**，与轴型不符即拒载。
"""

from __future__ import annotations

import pathlib
from collections.abc import Mapping
from dataclasses import dataclass

# 仓根＝本文件的祖父目录（core/config/schema.py → core/config → core → 仓根）。
# 用于 paths.cache_dir 的「不得落仓内」判定（03 §4／04 §7.1-10：缓存内是甲方模型几何真身，
# 远端为公开仓）。⚠️ 拆包前本文件在 core/config.py，层级少一层——改回单文件须同步改这里。
REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]

AXIS_TYPES = ("prismatic", "revolute")
AXIS_ROLES = ("trajectory", "setup")
COUPLING_TYPES = ("sync", "ratio")
PACK_PROFILES = ("v1_2_8axis", "v1_3_24axis")
# pack_profile → 回读 axis_pos 节点数（＝契约 §5.2 的 Pos[] 长度），用于「节点表与 pack_profile
# 禁只改一边」的一致性校验。V1.3 尚未冻结（CR-2026-03 §三-5：EnableMask 加宽能否吞并 Reserved2
# 仍悬置，且 22 轴是否占满 24 槽位未定），故记 None：加载器对 None 跳过校验，冻结后回填数字即生效。
PACK_PROFILE_AXIS_COUNT: dict[str, int | None] = {"v1_2_8axis": 8, "v1_3_24axis": None}
TRAJECTORY_AXES_MAX = 9  # 03 §4「实机轴系口径」：每工作模式的轨迹级轴上限
SECTIONS = ("machine", "axes", "modes", "links", "limits", "opcua", "paths")
LIMIT_KEYS = ("speed_max_mm_s", "speed_rapid_mm_s", "speed_work_mm_s", "accel_max_mm_s2",
              "clearance_warn_mm", "collision_envelope_mm", "tessellate_deflection_mm",
              "path_sample_step_mm")
# 节点子表规格：(键名, 是否为 NodeId 数组)。axis_pos 的**个数**由 PACK_PROFILE_AXIS_COUNT 约束
READ_NODE_SPEC = (("axis_pos", True), ("status", False), ("heartbeat", False))
WRITE_NODE_SPEC = (("cmd", False), ("seg_count", False), ("seg_array", False))
AXIS_KEYS = ("id", "type", "role", "travel", "direction", "scale", "coupling")
MODE_KEYS = ("id", "name", "axes")
LINK_KEYS = ("id", "length_mm", "parent")
MACHINE_KEYS = ("name", "schema_ver")
OPCUA_KEYS = ("endpoint_url", "security_policy", "ns_index", "pack_profile",
              "read_nodes", "write_nodes", "publish_interval_ms")
ZERO_OFFSET_KEY = {"prismatic": "zero_offset_mm", "revolute": "zero_offset_deg"}
UNIT_BY_TYPE = {"prismatic": "mm", "revolute": "deg"}


class ConfigError(Exception):
    """machine.yaml 校验不通过：缺字段／类型错／取值非法／缓存路径落仓内。"""


@dataclass(frozen=True)
class Coupling:
    """轴耦合。sync＝多驱动单元同步（group 内偏差超 sync_tol_mm 报 Violation，T04 消费）；
    ratio＝倍速链（从动轴位置 = master × ratio，T04 的 fk 按配置换算，禁外部反推）。"""

    type: str
    group: str | None = None
    sync_tol_mm: float | None = None
    master: str | None = None
    ratio: float | None = None


@dataclass(frozen=True)
class Axis:
    """单个受控运动轴。travel 与 zero_offset 的单位随 type：prismatic＝mm、revolute＝deg；
    scale＝原始值→工程值比例系数（null 表示回读已是工程值，契约 §7.4）；
    direction＝±1 标定符号；pending＝True 表示行程／零点／正方向待电气·机械回执、
    当前为占位值（加载器只告警不拒绝）。"""

    id: str
    type: str
    role: str
    travel: tuple[float, float]
    zero_offset: float
    direction: int
    scale: float | None
    coupling: Coupling | None
    pending: bool


@dataclass(frozen=True)
class Mode:
    """工作模式（快接换臂）→ 当前有效轴子集；axes 为轴 id，轨迹级计数 ≤ 9。"""

    id: str
    name: str
    axes: tuple[str, ...]


@dataclass(frozen=True)
class Link:
    """连杆几何（T04 的 fk 链式变换用）；length_mm 单位 mm，parent 为 links 表内 id。"""

    id: str
    length_mm: float
    parent: str | None


@dataclass(frozen=True)
class Limits:
    """全局限值。速度 mm/s、加速度 mm/s²、其余 mm；一律配置驱动，禁代码里散写字面量。"""

    speed_max_mm_s: float
    speed_rapid_mm_s: float
    speed_work_mm_s: float
    accel_max_mm_s2: float
    clearance_warn_mm: float
    collision_envelope_mm: float
    tessellate_deflection_mm: float
    path_sample_step_mm: float


@dataclass(frozen=True)
class OpcUa:
    """OPC UA 接入参数（模拟期占位，Q 回执后只改 machine.yaml 不改代码）。
    endpoint_url 形如 opc.tcp://host:port；read_nodes.axis_pos 为 NodeId 元组，
    其长度须与 pack_profile 匹配（v1_2_8axis＝8，契约 §6.1）。"""

    endpoint_url: str
    security_policy: str
    ns_index: int
    pack_profile: str
    read_nodes: Mapping[str, object]
    write_nodes: Mapping[str, str]
    publish_interval_ms: float


@dataclass(frozen=True)
class Paths:
    """落盘路径。cache_dir 为展开并解析后的**仓外**绝对路径（缓存与离线资产库根目录）。"""

    cache_dir: str


@dataclass(frozen=True)
class Machine:
    """machine 节：设备名（可上屏，故允许中文）与配置结构版本号。"""

    name: str
    schema_ver: str


@dataclass(frozen=True)
class MachineConfig:
    """整份 machine.yaml 的定型结果。axes 为 id→Axis 的插入序映射（序即契约 Pos[] 排法），
    warnings 为不拒绝启动的告警（当前只有 pending 占位轴一类）。"""

    machine: Machine
    axes: dict[str, Axis]
    modes: tuple[Mode, ...]
    links: tuple[Link, ...]
    limits: Limits
    opcua: OpcUa
    paths: Paths
    warnings: tuple[str, ...]
