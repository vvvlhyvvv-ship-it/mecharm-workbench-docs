"""app.sendseg —— 几何段（`core.path.Segment`）→ 下发段（`comm.opcua_client.write.Segment`）的适配层。

**为什么单列一个文件**：`core/path.py` 的 `Segment` 与 `comm` 的 `Segment` 是**同名异义**（前者几何段、
后者契约 §5.2 的 `ST_Seg`），且 T07 明令「⛔ 两者禁互引、禁合并；下发时的适配属 T08／T10」。本件就是那
个适配处：单向 `core.path → comm`，⛔ 不反向 import、⛔ 不在 core／comm 任何一侧塞对方的形状。
壳侧控制器（`app/sendctl.py`）只调本件的纯函数，故本件**不含任何 Qt 依赖**（可离屏单测、可被 e2e 复用）。

⚠️ **一处数据缺口（不是本层能定的，已登记为 T10 遗留问题）**：`Pos[i]` 槽位 ↔ `machine.yaml` 轴 id 的
映射，`comm/simulator.py` 与 `comm/plc_logic.py` 都写明「待 `附录 A`／`契约 Q-11` 回执，自造映射即越权」。
但不定映射就一步也走不动，故本件取**可自证的最小约定**并集中在一处（`slot_axes`）：

    槽位 i ← 当前工作模式在 `modes:` 表里声明的**第 i 根轨迹级轴**（声明序，⛔ 不重排、⛔ 不写死轴 id）

写下发块与解回读帧**共用这一个函数**，故自环下「写进去的槽位」与「读回来的槽位」必然是同一根轴。
真机口径以回执为准：回执到后只改 `slot_axes`（或改成从配置读一张映射表），本件其余部分与调用方都不动。
轴数超过槽位数时**人话拒绝并点名放不下的轴** ⛔ 不静默截断（截断＝让 PLC 少动一根轴而界面上看不出来，
属 04 §5.5 附7-③「掏空下游契约」那一族）。

⚠️ **回读语义假设**（同属上述缺口的另一半）：本层把回读值当作**与下发同语义的量**，即 `fk` 的关节输入
口径——`ratio` 自指轴（X3 三级筒）是**驱动位移**、不是工程位置（见 `core.kinematics.fk.resolve_positions`）。
模拟器自环下二者天然一致（PLC 侧就是把 `Pos[i]` 推向我们写的目标值）。真机若回读三级筒**工程位置**
（`契约 Q-10`／踏勘第 4 项待回执），须在 `app/livectl.py::_joint_of` 补一次除以 ratio，⛔ 现在不猜。
"""

from __future__ import annotations

from collections.abc import Sequence

from comm.opcua_client import (BLEND_EXACT, BLEND_SMOOTH, MOTION_ABS, SEG_LIN, SEG_PTP, SEG_SLOTS,
                               SPEED_OVERRIDE_FULL, axis_slots_of, seg_layout)
from comm.opcua_client.write import Segment as CommSegment
from core.collision import mode_axes
from core.config.schema import Axis, MachineConfig
from core.kinematics.fk import raw_to_eng
from core.path import Segment

# 段型字面（03 §3 的 JOINT／LINE）→ 契约 §5.2 的 SegType 取值。CIRC 是能力上限、本期 core 不产出。
_SEG_TYPE = {"JOINT": SEG_PTP, "LINE": SEG_LIN}
_MM = "mm"          # 单位只在人话里出现一次，避免逐行重复字面量（02 §4「单位标注一次」同源纪律）


class SendSegError(Exception):
    """适配失败：消息**本身就是人话**（含轴号／数值／下一步动作），调用方可直上屏 ⛔ 不改写。"""


def slot_axes(cfg: MachineConfig, mode_name: str) -> tuple[str, ...]:
    """当前工作模式 → 下发块 `Pos[i]` 的槽位轴序（写与读共用，见模块 docstring 的约定与缺口说明）。

    轴序取自 `machine.yaml` 的 `modes:` 声明序（经 `core.collision.mode_axes`，⛔ 本件不写死轴 id）；
    槽位数取自 `pack_profile`（经 `comm` 的对照表，V1.3 未冻结即拒打包）。三种不成立都人话报错。
    """
    axes = mode_axes(cfg, mode_name)
    if not axes:
        raise SendSegError(
            f"工作模式「{mode_name or '未选定'}」在 machine.yaml 的 modes 表里没有唯一命中行，"
            f"无法确定本次下发用哪几根轴——⛔ 不猜轴子集，请先在顶栏选定工作模式")
    slots = axis_slots_of(cfg.opcua.pack_profile)
    if len(axes) > slots:
        raise SendSegError(
            f"工作模式「{mode_name}」的轨迹轴有 {len(axes)} 根，超过下发段槽位 {slots} 个"
            f"（machine.yaml 的 pack_profile={cfg.opcua.pack_profile}）："
            f"{'、'.join(axes[slots:])} 无处安放。⛔ 不静默丢弃——请改用轴数不超过 {slots} 的模式，"
            f"或等契约 V1.3 把槽位扩到 24（该档尚未冻结，见 core/config/schema.py 的对照表）")
    return axes


def eng_to_raw(axis: Axis, eng: float) -> float:
    """工程值 → PLC 原始计数：`core.kinematics.fk.raw_to_eng` 的**代数逆**。

    正向（fk.py，契约 §7.4）＝ ``eng = raw × scale × 正负号 − zero_offset``，故逆向＝
    ``raw = (eng + zero_offset) / (scale × 正负号)``。`scale` 为 null＝回读已是工程值（03 §4）⇒
    按 1.0 处理，与正向同一口径。

    ⚠️ 标定四要素（规程 W-7.2）现场实测前本换算**恒等**（22 轴全为占位：scale null、零点 0、
    正方向 +1）；⛔ 不因此省掉它——回执填上真值后，正向回读与反向下发必须**同时**生效，漏一边就变成
    「写进去的和读回来的不是一套数」，而这类错在自环里看不出来（自环两端同一份占位）。
    本函数属 T10 的适配层；回执后应与 `raw_to_eng` 同处 `core/kinematics`（fk.py 对本单只读，故未迁）。
    """
    scale = 1.0 if axis.scale is None else axis.scale
    gain = scale * axis.direction
    if gain == 0.0:
        raise SendSegError(f"轴 {axis.id} 的标定增益为零（scale={axis.scale}、"
                           f"direction={axis.direction}），工程值折不回原始计数——⛔ 不猜、不填零")
    return (eng + axis.zero_offset) / gain


def build_segments(segments: Sequence[Segment], cfg: MachineConfig,
                   mode_name: str) -> tuple[CommSegment, ...]:
    """几何段序列 → 下发段序列（契约 §5.2 的 `ST_Seg` 元组，可直接喂 `Session.write_segments`）。

    四道前置检查，任一不过即 `SendSegError`（人话）⛔ 不产出半份下发块：
      ① 段数在 §5.1 的 1–`SEG_SLOTS` 内（超了＝须分批下发，本单未交付分批，故人话拒绝）；
      ② 无 `blocked` 段（`core.path` 判不可达的段 ⛔ 不得下发；这是 `app/checkctl.py` 双阻断之外的
         第三道，属**数据形状**防线：调用方拿错段序列也不会把不可达段发出去）；
      ③ 槽位映射成立（`slot_axes`）；④ 段型认得（`_SEG_TYPE`）。
    """
    if not segments:
        raise SendSegError("没有可下发的段：先在步骤③点[生成路径]")
    if len(segments) > SEG_SLOTS:
        raise SendSegError(
            f"本次路径 {len(segments)} 段，超过下发块一次能装的 {SEG_SLOTS} 段（契约 §5.1 的 "
            f"Seg=ARRAY[0..{SEG_SLOTS - 1}]）——请减少点位或分批下发；⛔ 本层不自行截断")
    axes = slot_axes(cfg, mode_name)
    out: list[CommSegment] = []
    for seg in segments:
        if seg.blocked:
            raise SendSegError(f"第 {seg.id} 段不可达（{seg.reason}）——⛔ 不得下发，请回步骤③改点位")
        out.append(_one(seg, cfg, axes))
    return tuple(out)


def _one(seg: Segment, cfg: MachineConfig, axes: Sequence[str]) -> CommSegment:
    """单段适配。速度取该段已算好的值（`core.path` 已按 `limits` 选速并经 `speed_max_mm_s` 钳制），
    加减速取 `limits.accel_max_mm_s2`（§3.2「PLC 强制钳位」，模拟器侧同一键再钳一次）。

    `blend_tol`／`dwell_ms` 恒零：`machine.yaml` 的 `limits` 无对应键、且该文件对本单只读 ⇒ **无配置源**，
    ⛔ 不自造数值。零与当前口径自洽——`blending` 在 `电Q-8` 回执前恒 False（见 `core/path.py` docstring），
    故 `blend_mode` 恒 `BLEND_EXACT`（到点精确停）、段间不停留。回执后须同时补 limits 键与此处取值。
    """
    return CommSegment(pos=_pos_of(seg, cfg, axes), vel=seg.speed_mm_s,
                       acc=cfg.limits.accel_max_mm_s2, dec=cfg.limits.accel_max_mm_s2,
                       seg_type=_seg_type(seg), motion_mode=MOTION_ABS,
                       blend_mode=BLEND_SMOOTH if seg.blending else BLEND_EXACT,
                       blend_tol=0.0, dwell_ms=0)


def _seg_type(seg: Segment) -> int:
    """段型字面 → §5.2 的 SegType 取值；认不得即人话报错 ⛔ 不按 PTP 兜底（那会改掉运动语义）。"""
    try:
        return _SEG_TYPE[seg.type]
    except KeyError:
        raise SendSegError(f"第 {seg.id} 段的段型 {seg.type!r} 不在本层认得的 "
                           f"{sorted(_SEG_TYPE)} 内——⛔ 不按点位型兜底") from None


def _pos_of(seg: Segment, cfg: MachineConfig, axes: Sequence[str]) -> tuple[float, ...]:
    """段的 `Pos[i]` 槽位值＝**段终点**的关节目标折成原始计数（绝对定位，段内插补归 PLC，契约 §3.2）。

    本模式声明了、但**不在驱动链上**的轴（如打磨臂专用轴 ZA1／RA：`links:` 表里没有它们的连杆）在
    `joints_end` 里没有值 ⇒ 按 §5.2「未使用的轴位一律填 0」填零。⚠️ 填零在**绝对定位**下的语义是
    「该轴走到 0 位」、不是「保持原位」（`comm/virtual_motion.py::build_plan` 明写它照契约执行、不猜）；
    真机下发前须由电气侧确认这些轴的 0 位是安全停放位，已登记为 T10 遗留问题。
    """
    out: list[float] = []
    for axis_id in axes:
        value = seg.joints_end.get(axis_id)
        out.append(0.0 if value is None else eng_to_raw(cfg.axes[axis_id], value))
    return tuple(out)


def describe_request(segments: Sequence[CommSegment], cfg: MachineConfig, mode_name: str,
                     override: float, endpoint: str) -> str:
    """确认弹窗里的**请求值小字**（卡片步骤①）：把真要写进 PLC 的数逐条摊开给操作员核。

    全人话、单位标注一次（02 §4）；每段一行、槽位值按 `machine.yaml` 的轴名点名 ⇒ 操作员看得见
    「哪根轴被要求走到多少」。⛔ 不做任何取整以外的加工：显示的就是 `pack_segments` 要打出去的数。

    ⚠️ 段长按 **`pack_profile` 的槽位数**算、⛔ 不按本模式声明的轴数：`pack_segments` 会把 `pos` 补零到
    槽位数（§5.2「未使用的轴位一律填 0」），用轴数算就会报出比真实载荷小的字节数（7 轴模式下 52 B vs 56 B），
    而弹窗里的数必须是真写出去的那份。补零的那几个槽位单独说明一行，免得操作员数不对。

    ⚠️ **槽位值一律不带 `mm`**：那是 `eng_to_raw` 折出来的 PLC **原始计数**（契约 §7.4 的反向），只在标定
    四要素还是占位（scale null／零点 0）时才与工程值同数；真机回执填上比例与零点后仍标 mm 就等于让操作员按
    错的单位核数。速度是真 mm/s（§7.2，不经标定折算）⇒ 单位只标在它上面，并在小字里写明这一区分。
    """
    axes = slot_axes(cfg, mode_name)
    slots = axis_slots_of(cfg.opcua.pack_profile)
    _, seg_bytes = seg_layout(slots)
    pairs = "、".join(f"{i + 1}={a}" for i, a in enumerate(axes))
    lines = [f"端点：{endpoint}",
             f"下发块：{len(segments)} 段 × {slots} 槽位 × {seg_bytes} B"
             f"（实写 {len(segments) * seg_bytes} B，整块再按契约补足 {SEG_SLOTS} 段的定长）",
             f"速度倍率：{override:g} %（PLC 有权再钳位，§3.2）",
             f"槽位↔轴（按配置里该工作模式的声明序）：{pairs}",
             f"槽位值＝写给 PLC 的原始计数（标定四要素为占位时与工程值同数）；速度单位 {_MM}/s"]
    if slots > len(axes):
        first = len(axes) + 1
        span = f"第 {first}–{slots}" if slots > first else f"第 {slots}"
        lines.append(f"{span} 槽位本模式没有声明轴，按契约 §5.2 一律填零")
    for index, seg in enumerate(segments, start=1):
        asks = " ".join(f"{axis}={value:g}" for axis, value in zip(axes, seg.pos))
        lines.append(f"第 {index} 段 类型{seg.seg_type} 速度 {seg.vel:g} {_MM}/s → {asks}")
    return "\n".join(lines)
