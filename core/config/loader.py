"""core.config.loader —— 读盘、收齐问题、返回定型结果（T03）。

对外入口只有一个：``load_machine(path) -> MachineConfig``（03 架构 §4 的签名，禁改）。
校验语义＝「缺项拒绝启动并列明细」：问题**一次性收集**再抛 ConfigError，消息按字段路径
逐行列全，不逐条抛、不只报第一个。唯一软处置是 ``pending: true`` 的轴——**只告警不拒绝**
（回执前允许带占位跑仿真），告警进 ``MachineConfig.warnings``，由 tools/config_check.py 打印。
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

import yaml

from core.config.schema import (PACK_PROFILE_AXIS_COUNT, SECTIONS, Axis, ConfigError,
                                MachineConfig, OpcUa)
from core.config.validate import (axes_section, limits_section, links_section, machine_section,
                                  modes_section, opcua_section, paths_section)


def _format(path: str, problems: Sequence[str]) -> str:
    """把全部问题拼成多行消息（「消息列出全部问题项」是 T03 卡的硬要求）。"""
    detail = "\n".join(f"  - {item}" for item in problems)
    return f"{path}: 参数校验不通过，共 {len(problems)} 项问题\n{detail}"


def _read_yaml(path: str) -> Mapping:
    """读文件并解析；文件不可读／非法 YAML／顶层不是映射 → 直接抛 ConfigError。"""
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"{path}: 无法读取配置文件 → {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML 解析失败 → {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigError(f"{path}: 顶层应为映射，实得 {type(data).__name__}")
    return data


def _check_coupling_masters(problems: list[str], axes: Mapping[str, Axis]) -> None:
    """ratio 耦合的 master 必须是 axes 表内已存在的轴 id（T03 卡步骤 4 校验用例）。

    放在 loader 而非 validate：它要等整张 axes 表建完才能判，属跨节校验。
    """
    for axis in axes.values():
        coupling = axis.coupling
        if coupling and coupling.type == "ratio" and coupling.master not in axes:
            problems.append(f"axes[{axis.id}].coupling.master: `{coupling.master}` "
                            f"不在 axes 表内")


# pack_profile 一致性校验覆盖的两个 NodeId 数组键 → 其数组长度在契约里的出处。
# G17 扩表后 axis_vel 与 axis_pos 同受约束（契约 §6.1 的 `Pos`／`Vel` 同为 ARRAY[0..7]）。
_PROFILE_ARRAY_NODES = (("axis_pos", "契约 §5.2 的 Pos[]"), ("axis_vel", "契约 §6.1 的 Vel[]"))


def _check_pack_profile(problems: list[str], opcua: OpcUa | None) -> None:
    """回读 axis_pos／axis_vel 节点数必须等于 pack_profile 对应的数组长度（契约 §5.2／§6.1）。

    与 _check_coupling_masters 同属跨字段一致性校验：单看节点表、单看 pack_profile 都合法，
    只有对着看才知道错——而这类错的后果是**下发／回读字节布局与 PLC 对不上**，故做成拒载，
    把 yaml 注释里那句「禁只改一边」变成机器判据。对照表记 None 的 profile（V1.3 未冻结）跳过。
    两键**分别**报，使只改了一边时消息直接点名是哪一张表，现场不必猜。
    """
    if opcua is None:
        return
    expected = PACK_PROFILE_AXIS_COUNT.get(opcua.pack_profile)
    if expected is None:
        return
    for key, clause in _PROFILE_ARRAY_NODES:
        count = len(opcua.read_nodes[key])
        if count != expected:
            problems.append(f"opcua.read_nodes.{key}: pack_profile={opcua.pack_profile} 应为 "
                            f"{expected} 个节点（{clause} 长度），实得 {count} 个"
                            f"——pack_profile 与节点表禁只改一边")


def _pending_warnings(axes: Mapping[str, Axis]) -> tuple[str, ...]:
    """pending 占位轴 → 告警文本（列出全部轴名，**不拒绝启动**；T03 卡步骤 2）。"""
    pending = [axis.id for axis in axes.values() if axis.pending]
    if not pending:
        return ()
    return (f"{len(pending)} 个轴标 pending: true（行程／零点／正方向待电气·机械回执，"
            f"当前为占位值，不得据此对外承诺）：{', '.join(pending)}",)


def load_machine(path: str) -> MachineConfig:
    """读取并强校验 machine.yaml，返回定型后的 MachineConfig。

    path：配置文件路径（现场为 config/machine.yaml）。校验不通过抛 ConfigError，消息按
    字段路径列**全部**问题项；`pending: true` 的轴只进 warnings 不拒绝启动。
    单位见各字段键名后缀（mm／deg／mm_s／mm_s2／ms），坐标系按 S-1 契约第 7 章。
    """
    data = _read_yaml(path)
    problems: list[str] = [f"缺必填节 `{name}`" for name in SECTIONS if name not in data]
    if problems:
        raise ConfigError(_format(path, problems))
    axes = axes_section(problems, data["axes"])
    machine = machine_section(problems, data["machine"])
    modes = modes_section(problems, data["modes"], axes)
    links = links_section(problems, data["links"])
    limits = limits_section(problems, data["limits"])
    opcua = opcua_section(problems, data["opcua"])
    paths = paths_section(problems, data["paths"])
    _check_coupling_masters(problems, axes)
    _check_pack_profile(problems, opcua)
    if problems:
        raise ConfigError(_format(path, problems))
    return MachineConfig(machine, axes, modes, links, limits, opcua, paths,
                         _pending_warnings(axes))
