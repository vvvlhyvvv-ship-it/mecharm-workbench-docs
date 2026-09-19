"""tests/test_process.py —— core.process 工步编排与变量映射的纯函数用例（T17 卡步骤 1）。

用例面＝卡片点名的「空路径／单段／多段／逐点／超预算」＋速度来源两路＋variable_map 的
「只映射真实 NodeId／禁造字典字样（Δ-5）」＋CSV 表头。配置一律现场 load_machine（真交付物，
⛔ 不在测试里复写轴参数）；段样例手工构造 ``core.path.Segment``（段结构只读，不调 gen_path——
本单测编排层，不重复 T07 的生成用例）。
"""

from __future__ import annotations

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.config import load_machine
from core.path import Segment
from core.process import (MODES, SPEED_SOURCES, SPEED_BY_DICT, SPEED_BY_PATH, STEPS_HEAD,
                          VARS_HEAD, budget, build_steps, steps_to_csv, variable_map,
                          vars_to_csv, MODE_BY_POINT, MODE_BY_SEGMENT)

REPO = pathlib.Path(__file__).resolve().parents[1]
SEG_NODE = 'ns=3;s="DB_SW_to_PLC"."Seg"'


def _seg(seg_id: int, end=(100.0, 0.0, 0.0), blocked: bool = False) -> Segment:
    """单段样例：P0→Pend 直线作业段（速度 50 mm/s＝machine.yaml 的 speed_work 同量级示意值，
    仅作段结构夹具、非机台参数——机台参数一律经 cfg 现读）。"""
    return Segment(id=seg_id, type="LINE", start_name=f"P{seg_id}", end_name=f"P{seg_id + 1}",
                   start_mm=(0.0, 0.0, 0.0), end_mm=end, length_mm=100.0, speed_mm_s=50.0,
                   duration_s=2.0, joints_start={}, joints_end={}, blocked=blocked, reason="")


@pytest.fixture(scope="module")
def cfg():
    return load_machine(str(REPO / "config" / "machine.yaml"))


def test_empty_path_yields_no_steps() -> None:
    assert build_steps([], MODE_BY_SEGMENT, 1, SPEED_BY_PATH, 500.0, SEG_NODE) == []


def test_single_segment_by_default_mode(cfg) -> None:
    steps = build_steps([_seg(1)], MODE_BY_SEGMENT, 1, SPEED_BY_PATH,
                        cfg.limits.speed_max_mm_s, cfg.opcua.write_nodes["seg_array"])
    assert len(steps) == 1
    step = steps[0]
    assert (step.no, step.seg_no, step.process_step) == (1, 1, 1)
    assert step.pos_mm == _seg(1).end_mm and step.speed_mm_s == 50.0
    assert step.variable == cfg.opcua.write_nodes["seg_array"]     # 真实点表节点（⛔ 禁造字典名）
    assert step.note == "估算值"                                    # 速度为推算值（铁律 2）


def test_multi_segment_numbering_follows_start_no(cfg) -> None:
    segments = [_seg(1), _seg(2, end=(200.0, 0.0, 0.0)), _seg(3, end=(300.0, 0.0, 0.0))]
    steps = build_steps(segments, MODE_BY_SEGMENT, 7, SPEED_BY_PATH,
                        cfg.limits.speed_max_mm_s, SEG_NODE)
    assert [step.no for step in steps] == [1, 2, 3]
    assert [step.seg_no for step in steps] == [1, 2, 3]
    assert [step.process_step for step in steps] == [7, 8, 9]      # 起始序号＝工步起始输入


def test_by_point_keeps_every_point(cfg) -> None:
    segments = [_seg(1), _seg(2, end=(200.0, 0.0, 0.0))]
    steps = build_steps(segments, MODE_BY_POINT, 1, SPEED_BY_PATH,
                        cfg.limits.speed_max_mm_s, SEG_NODE)
    assert len(steps) == 3                                          # 首段起点＋各段终点
    assert steps[0].pos_mm == segments[0].start_mm
    assert [step.seg_no for step in steps] == [1, 1, 2]
    assert [step.process_step for step in steps] == [1, 2, 3]


def test_speed_source_dict_uses_dict_limit(cfg) -> None:
    segments = [_seg(1), _seg(2, end=(200.0, 0.0, 0.0))]
    for step in build_steps(segments, MODE_BY_SEGMENT, 1, SPEED_BY_DICT,
                            cfg.limits.speed_max_mm_s, SEG_NODE):
        assert step.speed_mm_s == cfg.limits.speed_max_mm_s         # 字典上限由调用方从 yaml 读
    assert SPEED_BY_PATH in SPEED_SOURCES and SPEED_BY_DICT in SPEED_SOURCES


def test_blocked_segment_kept_with_honest_note(cfg) -> None:
    steps = build_steps([_seg(1, blocked=True)], MODE_BY_SEGMENT, 1, SPEED_BY_PATH,
                        cfg.limits.speed_max_mm_s, SEG_NODE)
    assert steps[0].note != "估算值" and "不可达" in steps[0].note


def test_over_budget_reports_used_over_limit() -> None:
    steps = build_steps([_seg(i) for i in range(1, 4)], MODE_BY_SEGMENT, 1, SPEED_BY_PATH,
                        500.0, SEG_NODE)
    assert budget(steps, limit=2) == (3, 2)                         # used>limit ⇒ UI 黄警示不禁导出
    assert budget([], limit=200) == (0, 200)


def test_variable_map_only_real_nodeids(cfg) -> None:
    rows = variable_map(cfg)
    read_total = sum(len(v) if isinstance(v, (list, tuple)) else 1
                     for v in cfg.opcua.read_nodes.values())
    write_total = len(cfg.opcua.write_nodes)
    assert len(rows) == read_total + write_total                    # 读＋写节点各一行
    assert {row.node_id for row in rows} >= {str(n) for v in cfg.opcua.read_nodes.values()
                                             for n in (v if isinstance(v, (list, tuple)) else [v])}
    assert all("MasterLink" not in row.name and ".Command" not in row.name for row in rows)
    assert all(row.direction == "回读" for row in rows[:read_total])


def test_variable_map_pos_slots_follow_axes_order(cfg) -> None:
    rows = variable_map(cfg)
    axes_order = list(cfg.axes)
    pos = [row for row in rows if "Pos[" in row.name]
    assert len(pos) == len(cfg.opcua.read_nodes["axis_pos"])
    for index, row in enumerate(pos[:len(axes_order)]):
        assert row.axis == axes_order[index]                        # 插入序＝契约 Pos[] 排法
    assert pos[0].unit == "mm"                                      # 轴型单位（X1＝移动副）
    assert "待回执" in pos[0].note and cfg.axes[pos[0].axis].pending
    assert next(row for row in rows if "Vel[" in row.name).unit == "mm/s"


def test_illegal_mode_or_speed_source_rejected(cfg) -> None:
    with pytest.raises(ValueError):
        build_steps([_seg(1)], "by_craft", 1, SPEED_BY_PATH, 500.0, SEG_NODE)
    with pytest.raises(ValueError):
        build_steps([_seg(1)], MODES[0], 1, "by_mood", 500.0, SEG_NODE)
    assert MODE_BY_SEGMENT in MODES and MODE_BY_POINT in MODES


def test_csv_headers_and_rows() -> None:
    steps = build_steps([_seg(1)], MODE_BY_SEGMENT, 1, SPEED_BY_PATH, 500.0, SEG_NODE)
    lines = steps_to_csv(steps).strip().split("\n")
    assert lines[0] == ",".join(STEPS_HEAD) and len(lines[0].split(",")) == 10
    assert len(lines) == 2
    rows = vars_to_csv(variable_map(load_machine(str(REPO / "config" / "machine.yaml"))))
    head, *body = rows.strip().split("\n")
    assert head == ",".join(VARS_HEAD) and len(body) == 27          # 22 读＋5 写（现点表实况）
    assert all("," not in row.node_id for row in                    # NodeId 无逗号 ⇒ CSV 安全
               variable_map(load_machine(str(REPO / "config" / "machine.yaml"))))
