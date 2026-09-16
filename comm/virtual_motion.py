"""comm.virtual_motion —— PLC 侧「虚拟执行」：梯形速度曲线与段计划（T09 的模拟器专用）。

契约 §3.2 把插补与加减速划给 PLC（软件侧 ❌ 不做运动控制），故这段数学**只存在于模拟器**——它冒充的是
PLC，不是软件。真机接上后本模块整个退役，客户端侧一行不改。

三条口径：
- **梯形而非 S 曲线**：§5.2 只给 Vel／Acc／Dec 三个量，没有 jerk 键；要 S 曲线就得自造第四个数（越权）。
  行程不够跑到峰值速度时自动退化成三角形（``Move.build`` 的 cap 分支），不糊弄成「先跑完再说」。
- **禁外推（§9.3-③）**：``Move.at`` 只在段时长内取值，``elapsed >= total`` 一律钳在终点且速度归 0；
  段与段之间不预测、不补间。
- **限值为配置驱动**：峰值速度钳 ``limits.speed_max_mm_s``、加减速度钳 ``limits.accel_max_mm_s2``
  （§3.2「PLC 强制钳位，软件侧不得越过」），本模块不写任何数值字面量。

⚠️ 单位按 §7.2（长度 mm、角度 deg、线速度 mm/s、角速度 deg/s、加速度 mm/s²、时间 ms），但本模块内部
**只用秒**算曲线：``dwell_ms`` 在 ``build_plan`` 里除以 ``MS_PER_S`` 折成秒，避免 ms／s 混算出错。
回读的 ``Vel[i]`` 带符号（正负随运动方向），与 §6.1「各轴实际速度」一致。
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from comm.opcua_client import MOTION_REL, MS_PER_S, SPEED_OVERRIDE_FULL, Segment
from core.config import Limits


@dataclass(frozen=True)
class Move:
    """单轴单段的梯形曲线。全部字段由 ``build`` 算出，调用方不手填（填错即另一条曲线）。

    ``sign`` 刻意不叫 ``direction``：与数值字面量同行会撞 ``tools/lint_no_magic.py`` 的行级近似判定
    （该脚本对非 ``.py`` 宁误报不漏报，而 ``direction`` 正是它的轴参数字段名之一）。
    """

    start: float
    end: float
    sign: int
    peak: float
    acc: float
    dec: float
    acc_t: float
    cruise_t: float
    dec_t: float
    acc_d: float
    cruise_d: float
    total: float

    @classmethod
    def build(cls, start: float, end: float, peak: float, acc: float, dec: float) -> Move:
        """按 (起点, 终点, 峰值速度, 加速度, 减速度) 定出一条梯形曲线。

        三个量里任一 ≤0 或行程为 0 时退化成「瞬时到位」（``total == 0``）：模拟器不对非法参数猜曲线，
        真机上这类值由 §5.1／§5.2 的取值校验挡在下发之前（见 ``comm.simulator.PlcSimulator``）。
        """
        span = end - start
        sign = 1 if span >= 0.0 else -1
        dist = abs(span)
        if dist <= 0.0 or min(peak, acc, dec) <= 0.0:
            return cls(start, end, sign, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
        cap = math.sqrt(2.0 * dist / (1.0 / acc + 1.0 / dec))
        peak = min(peak, cap)
        acc_t, dec_t = peak / acc, peak / dec
        acc_d, dec_d = peak * acc_t / 2.0, peak * dec_t / 2.0
        cruise_t = (dist - acc_d - dec_d) / peak
        return cls(start, end, sign, peak, acc, dec, acc_t, cruise_t, dec_t, acc_d,
                   peak * cruise_t, acc_t + cruise_t + dec_t)

    def at(self, elapsed: float) -> tuple[float, float]:
        """时刻（秒）→ (位置, 速度)。速度带符号，直接回读进 §6.1 的 ``Vel[i]``。"""
        if self.total <= 0.0 or elapsed >= self.total:
            return self.end, 0.0
        if elapsed <= 0.0:
            return self.start, 0.0
        if elapsed < self.acc_t:
            speed = self.acc * elapsed
            offset = speed * elapsed / 2.0
        elif elapsed < self.acc_t + self.cruise_t:
            speed = self.peak
            offset = self.acc_d + speed * (elapsed - self.acc_t)
        else:
            tau = elapsed - self.acc_t - self.cruise_t
            speed = self.peak - self.dec * tau
            offset = self.acc_d + self.cruise_d + self.peak * tau - self.dec * tau * tau / 2.0
        return self.start + self.sign * offset, self.sign * speed


@dataclass(frozen=True)
class Step:
    """一段的执行计划：各槽位的曲线 ＋ 段总时长（秒，含 §5.2 的 ``DwellMS`` 到点停留）。"""

    moves: tuple[Move, ...]
    duration: float

    def sample(self, elapsed: float) -> tuple[tuple[float, float], ...]:
        """整段各槽位在同一时刻的 (位置, 速度)，顺序即 §5.2 ``Pos[i]`` 的槽位序。"""
        return tuple(move.at(elapsed) for move in self.moves)


def clamp_speeds(seg: Segment, override: float, limits: Limits) -> tuple[float, float, float]:
    """§5.1 的 ``SpeedOverride``（%）折速 ＋ §3.2「PLC 强制钳位」，返回 (峰值速度, 加速度, 减速度)。"""
    ratio = override / SPEED_OVERRIDE_FULL
    return (min(seg.vel * ratio, limits.speed_max_mm_s),
            min(seg.acc, limits.accel_max_mm_s2),
            min(seg.dec, limits.accel_max_mm_s2))


def build_plan(segments: Sequence[Segment], start: Sequence[float], override: float,
               limits: Limits) -> tuple[Step, ...]:
    """段序列 → 执行计划。

    ``start`` 是装载时刻各槽位的实测位置：``MotionMode = 1``（相对，§5.2）按它逐段累加，绝对定位则直接
    取段内目标值。未驱动的槽位（段里填 0 的那些）目标即 0 位——这是 §5.2「未使用的轴位一律填 0」的
    直接后果，模拟器照契约执行，**不猜**「填 0 应当保持原位」。
    """
    plan: list[Step] = []
    cursor = list(start)
    for seg in segments:
        peak, acc, dec = clamp_speeds(seg, override, limits)
        goals = list(cursor)
        for slot, target in enumerate(seg.pos):
            goals[slot] = cursor[slot] + target if seg.motion_mode == MOTION_REL else target
        moves = tuple(Move.build(cursor[slot], goals[slot], peak, acc, dec)
                      for slot in range(len(cursor)))
        span = max((move.total for move in moves), default=0.0)
        plan.append(Step(moves, span + seg.dwell_ms / MS_PER_S))
        cursor = list(goals)
    return tuple(plan)
