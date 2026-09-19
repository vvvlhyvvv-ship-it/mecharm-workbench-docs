"""core.process —— 工步编排与变量映射纯函数层（T17；蓝图 §6.3，演示稿画面 05/09）。

**用途声明**（蓝图 §6.3，界面三串读 ui.yaml）：本输出是**供电气 PLC 编程使用的工步数据与
变量映射**（数据交接物），不是我方交付的 PLC 程序——主要动作由 PLC 编程（03 §4「职责边界」），
本模块只是把已生成路径整理成 PLC 侧可对照的表格。**纯离线输出**：⛔ 不 import comm、
无任何界面框架依赖（GUI-free，收单核）、⛔ 不碰任何通讯。

口径（与卡片逐条对应）：
  · ``build_steps`` 只认 ``core.path.Segment``（T15 域，只读其段结构）；速度来源＝按轨迹算得
    （段速度，``gen_path`` 已按 ``limits`` 钳制）或字典上限（调用方传 ``machine.yaml`` 的
    ``limits.speed_max_mm_s``，⛔ 本模块不写死数值）。编排＝按运动段合并（默认）／逐点（不合并）。
  · ``variable_map`` **只映射 machine.yaml 点表的真实 NodeId**（读＋写节点各一行）；⛔ 禁造
    MasterLink／``J*.Command`` 等字典字样（Δ-5，DEC-04 未决）。回读 ``Pos[i]``／``Vel[i]``
    与轴的对应＝``MachineConfig.axes`` 的插入序（03 §3「序即契约 Pos[] 排法」），配置驱动。
  · ``budget`` 的上限由调用方从 ``config/ui.yaml`` 的 ``process_step_budget`` 读（T12 建）；
    超预算返回 used>limit 由 UI 黄警示、**不禁导出**（如实呈现）。
  · 备注列凡速度推算处固定「估算值」（口径铁律 2）；不可达段如实标注，⛔ 不标实测。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from core.config.schema import UNIT_BY_TYPE
from core.path import Segment

if TYPE_CHECKING:  # 只取类型：本模块运行期只依赖 core.path／core.config.schema
    from core.config.schema import MachineConfig

MODE_BY_SEGMENT = "by_segment"      # 按运动段合并（默认：每运动段一工步）
MODE_BY_POINT = "by_point"          # 逐点（不合并：每个目标点位一工步）
MODES = (MODE_BY_SEGMENT, MODE_BY_POINT)
SPEED_BY_PATH = "by_path"           # 速度来源＝按轨迹算得（段速度）
SPEED_BY_DICT = "by_dict"           # 速度来源＝字典上限（limits.speed_max_mm_s）
SPEED_SOURCES = (SPEED_BY_PATH, SPEED_BY_DICT)
# 编排取值的上屏中文（单一真值在 core，app 侧只投影——先例＝core.path 的 KINDS）
MODE_TEXT = {MODE_BY_SEGMENT: "按运动段合并", MODE_BY_POINT: "逐点（不合并）"}
SPEED_TEXT = {SPEED_BY_PATH: "按轨迹算得", SPEED_BY_DICT: "字典上限"}

NOTE_ESTIMATE = "估算值"             # 备注列的固定口径（速度为推算值，⛔ 禁标实测）
NOTE_BLOCKED = "⛔ 不可达（须重新生成）"
ACTION_BY_TYPE = {"JOINT": "空程移动", "LINE": "直线作业"}   # 段型 → 动作名（工艺动作口径等 TBD-11，期 3）

STEPS_HEAD = ("工步", "段号", "动作", "X(mm)", "Y(mm)", "Z(mm)", "速度(mm/s)",
              "ProcessStep", "OPC UA 变量", "备注")
VARS_HEAD = ("方向", "变量", "NodeId", "关联轴", "单位", "说明")


@dataclass(frozen=True)
class ProcessStep:
    """一行工步数据（PLC 编程对照用）。``pos_mm``＝段端点（模型坐标系 mm，与点位表同源）；
    ``speed_mm_s``＝该工步速度（mm/s，按 ``speed_source`` 取段速度或字典上限）；``process_step``
    ＝ProcessStep 序号（自 ``start_no`` 起连续编号，预算上限另见 ``budget``）；``variable``＝
    本工步经哪个真实点表节点下发（契约 §5.2 段数组节点，全表同源，⛔ 禁造字典变量名）。"""

    no: int                      # 工步号（1-based 行序）
    seg_no: int                  # 段号（＝core.path.Segment.id，与轨迹清单同源）
    action: str                  # 动作名（段型推导；工艺动作层未决前如实按段型称呼）
    pos_mm: tuple[float, float, float]
    speed_mm_s: float
    process_step: int
    variable: str
    note: str


@dataclass(frozen=True)
class VarRow:
    """一行变量映射（点表真实 NodeId 的交接清单）。``axis``＝回读 Pos/Vel 槽位对应的轴 id
    （按 axes 插入序；无对应轴为 None）；``unit`` 取轴型单位（mm/deg），无轴为「—」。"""

    direction: str               # 回读｜下发
    name: str                    # 契约符号名（从 NodeId 解析，非本模块发明）
    node_id: str
    axis: str | None
    unit: str
    note: str


def build_steps(segments: list[Segment], mode: str, start_no: int, speed_source: str,
                speed_max_mm_s: float, seg_node_id: str) -> list[ProcessStep]:
    """段序列 → 工步序列。``start_no``＝ProcessStep 起始序号（工步号恒从 1 连续）。

    ``mode``＝按运动段合并（每段一工步）／逐点（首段起点＋各段终点各一工步）；``speed_source``
    ＝按轨迹算得（段速度）或字典上限（``speed_max_mm_s``，由调用方从 ``machine.yaml`` 读）；
    ``seg_node_id``＝点表里段数组的真实 NodeId（工步统一经该节点下发，契约 §5.2）。
    空路径返回空表（调用方提示，⛔ 不造工步）；不可达段照编排、备注如实标注。
    """
    if mode not in MODES:
        raise ValueError(f"mode 应为 {MODES} 之一，实得 {mode!r}")
    if speed_source not in SPEED_SOURCES:
        raise ValueError(f"speed_source 应为 {SPEED_SOURCES} 之一，实得 {speed_source!r}")
    if not segments:
        return []
    rows: list[tuple[Segment, tuple[float, float, float]]] = []
    if mode == MODE_BY_SEGMENT:
        rows = [(seg, seg.end_mm) for seg in segments]
    else:
        rows = [(segments[0], segments[0].start_mm)]
        rows += [(seg, seg.end_mm) for seg in segments]
    numbers = range(start_no, start_no + len(rows))   # ProcessStep 连续编号（工步起始 ⇒ 起算号）
    return [_row(no, seg, pos, step_no, speed_source, speed_max_mm_s, seg_node_id)
            for no, ((seg, pos), step_no) in enumerate(zip(rows, numbers), start=1)]


def _row(no: int, seg: Segment, pos_mm, process_step: int, speed_source: str,
         speed_max_mm_s: float, seg_node_id: str) -> ProcessStep:
    """单行工步：速度按来源取值、备注按可达性如实标注。"""
    speed = speed_max_mm_s if speed_source == SPEED_BY_DICT else seg.speed_mm_s
    note = NOTE_BLOCKED if seg.blocked else NOTE_ESTIMATE
    return ProcessStep(no=no, seg_no=seg.id, action=ACTION_BY_TYPE.get(seg.type, seg.type),
                       pos_mm=pos_mm, speed_mm_s=speed, process_step=process_step,
                       variable=seg_node_id, note=note)


def variable_map(machine_cfg: MachineConfig) -> list[VarRow]:
    """机台配置 → 变量映射（读＋写节点各一行，NodeId 逐字取自点表）。

    ``Pos[i]``／``Vel[i]`` 的关联轴＝``axes`` 插入序第 i 根（MachineConfig docstring「序即契约
    Pos[] 排法」）；超出轴表覆盖的槽位关联轴记 None。单位按轴型（schema.UNIT_BY_TYPE），
    回转轴速度单位 deg/s。符号名从 NodeId 原文解析（解析不出时退回 yaml 键名，禁造名）。
    """
    nodes: list[VarRow] = []
    axes_order = list(machine_cfg.axes)
    read_notes = {"status": "状态字（位域）", "heartbeat": "心跳计数", "ack": "应答字（握手）",
                  "alarm_word": "报警字（位域）", "seq_id": "批次号（回显）", "cur_seg": "当前段号"}
    for key, value in machine_cfg.opcua.read_nodes.items():
        items = value if isinstance(value, (list, tuple)) else [value]
        for index, node_id in enumerate(items):
            axis = (axes_order[index] if key in ("axis_pos", "axis_vel")
                    and index < len(axes_order) else None)
            nodes.append(VarRow(
                direction="回读", name=_symbol(node_id, key, index), node_id=str(node_id),
                axis=axis, unit=_axis_unit(machine_cfg, axis, key),
                note=_read_note(machine_cfg, axis, key, read_notes)))
    write_notes = {"cmd": "命令字（脉冲式，写后清零）", "seq_id": "批次号", "seg_count": "本批段数",
                   "speed_override": "速度倍率（%）", "seg_array": "段数组（批量写入，工步经此下发）"}
    for key, node_id in machine_cfg.opcua.write_nodes.items():
        nodes.append(VarRow(direction="下发", name=_symbol(node_id, key), node_id=str(node_id),
                            axis=None, unit="—" if key != "speed_override" else "%",
                            note=write_notes.get(key, "")))
    return nodes


def budget(steps: list[ProcessStep], limit: int) -> tuple[int, int]:
    """工步序列 → (已用, 上限)。``limit`` 由调用方读 ``config/ui.yaml`` 的 ``process_step_budget``
    （⛔ 本模块不写死）；used>limit 时由 UI 黄警示、不禁导出（如实呈现）。"""
    return len(steps), int(limit)


def steps_to_csv(steps: list[ProcessStep]) -> str:
    """工步序列 → CSV 文本（表头＝STEPS_HEAD 十列；坐标 .3f 与点位表同口径；BOM 由写盘侧
    以 ``utf-8-sig`` 加，本函数只出正文）。"""
    lines = [",".join(STEPS_HEAD)]
    for step in steps:
        x, y, z = step.pos_mm
        lines.append(f"{step.no},{step.seg_no},{step.action},{x:.3f},{y:.3f},{z:.3f},"
                     f"{step.speed_mm_s:g},{step.process_step},{step.variable},{step.note}")
    return "\n".join(lines) + "\n"


def vars_to_csv(rows: list[VarRow]) -> str:
    """变量映射 → CSV 文本（表头＝VARS_HEAD 六列；NodeId 含逗号风险＝0：NodeId 语法无逗号，
    值内不再加引号转义——与工程内其余 CSV 同一口径）。"""
    lines = [",".join(VARS_HEAD)]
    for row in rows:
        axis = row.axis if row.axis is not None else "—"
        lines.append(f"{row.direction},{row.name},{row.node_id},{axis},{row.unit},{row.note}")
    return "\n".join(lines) + "\n"


# --- 内部辅助 ---------------------------------------------------------------------------- #
def _symbol(node_id: object, key: str, index: int | None = None) -> str:
    """从 NodeId 原文解析契约符号名（``ns=3;s="DB"."Pos[0]"`` → ``DB.Pos[0]``）；解析不出时
    退回 yaml 键名（数组槽位加 [i]），⛔ 不发明点表里没有的名字。"""
    text = str(node_id)
    marker = 's="'
    head = text.find(marker)
    if head >= 0:
        tail = text.rfind('"')
        if tail > head:
            return text[head + len(marker):tail].replace('"."', ".")
    return f"{key}[{index}]" if index is not None else key


def _axis_of(machine_cfg: MachineConfig, axis_id: str | None):
    """轴 id → Axis（关联轴不在表内时 None；调用方已按插入序对齐，正常恒命中）。"""
    return machine_cfg.axes.get(axis_id) if axis_id else None


def _axis_unit(machine_cfg: MachineConfig, axis_id: str | None, key: str) -> str:
    """单位：Pos/Vel 按关联轴型（mm/deg，速度另加 /s）；无关联轴或其余节点恒「—」。
    倍率节点的单位是 %（契约 §5.1 SpeedOverride）。"""
    if key == "speed_override":
        return "%"
    axis = _axis_of(machine_cfg, axis_id)
    if axis is None or key not in ("axis_pos", "axis_vel"):
        return "—"
    unit = UNIT_BY_TYPE.get(axis.type, "—")
    return f"{unit}/s" if key == "axis_vel" else unit


def _read_note(machine_cfg: MachineConfig, axis_id: str | None, key: str,
               scalar_notes: dict[str, str]) -> str:
    """回读行的说明：Pos/Vel 标工程值口径与待回执状态（轴 pending 是 yaml 真字段）；其余按
    契约 §6.1 字段语义。无关联轴的 Pos/Vel 槽位＝点表未收该轴回读，如实标注。"""
    if key in ("axis_pos", "axis_vel"):
        axis = _axis_of(machine_cfg, axis_id)
        if axis is None:
            return "点表未收该槽位的轴对应（如实占位）"
        parts = ["工程值回读" if axis.scale is None else "原始值回读（经换算）"]
        if axis.pending:
            parts.append("行程/零点待回执")
        return "；".join(parts)
    return scalar_notes.get(key, "")
