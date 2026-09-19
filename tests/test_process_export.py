"""tests/test_process_export.py —— T17 导出侧判据（卡片完成标准：三串逐字／BOM 在场／同源）。

**三串声明文案逐字守卫**：本文件里的期望值＝01 蓝图 §6.3 的逐字原文（收单核对基准），
被测值＝`config/ui.yaml` 三键经 ``load_ui`` 的实读——产品代码路径里没有第二份文案（§1-8），
测试里出现原文是**核对基准**、不是交付拷贝。BOM 判据＝`utf-8-sig` 写盘后前 3 字节实读。
"""

from __future__ import annotations

import csv
import io
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.config import load_machine
from core.config.ui_config import load_ui
from core.path import Segment
from core.process import STEPS_HEAD, build_steps, steps_to_csv, variable_map, vars_to_csv

REPO = pathlib.Path(__file__).resolve().parents[1]
UI_YAML = REPO / "config" / "ui.yaml"
SEG_NODE = 'ns=3;s="DB_SW_to_PLC"."Seg"'

# —— 01 蓝图 §6.3 逐字原文（V1.1 更正版；⛔ 不得缩写，第 3 串首词多「字典中」）—— #
EXPECT_TOP = "本输出为供电气 PLC 编程使用的工步数据与变量映射，不是我方交付的 PLC 程序。"
EXPECT_TABLE = ("ⓘ 各轴 Position 为只读；位置类指令需与 PLC 侧另行约定。"
                "本输出供 PLC 侧编程使用，不含联锁保护逻辑。")
EXPECT_FOOTER = ("ⓘ 字典中各轴 Position 为只读；位置类指令需与 PLC 侧另行约定。"
                 "本输出供 PLC 侧编程使用，不含联锁保护逻辑。")


def _seg(seg_id: int, end=(100.0, 0.0, 0.0)) -> Segment:
    return Segment(id=seg_id, type="LINE", start_name=f"P{seg_id}", end_name=f"P{seg_id + 1}",
                   start_mm=(0.0, 0.0, 0.0), end_mm=end, length_mm=100.0,
                   speed_mm_s=50.0, duration_s=2.0, joints_start={}, joints_end={},
                   blocked=False, reason="")


def test_three_declaration_strings_verbatim() -> None:
    """ui.yaml 三键与蓝图 §6.3 原文逐字一致（含第 2/3 串的「位置类指令需与 PLC 侧另行约定」）。"""
    ui = load_ui(str(UI_YAML))
    assert ui.plc_declare_top == EXPECT_TOP
    assert ui.plc_declare_table == EXPECT_TABLE
    assert ui.plc_declare_footer == EXPECT_FOOTER
    assert ui.plc_declare_table != ui.plc_declare_footer            # 三串禁合并复用（卡面注）


def test_declaration_keys_reach_the_config_object() -> None:
    """L-9 反证：三键真的进了定型对象（白名单登记生效，非被静默丢弃）。"""
    ui = load_ui(str(UI_YAML))
    for key in ("plc_declare_top", "plc_declare_table", "plc_declare_footer"):
        assert isinstance(getattr(ui, key), str) and getattr(ui, key)


def test_steps_csv_bom_is_present(tmp_path: pathlib.Path) -> None:
    """UTF-8-BOM 在场：`utf-8-sig` 写盘后前 3 字节实读 ＝ Excel 可读的判据（卡面 xxd 等价）。"""
    target = tmp_path / "工步数据表.csv"
    text = steps_to_csv(build_steps([_seg(1)], "by_segment", 1, "by_path", 500.0, SEG_NODE))
    target.write_text(text, encoding="utf-8-sig")
    assert target.read_bytes()[:3] == b"\xef\xbb\xbf"
    plain = tmp_path / "plain.csv"
    plain.write_text(text, encoding="utf-8")
    assert plain.read_bytes()[:3] != b"\xef\xbb\xbf"                # 反向对照：非 sig 无 BOM


def test_vars_csv_bom_is_present_and_parses(tmp_path: pathlib.Path) -> None:
    target = tmp_path / "变量映射.csv"
    rows = variable_map(load_machine(str(REPO / "config" / "machine.yaml")))
    target.write_text(vars_to_csv(rows), encoding="utf-8-sig")
    assert target.read_bytes()[:3] == b"\xef\xbb\xbf"
    parsed = list(csv.reader(io.StringIO(target.read_text(encoding="utf-8-sig"))))
    assert parsed[0] == ["方向", "变量", "NodeId", "关联轴", "单位", "说明"]
    assert len(parsed) - 1 == len(rows)


def test_steps_csv_round_trip_columns() -> None:
    """预览与导出同源的数据落到 CSV 后仍是 10 列（与预览模态表头同源同序）。"""
    steps = build_steps([_seg(1), _seg(2, end=(200.0, 0.0, 0.0))], "by_segment", 1, "by_path",
                        500.0, SEG_NODE)
    parsed = list(csv.reader(io.StringIO(steps_to_csv(steps))))
    assert parsed[0] == list(STEPS_HEAD)
    assert all(len(row) == len(STEPS_HEAD) for row in parsed)
    assert [row[0] for row in parsed[1:]] == ["1", "2"]             # 工步号列
    assert [row[7] for row in parsed[1:]] == ["1", "2"]             # ProcessStep 列（起始 1）


@pytest.mark.parametrize("banned", ["MasterLink", "J1.Command", "J4.Command"])
def test_no_demo_dictionary_words_in_outputs(banned: str) -> None:
    """Δ-5：导出物全量文本无演示字典字样（DEC-04 未决前禁造）。"""
    cfg = load_machine(str(REPO / "config" / "machine.yaml"))
    steps = build_steps([_seg(i) for i in range(1, 4)], "by_segment", 1, "by_path",
                        cfg.limits.speed_max_mm_s, cfg.opcua.write_nodes["seg_array"])
    assert banned not in steps_to_csv(steps)
    assert banned not in vars_to_csv(variable_map(cfg))
