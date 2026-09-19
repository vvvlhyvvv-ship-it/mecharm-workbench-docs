"""tools/e2e_plc —— T17 PLC 输出区与预览模态判据（standalone；99 台账 2026-09-19 预声明新件）。

为什么独立成件：``e2e_tabs.py`` 300/300 冻结、``e2e_smoke.py`` 冻结拼接（L-2）⇒ 本单判据落
本件（模式同 ``e2e_sim``：自起 ``e2e_rig.Rig`` 只 import 不改），rc=0＝全 PASS。**本单零通讯**：
PLC 输出是纯离线数据交接物（卡面目标句），全程不连模拟器不握手。

判据（对 T17 卡完成标准逐条；读**操作员看得见的那份原文**，同 smoke 口径）：
  P1 空态：输出区整体禁用＋「先在上方生成轨迹」＋徽标「未生成」｜
  P2 生成：点[生成] ⇒ 汇总行真值（N 工步＝段数、M 条＝点表实况、预算 N/limit——limit 读 ui.yaml）
  P2B 超预算：预算改 1 ⇒ 黄警示「超预算」＋导出钮仍可用（如实呈现，不禁导出）｜
  P3 预览模态：红条两行＝ui.yaml 第 1/2 串逐字、页脚注＝第 3 串、表头 10 列、KPI 真值、✕ 可关｜
  P4 导出 CSV：文件名＝〈工程名〉_〈表名〉_〈时间戳〉.csv、BOM 前 3 字节在场、行数＝N+1/M+1｜
  P5 失效联动：改点位 ⇒ 「路径已改动…重新生成」＋预览/导出/复制禁用（pathctl.changed 唯一联动）｜
  P6 变量映射：M＝点表实况（22 读＋5 写）且 UI 与 CSV 全文无 MasterLink／J1.Command（Δ-5）。
"""

from __future__ import annotations

import argparse
import dataclasses
import os
import pathlib
import re
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from app.bootstrap import preload_windows_icu  # noqa: E402  须在任何 PySide6 之前（ICU 陷阱）

preload_windows_icu()

import app.plc_out as plc_module  # noqa: E402
from core.process import STEPS_HEAD, steps_to_csv, variable_map, vars_to_csv  # noqa: E402
from core.geometry.face_point import FacePoint  # noqa: E402
from tools.comm_selftest_kit import check, force_utf8_stdout, guarded, recording  # noqa: E402
from tools.e2e_rig import THREE_POINTS, Rig  # noqa: E402

OUTPUT = pathlib.Path("evidence/T17/e2e_plc.txt")
AREA = lambda rig: rig.win.tabshell.prog.plc_out  # noqa: E731  判据都落在输出区可见态上


def section_empty(rig: Rig, results: dict, _d: dict) -> None:
    """P1：未生成路径 ⇒ 整体禁用＋「先在上方生成轨迹」（Δ-6 禁演示值）。"""
    area = AREA(rig)
    print("\n=== P1 未生成路径的空态 ===")
    off = all(not w.isEnabled() for w in (area._sw_steps, area._sw_vars, area._mode,
                                          area._speed, area._btn_build))
    three_off = all(not b.isEnabled() for b in (area._btn_preview, area._btn_export, area._btn_copy))
    print(f"  编排/开关禁用={off}｜预览/导出/复制禁用={three_off}｜汇总行={area._summary.text()!r}"
          f"｜徽标={area._badge.text()!r}")
    check(results, "P1", off and three_off and area._summary.text() == "先在上方生成轨迹"
          and area._badge.text() == "未生成",
          "未生成路径：输出区整体禁用＋「先在上方生成轨迹」在场（卡片步骤 6）")


def _prepare(rig: Rig) -> None:
    """导入自造障碍＋注三点＋生成路径＋校核（真控制器路径；同 e2e_sim._prepare）。"""
    assert rig.import_box()
    rig.pick()
    rig.win.pathctl.generate()
    rig.win.checkctl.run_check()
    rig.pump(200)


def section_generate(rig: Rig, results: dict, _d: dict) -> None:
    """P2＋P6：生成 → 汇总行真值＋变量映射条数＝点表实况＋禁字典字样（Δ-5）。"""
    area, segments = AREA(rig), rig.win.pathctl.segments()
    print("\n=== P2 生成工步（P6 变量映射同轮核）===")
    area._btn_build.click()
    text = area._summary.text()
    n, m, limit = len(segments), len(variable_map(rig.cfg)), rig.win.ui.process_step_budget
    modal_kpi_ok = f"已生成 {n} 工步" in text and f"变量映射 {m} 条" in text \
        and f"预算 {n}/{limit}" in text
    banned_hits = _banned_in_ui(rig)
    print(f"  段数={n}｜汇总行={text!r}｜徽标={area._badge.text()!r}｜映射行数={m}"
          f"｜UI 禁词命中={banned_hits}")
    check(results, "P2", area._badge.text() == f"{n} 工步" and modal_kpi_ok
          and area._btn_preview.isEnabled() and not banned_hits,
          "点[生成] ⇒ 徽标/汇总行全真值（工步数＝段数、映射条数＝点表实况、预算读 ui.yaml）")
    check(results, "P6", m == 27 and not banned_hits,
          "变量映射 27 行＝点表实况（22 读＋5 写）；UI 全文无 MasterLink／J1.Command（Δ-5）")


def _banned_in_ui(rig: Rig) -> list[str]:
    """UI 全文扫禁词（输出区＋预览模态的标签与表格原文，Δ-5／卡面禁止事项）。"""
    texts = [w.text() for w in AREA(rig).findChildren(type(AREA(rig)._summary))]
    preview = getattr(rig.win, "plc_preview", None)
    if preview is not None:
        texts += [w.text() for w in preview.findChildren(type(preview._meta))]
        for row in range(preview._table.rowCount()):
            for col in range(preview._table.columnCount()):
                item = preview._table.item(row, col)
                if item:
                    texts.append(item.text())
    return [w for w in ("MasterLink", "J1.Command") if any(w in t for t in texts)]


def section_over_budget(rig: Rig, results: dict, _d: dict) -> None:
    """P2B：预算改 1 ⇒ 黄警示在场＋导出仍可用（如实呈现不禁导出）；测毕还原。"""
    area = AREA(rig)
    print("\n=== P2B 超预算黄警示（预算改 1，测毕还原）===")
    real_ui = rig.win.ui
    rig.win.ui = dataclasses.replace(real_ui, process_step_budget=1)
    area._btn_build.click()
    warn = area._summary.property("tone") == "warn" and "超预算" in area._summary.text()
    export_ok = area._btn_export.isEnabled()
    rig.win.ui = real_ui
    area._btn_build.click()                    # 还原口径后按真预算重生成（P3/P4 用干净态）
    print(f"  黄警示={warn}｜导出仍可用={export_ok}｜还原后汇总={area._summary.text()!r}")
    check(results, "P2B", warn and export_ok and "超预算" not in area._summary.text(),
          "超预算 ⇒ 汇总行黄警示「超预算」；导出钮仍可用（如实呈现，不禁导出）；还原后警示退场")


def section_preview(rig: Rig, results: dict, _d: dict) -> None:
    """P3：预览模态——红条两行/页脚注逐字（读 ui.yaml 的那一份）＋10 列表头＋KPI 真值。"""
    area, preview = AREA(rig), rig.win.plc_preview
    print("\n=== P3 预览模态（演示稿画面 09）===")
    area._btn_preview.click()
    rig.pump(200)
    n = len(rig.win.pathctl.segments())
    heads = [preview._table.horizontalHeaderItem(i).text() for i in range(preview._table.columnCount())]
    kpis = {key: label.text() for key, label in preview._kpi.items()}
    opened = preview.isVisible()
    verbatim = (preview._decl[0].text() == rig.win.ui.plc_declare_top
                and preview._decl[1].text() == rig.win.ui.plc_declare_table
                and preview._foot_note.text() == rig.win.ui.plc_declare_footer)
    print(f"  可见={opened}｜红条两行＝ui 第 1/2 串逐字={verbatim}｜页脚＝第 3 串="
          f"{preview._foot_note.text() == rig.win.ui.plc_declare_footer}"
          f"｜表头={heads}｜KPI={kpis}｜行数={preview._table.rowCount()}")
    preview.findChildren(__import__("PySide6.QtWidgets", fromlist=["QPushButton"]).__dict__["QPushButton"])[-1].click()
    rig.pump(100)
    closed = not preview.isVisible()
    print(f"  ✕ 关闭后可见={preview.isVisible()}")
    check(results, "P3", opened and verbatim and heads == list(STEPS_HEAD)
          and kpis["工步数"] == str(n) and kpis["弦高容差"] == "待定" and kpis["掉头保护"] == "待定"
          and preview._table.rowCount() == n and closed,
          "模态红条两行/页脚注与 ui.yaml 三串逐字一致；表头 10 列；KPI 真值＋弦高/掉头「待定」；✕ 可关")


def section_export(rig: Rig, results: dict, _d: dict) -> None:
    """P4：导出双 CSV——文件名口径＋BOM 前 3 字节＋行数（预览与导出同源：同一 _built）。"""
    area, rig2 = AREA(rig), rig
    print("\n=== P4 导出 CSV（UTF-8 BOM）===")
    seen: list[str] = []
    real_dialog = plc_module.QFileDialog.getSaveFileName

    def _fake(_parent, _caption, default: str, _filter: str):
        seen.append(pathlib.Path(default).name)
        target = pathlib.Path(rig2.tmp.name) / pathlib.Path(default).name
        return str(target), ""

    plc_module.QFileDialog.getSaveFileName = staticmethod(_fake)
    try:
        area._btn_export.click()
        rig2.pump(200)
    finally:
        plc_module.QFileDialog.getSaveFileName = real_dialog
    n, m = len(rig2.win.pathctl.segments()), len(variable_map(rig2.cfg))
    stem = rig2.cfg.machine.name
    pattern = re.compile(rf"^{re.escape(stem)}_(工步数据表|变量映射)_\d{{8}}_\d{{6}}\.csv$")
    names_ok = len(seen) == 2 and all(pattern.match(name) for name in seen)
    paths = [pathlib.Path(rig2.tmp.name) / name for name in seen]
    steps_path = next(p for p in paths if "工步数据表" in p.name)
    vars_path = next(p for p in paths if "变量映射" in p.name)
    bom_steps = steps_path.read_bytes()[:3] == b"\xef\xbb\xbf"
    bom_vars = vars_path.read_bytes()[:3] == b"\xef\xbb\xbf"
    rows_ok = (len(steps_path.read_text(encoding="utf-8-sig").strip().split("\n")) == n + 1
               and len(vars_path.read_text(encoding="utf-8-sig").strip().split("\n")) == m + 1)
    print(f"  文件名={seen}｜工步 BOM={bom_steps} 变量 BOM={bom_vars}｜工步行={n + 1} 映射行={m + 1}")
    check(results, "P4", names_ok and bom_steps and bom_vars and rows_ok,
          "文件名＝〈工程名〉_〈表名〉_〈时间戳〉.csv；两份 CSV 前 3 字节均 BOM；行数＝表头+N／表头+M")
    check(results, "P6B", not any(w in steps_path.read_text(encoding="utf-8-sig")
                                  or w in vars_path.read_text(encoding="utf-8-sig")
                                  for w in ("MasterLink", "J1.Command")),
          "导出 CSV 全文无 MasterLink／J1.Command（Δ-5，与 P6 的 UI 侧合围）")


def section_stale(rig: Rig, results: dict, _d: dict) -> None:
    """P5：路径改动 ⇒ 工步作废＋重生成提示（预览/导出/复制随之禁用）。"""
    area = AREA(rig)
    print("\n=== P5 路径改动 ⇒ 工步作废 ===")
    rig.win.panel.step2.clear()
    for index, pos in enumerate(THREE_POINTS[:2], start=1):
        rig.win.panel.step2.add_face_point(
            FacePoint(pos_mm=pos, normal=(0.0, 0.0, 1.0), source_face=index))
    rig.pump(300)
    told = area._summary.text()
    off = all(not b.isEnabled() for b in (area._btn_preview, area._btn_export, area._btn_copy))
    print(f"  汇总行={told!r}｜三钮禁用={off}")
    check(results, "P5", told == "路径已改动，已生成工步作废——请重新点「生成」" and off,
          "pathctl.changed ⇒ 已生成工步作废＋重生成提示在场（卡片步骤 6 失效联动）")


def main(argv=None) -> int:
    args = parse(argv)
    force_utf8_stdout()
    results: dict[str, bool] = {}
    with recording(None if args.no_save else OUTPUT):
        print(f"T17 PLC 输出区与预览模态判据 · python {sys.version.split()[0]} · "
              f"{time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"取证物 {OUTPUT}｜只跑 {args.only or '全部节'}")
        rig = Rig()
        try:
            for key, body in PLAN:
                if args.only and not key.upper().startswith(args.only.upper()):
                    continue
                if key == "PREP":
                    _prepare(rig)                     # 导入/取点/生成/校核（无判据）
                elif body is not None:
                    guarded(results, key, lambda run=body: run(rig, results, {}))
            rig.tab("prog")
            rig.pump(200)
        finally:
            rig.close()
        bad = [key for key, ok in results.items() if not ok]
        picked = [key for key, _b in PLAN if not args.only or key.upper().startswith(args.only.upper())]
        missing = [key for key in picked if key != "PREP" and key not in results]
        print("\n=== 结论 ===")
        for key, _body in PLAN:
            if key in results:
                print(f"  {key:<4} {'PASS' if results[key] else 'FAIL'}")
        print(f"  未跑到：{('、'.join(missing)) if missing else '无'}｜共 {len(results)} 条："
              f"{len(results) - len(bad)} PASS、{len(bad)} FAIL")
        print("结论：" + ("全链路走通" if not bad and not missing else "有判据未过，见上文原文"))
    return 0 if not bad and not missing else 1


def parse(argv=None):
    parser = argparse.ArgumentParser(description="T17 PLC 输出判据（离屏、零通讯）")
    parser.add_argument("--only", default="", help="只跑这些节（前缀匹配，如 P4）")
    parser.add_argument("--no-save", action="store_true", help="不落 evidence/T17/e2e_plc.txt")
    return parser.parse_args(argv)


# (判据号, 入口)；PREP 哨兵＝导入/取点/生成/校核（无判据）
PLAN = (("P1", section_empty), ("PREP", None), ("P2", section_generate),
        ("P2B", section_over_budget), ("P3", section_preview), ("P4", section_export),
        ("P5", section_stale))

if __name__ == "__main__":
    raise SystemExit(main())
