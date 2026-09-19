"""tests.test_path_estimate —— `core.path.estimate_duration` 的守卫（T15 卡步骤 1 预声明增件）。

只测**估算函数**（纯函数）：空段／单段／混合段型／上界钳制／与 `gen_path.duration_s` 同口径。
时间轴与 KPI 的接线判据归 `tools/e2e_tabs.py`（真壳），⛔ 不在此重复。
"""

from __future__ import annotations

import dataclasses
import pathlib

from core.config import load_machine
from core.path import Segment, estimate_duration

LIMITS = load_machine(str(pathlib.Path("tests/fixtures/ok_minimal.yaml"))).limits


def _seg(length_mm: float, seg_type: str = "JOINT") -> Segment:
    """造一段定长的几何段（其余字段取中性值——本测试只消费 ``length_mm``／``type``）。"""
    return Segment(id=1, type=seg_type, start_name="A", end_name="B",
                   start_mm=(0.0, 0.0, 0.0), end_mm=(0.0, 0.0, 0.0),
                   length_mm=length_mm, speed_mm_s=0.0, duration_s=0.0,
                   joints_start={}, joints_end={}, blocked=False, reason="")


def test_empty_segments_estimate_zero():
    assert estimate_duration([], LIMITS) == 0.0


def test_single_point_segment_uses_rapid_speed():
    # 点位型走 speed_rapid_mm_s（经 speed_max_mm_s 钳制——fixture 的 rapid 300 > max 500 不触发钳制）
    speed = min(LIMITS.speed_rapid_mm_s, LIMITS.speed_max_mm_s)
    assert estimate_duration([_seg(300.0, "JOINT")], LIMITS) == 300.0 / speed


def test_contour_segment_uses_work_speed():
    speed = min(LIMITS.speed_work_mm_s, LIMITS.speed_max_mm_s)
    assert estimate_duration([_seg(100.0, "LINE")], LIMITS) == 100.0 / speed


def test_mixed_segment_types_sum_per_type():
    rapid = min(LIMITS.speed_rapid_mm_s, LIMITS.speed_max_mm_s)
    work = min(LIMITS.speed_work_mm_s, LIMITS.speed_max_mm_s)
    total = estimate_duration([_seg(300.0, "JOINT"), _seg(100.0, "LINE")], LIMITS)
    assert total == 300.0 / rapid + 100.0 / work


def test_speed_max_clamps_the_estimate():
    """把 rapid 抬过 speed_max ⇒ 估算按上界算（钳制口径与 ``gen_path`` 的 ``duration_s`` 一致）。"""
    clamped = dataclasses.replace(LIMITS, speed_rapid_mm_s=LIMITS.speed_max_mm_s * 10)
    assert estimate_duration([_seg(LIMITS.speed_max_mm_s, "JOINT")], clamped) == 1.0


def test_same_result_as_gen_path_durations():
    """与 ``summarize`` 的口径一致性：估算值恒等于逐段 ``duration_s`` 之和（同限速同段长）。"""
    rapid = min(LIMITS.speed_rapid_mm_s, LIMITS.speed_max_mm_s)
    seg = dataclasses.replace(_seg(240.0, "JOINT"), speed_mm_s=rapid,
                              duration_s=240.0 / rapid)
    assert estimate_duration([seg, seg], LIMITS) == 2 * 240.0 / rapid


def test_unknown_kind_is_rejected_upstream():
    """段型只有 JOINT/LINE 两种（`_SEG_TYPE` 的值域）⇒ 传别的当场 KeyError，⛔ 不静默当零。"""
    try:
        estimate_duration([_seg(10.0, "CIRC")], LIMITS)
    except KeyError:
        return
    raise AssertionError("未知段型应当场报错而不是被吞掉")
