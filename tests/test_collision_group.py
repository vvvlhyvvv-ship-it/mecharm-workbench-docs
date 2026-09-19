"""tests/test_collision_group.py —— T16 归并呈现层的承重用例（卡面步骤 1／完成标准③）。

① 无干涉（cases 空）→ 空报告，⛔ 不造行 ② 单组多步：同设备组多段涉事 → 一组、组内记录数＝步数
③ 多组：按涉事记录数降序、组名来自**父装配节点名**（演示稿「压机立柱3 · 上横梁」口径）、顶层零件
＝自身名 ④ 零件不在树里：如实跳过（skipped 记录＋warning 日志），⛔ 禁造组名——by_device 不含它、
group_of 回 None ⑤ GUI-free 守卫：本件源文件无 PySide6/Qt import（03 §3 core 铁律）。
判定真值不经本层：全部用例直接构造 ``CollisionResult``／``CollisionCase``（先例
tests/test_collision.py::_result），⛔ 不重跑几何。
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from core.collision import (FP_HEX_LEN, VERDICT_INTERFERE, CollisionCase, CollisionResult)
from core.collision_report import ClashReport, DeviceClash, group_by_device

SOURCE = pathlib.Path("core/collision_report.py").read_text(encoding="utf-8")


def _case(seg, part_b, dist):
    """一条涉事记录（part_a＝连杆 id、point/box 与归并无关，给占位真类型）。"""
    return CollisionCase(seg, "slide", part_b, dist, (0.0, 0.0, 0.0), None)


def _result(*cases):
    return CollisionResult(VERDICT_INTERFERE, tuple(cases), "0" * FP_HEX_LEN, 2, (), 7, 1.0)


def _node(name, children=(), is_assembly=False):
    """装配树节点替身（group_by_device 只读 name/children/is_assembly，先例 test_collision.py）。"""
    from types import SimpleNamespace
    return SimpleNamespace(name=name, children=list(children), is_assembly=is_assembly)


TREE = (_node("整线", (_node("压机立柱3", (_node("上横梁"), _node("立柱身")), is_assembly=True),
                      _node("自造挡块")), is_assembly=True),)


def test_no_cases_yields_empty_report():
    """承重用例①：无干涉 → 空报告（by_device／skipped 全空），headline 空串由调用方显「—」。"""
    report = group_by_device(_result(), TREE)
    assert report == ClashReport(by_device=(), skipped=())
    assert report.headline() == "" and report.group_of("上横梁") is None


def test_single_group_counts_steps_and_keeps_distance_order():
    """承重用例②：同一零件多段涉事 → 一组一条归并行、组内记录数＝涉事步数、沿用距离升序。"""
    cases = (_case(3, "上横梁", 8.0), _case(5, "上横梁", 0.0), _case(6, "上横梁", 2.0))
    report = group_by_device(_result(*cases), TREE)
    assert len(report.by_device) == 1
    row = report.by_device[0]
    assert (row.group, row.member) == ("压机立柱3", "上横梁")     # 组名＝父装配节点名（非自造）
    assert len(row.cases) == 3 and [c.seg_id for c in row.cases] == [3, 5, 6]  # 沿 cases 原序＝距离升序
    assert "压机立柱3 · 上横梁（3 处）" in report.headline()
    assert report.group_of("上横梁") == "压机立柱3"


def test_multiple_groups_sorted_by_step_count_desc():
    """承重用例③：多组按涉事记录数降序（同数按组名稳定）；子零件组名＝父装配名、根下顶层零件
    的组＝其父装配名（本树即「整线」）——组名一律来自树，⛔ 不自造。"""
    cases = (_case(1, "上横梁", 5.0), _case(2, "上横梁", 1.0), _case(3, "上横梁", 0.0),
             _case(4, "自造挡块", 2.0), _case(5, "自造挡块", 0.5))
    report = group_by_device(_result(*cases), TREE)
    assert [(r.group, r.member, len(r.cases)) for r in report.by_device] == [
        ("压机立柱3", "上横梁", 3), ("整线", "自造挡块", 2)]
    assert report.skipped == () and report.group_of("自造挡块") == "整线"


def test_part_missing_from_tree_is_skipped_with_warning(caplog):
    """承重用例④：零件不在树里 → 跳过＋告警，⛔ 禁造组名（by_device 不含、group_of 回 None）。"""
    cases = (_case(1, "上横梁", 0.0), _case(2, "已删除的零件", 0.0))
    with caplog.at_level("WARNING"):
        report = group_by_device(_result(*cases), TREE)
    assert [r.member for r in report.by_device] == ["上横梁"]
    assert report.skipped == ("已删除的零件",)
    assert report.group_of("已删除的零件") is None
    assert any("已删除的零件" in rec.message and "不在当前装配树" in rec.getMessage()
               for rec in caplog.records)


def test_same_member_takes_first_group_deterministically():
    """同名零件取**首个**出现的组（确定性，⛔ 不随机覆盖；真实导入树命名计数器保证叶名唯一）。"""
    tree = (_node("组A", (_node("垫块"),), is_assembly=True),
            _node("组B", (_node("垫块"),), is_assembly=True))
    report = group_by_device(_result(_case(1, "垫块", 0.0), _case(2, "垫块", 1.0)), tree)
    assert [(r.group, len(r.cases)) for r in report.by_device] == [("组A", 2)]
    assert report.group_of("垫块") == "组A"


def test_report_layer_is_gui_free():
    """守卫：core 层禁 PySide6/Qt import（03 §3 铁律，同 test_collision.py 的 FORBIDDEN 手法）。"""
    tree = ast.parse(SOURCE)
    banned = {"PySide6", "Qt"}
    mods = {node.names[0].name.split(".")[0] for node in ast.walk(tree)
            if isinstance(node, ast.Import)} | {
            node.module.split(".")[0] for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module}
    assert not (mods & banned), f"core 层出现 GUI 依赖：{mods & banned}"


@pytest.mark.parametrize("bad", [DeviceClash("", "", ())])
def test_frozen_dataclasses_reject_mutation(bad):
    """frozen 承重：报告层对象不可变（结论一次算完多处只读，禁半路改行数造假）。"""
    with pytest.raises(Exception):
        bad.group = "x"
    report = group_by_device(_result(_case(1, "上横梁", 0.0)), TREE)
    with pytest.raises(Exception):
        report.by_device[0].member = "别的零件"
