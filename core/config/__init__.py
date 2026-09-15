"""core.config —— machine.yaml 参数体系（T03；规程 W-4.1「配置先行」的落码件）。

本包是**拆包形态**：原单文件 `core/config.py` 实测 488 行，超 04 §4.5-① 的 300 行上限，
故按 T03 派单卡预授权的结构拆为三个子模块（04 §4.5-②③ 的「去重复→抽函数→拆文件」）：

    schema.py    字段名常量、ConfigError、dataclass 定型（无逻辑）
    validate.py  各节强校验，问题追加进 problems 列表、不就地抛
    loader.py    读盘 + 收齐问题 + 一次性抛错 / 返回 MachineConfig

本文件**只做 re-export 与 __all__，禁写任何业务逻辑**（04 §4.5-⑦ 硬要求 1）；拆分前后
调用形态一字不变——`from core.config import load_machine, ConfigError, MachineConfig`
照旧成立（硬要求 2），下游 T04／T09 无需知道内部拆分。
"""

from core.config.loader import load_machine
from core.config.schema import (AXIS_KEYS, AXIS_ROLES, AXIS_TYPES, COUPLING_TYPES, LIMIT_KEYS,
                                LINK_KEYS, MACHINE_KEYS, MODE_KEYS, OPCUA_KEYS, PACK_PROFILES,
                                READ_NODE_SPEC, REPO_ROOT, SECTIONS, TRAJECTORY_AXES_MAX,
                                UNIT_BY_TYPE, WRITE_NODE_SPEC, ZERO_OFFSET_KEY, Axis,
                                ConfigError, Coupling, Limits, Link, Machine, MachineConfig,
                                Mode, OpcUa, Paths)

__all__ = [
    "load_machine", "ConfigError", "MachineConfig", "Machine", "Axis", "Coupling", "Mode",
    "Link", "Limits", "OpcUa", "Paths",
    "REPO_ROOT", "SECTIONS", "AXIS_KEYS", "AXIS_TYPES", "AXIS_ROLES", "COUPLING_TYPES",
    "MODE_KEYS", "LINK_KEYS", "LIMIT_KEYS", "MACHINE_KEYS", "OPCUA_KEYS", "PACK_PROFILES",
    "READ_NODE_SPEC", "WRITE_NODE_SPEC", "ZERO_OFFSET_KEY", "UNIT_BY_TYPE",
    "TRAJECTORY_AXES_MAX",
]
