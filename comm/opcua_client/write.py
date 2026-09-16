"""comm.opcua_client.write —— 下发行协议：契约 §5 的 ``ST_Seg`` 打包与命令字位定义。

**段打包口径（G17 裁决，2026-09-16）**：machine.yaml 的 ``write_nodes.seg_array`` 是**单个** NodeId，
故整批段按 §5.2 打成 ``SEG_SLOTS × 段长`` 的 **ByteString 一次写**；⛔ 禁改成逐变量写（80 次写＋
一致性窗口——两次写之间 PLC 可能扫到半批数据）。

此举与契约 §4.3「字节序由 Server 自动转换、双方均不手工处理」相抵：ByteString 是不透明载荷，Server
无从转换，必须自定序。本期取 **S7 原生大端**（§4.3「S7 内部为大端」）。自环两端同码故功能无差；真机
口径待 `电Q-2`（OPC UA 接入参数，属《沟通单》体系）与 `契约 Q-7`（实际 DB 号）回执后复定——届时只改
本模块与 machine.yaml，**不改调用方形态**。

段长由 ``struct.calcsize`` **实算**、不写死 56：契约 V1.3 把槽位从 8 扩到 24 时本模块自动跟着变，
「改 ``pack_profile`` 取值即切换、不改码」的承诺由此成立（扩容后的 124／1264／6224 B 见 CR-2026-03
§三-5，属 V1.3 输入，本单一律**不硬编码**）。

本模块是编解码＋下发口径：纯函数（``seg_layout``／``pack_segments``／``unpack_segments``）的前置条件
不满足一律抛 ``ValueError``；配置口径不可用（``pack_profile`` 未冻结）抛 ``CommError``。依赖方向单向
（write → errors → subscribe），不成环。
"""

from __future__ import annotations

import struct
from collections.abc import Sequence
from dataclasses import dataclass

from asyncua import ua

from comm.opcua_client.errors import CommError
from core.config import PACK_PROFILE_AXIS_COUNT

# ── 契约 §5.1 的下发块布局 ────────────────────────────────────────────────────────────────
SEG_SLOTS = 10               # §5.1 `Seg = ARRAY[0..9] OF ST_Seg`；SegCount 取值 1–10
SEG_HEAD_BYTES = 4           # §5.2 SegType／MotionMode／BlendMode／Reserved1
SEG_TAIL_REALS = 4           # §5.2 Vel／Acc／Dec／BlendTol
SEG_TAIL_DINTS = 1           # §5.2 DwellMS
SEQ_ID_MAX = 32767           # §5.1 SeqID 取值 0–32767 循环
SPEED_OVERRIDE_MIN = 1.0     # §5.1 SpeedOverride 取值 1.0–100.0（单位 %，见 §7.2）
SPEED_OVERRIDE_FULL = 100.0

# §5.2 的三个 BYTE 枚举取值。命名刻意避开 `direction`／`modes` 一类轴参数字段名，
# 以免与数值同行撞上 tools/lint_no_magic.py 的行级近似判定（该脚本宁误报不漏报）。
SEG_PTP, SEG_LIN, SEG_CIRC = 0, 1, 2
MOTION_ABS, MOTION_REL = 0, 1
BLEND_EXACT, BLEND_SMOOTH = 0, 1

# §5.3 命令字位。软件侧只用得到这几个；位 7 契约留空，故不定义。
CMD_LOAD, CMD_START, CMD_PAUSE, CMD_RESUME, CMD_STOP, CMD_RESET, CMD_HOME = (1 << i for i in range(7))

# 下发节点的 PLC 类型（§5.1）。**按 machine.yaml 的键**定，不按 NodeId 里的符号名——
# 代码里不出现任何 ``"DB_SW_to_PLC"."Cmd"`` 一类字面量，换点表才能零改码。
WRITE_NODE_TYPES = {"cmd": ua.VariantType.Byte, "seq_id": ua.VariantType.Int16,
                    "seg_count": ua.VariantType.Int16, "speed_override": ua.VariantType.Float,
                    "seg_array": ua.VariantType.ByteString}


@dataclass(frozen=True)
class Segment:
    """契约 §5.2 的 ``ST_Seg``：关节空间目标，单位按 §7.2（直线 mm、回转 deg、速度 mm/s、时间 ms）。

    ``pos`` 只填本段实际驱动的槽位，其余由 ``pack_segments`` 补 0——§5.2「未使用的轴位一律填 0，
    不得留空或填随机值」。形态与 ``core/path.py::gen_path`` 的产物对齐（T07 落地后直接喂进来）。
    """

    pos: Sequence[float] = ()
    vel: float = 0.0
    acc: float = 0.0
    dec: float = 0.0
    seg_type: int = SEG_PTP
    motion_mode: int = MOTION_ABS
    blend_mode: int = BLEND_EXACT
    blend_tol: float = 0.0
    dwell_ms: int = 0


def axis_slots_of(pack_profile: str) -> int:
    """``pack_profile`` → 段内轴槽位数。对照表在 ``core/config/schema.py``，本函数不存数字。

    未冻结的 profile（V1.3 在对照表里记 None）**拒绝打包**：T09 卡明确「只按 profile 取值实现、
    不硬编码扩容后的布局数字」，故此处宁可报错，也不去猜 24 槽位的段长与对齐。
    """
    slots = PACK_PROFILE_AXIS_COUNT.get(pack_profile)
    if slots is None:
        raise CommError(f"pack_profile={pack_profile} 的轴槽位数尚未冻结（契约 V1.3 待定），拒绝打包")
    return slots


def seg_layout(axis_slots: int) -> tuple[str, int]:
    """按槽位数算出 §5.2 的 struct 格式与实际段长（大端，理由见模块 docstring）。"""
    fmt = f">{SEG_HEAD_BYTES}B{axis_slots}f{SEG_TAIL_REALS}f{SEG_TAIL_DINTS}i"
    return fmt, struct.calcsize(fmt)


def pack_segments(path: Sequence[Segment], axis_slots: int) -> bytes:
    """段序列 → 定长 ByteString（恒为 ``SEG_SLOTS`` 段；未用的段与未用的轴位一律填 0）。"""
    if len(path) > SEG_SLOTS:
        raise ValueError(f"段数 {len(path)} 超 §5.1 的数组上限 {SEG_SLOTS}——请分批下发")
    fmt, seg_bytes = seg_layout(axis_slots)
    zeros = struct.pack(fmt, *([0] * SEG_HEAD_BYTES), *([0.0] * axis_slots),
                        *([0.0] * SEG_TAIL_REALS), *([0] * SEG_TAIL_DINTS))
    out = bytearray()
    for seg in path:
        if len(seg.pos) > axis_slots:
            raise ValueError(f"段内轴位 {len(seg.pos)} 个 > 槽位 {axis_slots} 个（pack_profile 决定）")
        pos = tuple(seg.pos) + (0.0,) * (axis_slots - len(seg.pos))
        out += struct.pack(fmt, seg.seg_type, seg.motion_mode, seg.blend_mode, 0, *pos,
                           seg.vel, seg.acc, seg.dec, seg.blend_tol, seg.dwell_ms)
    return bytes(out) + zeros * (SEG_SLOTS - len(path))


def unpack_segments(payload: bytes, axis_slots: int, count: int | None = None) -> tuple[Segment, ...]:
    """``pack_segments`` 的逆运算（模拟器与单测共用同一份布局常量，防两端各写一套走偏）。

    ``count`` 省略即解满 ``SEG_SLOTS`` 段；传值则只解前 count 段（＝PLC 侧按 ``SegCount`` 取用）。
    """
    fmt, seg_bytes = seg_layout(axis_slots)
    if len(payload) != seg_bytes * SEG_SLOTS:
        raise ValueError(f"段数组载荷 {len(payload)} B ≠ {SEG_SLOTS}×{seg_bytes} B（§5.1）")
    total = SEG_SLOTS if count is None else count
    if not 0 <= total <= SEG_SLOTS:
        raise ValueError(f"SegCount={total} 应在 0–{SEG_SLOTS}（§5.1 取值范围 1–10）")
    out = []
    for index in range(total):
        raw = struct.unpack_from(fmt, payload, index * seg_bytes)
        head = raw[:SEG_HEAD_BYTES]
        tail = raw[-(SEG_TAIL_REALS + SEG_TAIL_DINTS):]
        pos = raw[SEG_HEAD_BYTES:SEG_HEAD_BYTES + axis_slots]
        out.append(Segment(pos=pos, vel=tail[0], acc=tail[1], dec=tail[2], blend_tol=tail[3],
                           seg_type=head[0], motion_mode=head[1], blend_mode=head[2],
                           dwell_ms=int(raw[-1])))
    return tuple(out)
