"""tests/test_prog_export.py —— T14 程序存取的 CSV/JSON 导出导入往返承重用例。

覆盖卡片完成标准「导出 CSV→清空→导入→步骤一致」的单测层：
  ① CSV 纯函数往返（app.prog_tab.build_csv／parse_csv）：清单字段逐点一致；坏表头／坏行／
     空名一律 ValueError 人话（⛔ 不跳过不补默认）；法向与来源面不在列内 ⇒ 占位恢复且
     source_face 为负（不会与真 B-Rep 面 id 相撞）。
  ② export_csv 落盘 UTF-8-BOM（Excel 可读，蓝图 §6.3）。
  ③ import_file 两条分支：CSV 清单级恢复＋JSON（proj/v1 工程原文）无损恢复——经**最小 stub 壳**
     （只实现 import_file 触及的 panel.step2／tabshell.prog.store_log/step3 面），免起 MainWindow
     （真壳往返由 tools/e2e_tabs.py 的 T14 判据承重）。
夹具纪律：只用 tmp_path；只用自造数据，⛔ 不出现甲方模型／名称／尺寸。
"""

from __future__ import annotations

import json
import pathlib

import pytest

from app.pop_import import export_csv, import_file
from app.prog_tab import CSV_HEAD, build_csv, parse_csv
from core.config import REPO_ROOT, load_machine
from core.geometry.face_point import Waypoint
from core.project import build_project, save

WPS = [Waypoint(id=1, name="P1", pos_mm=(10.5, 0.0, 30.0), normal=(0.0, 0.0, 1.0), source_face=7),
       Waypoint(id=3, name="落刀点", pos_mm=(-4.25, 96.0, 2740.125), normal=(1.0, 0.0, 0.0),
                source_face=9)]
KIND_TEXT = "点位型"


class _Step2:
    def __init__(self) -> None:
        self.points = None

    def set_waypoints(self, pts) -> None:
        self.points = list(pts)

    def waypoints(self):
        return list(WPS)


class _Step3:
    def current_kind_text(self) -> str:
        return KIND_TEXT


class _Store:
    def __init__(self) -> None:
        self.lines: list[str] = []

    def emit(self, msg: str) -> None:
        self.lines.append(msg)


class _StubWin:
    """import_file／export_csv 触及的最小壳面（⛔ 不碰真 MainWindow，那归 e2e）。"""

    def __init__(self) -> None:
        self.step2, self.step3, self.store = _Step2(), _Step3(), _Store()
        self.panel = type("Panel", (), {"step2": self.step2, "step3": self.step3})()
        prog = type("Prog", (), {"store_log": self.store})()
        self.tabshell = type("Tabs", (), {"prog": prog})()


# --- ① CSV 纯函数往返 ---------------------------------------------------------------- #
def test_csv_roundtrip_keeps_list_fields():
    text = build_csv(WPS, KIND_TEXT)
    assert text.splitlines()[0] == ",".join(CSV_HEAD)
    back = parse_csv(text)
    assert [(w.id, w.name, w.pos_mm) for w in back] == \
           [(w.id, w.name, w.pos_mm) for w in WPS]


def test_csv_roundtrip_marks_placeholder_normal_and_face():
    back = parse_csv(build_csv(WPS, KIND_TEXT))
    assert all(w.normal == (0.0, 0.0, 0.0) for w in back)
    assert all(w.source_face < 0 for w in back)          # 负占位：不与真 B-Rep 面 id 相撞


def test_csv_bad_header_and_rows_are_rejected():
    good = build_csv(WPS, KIND_TEXT).splitlines()
    with pytest.raises(ValueError, match="表头"):
        parse_csv("X,Y,Z\n1,2,3\n")
    with pytest.raises(ValueError, match="列"):
        parse_csv("\n".join(good + ["9,短行"]) + "\n")
    with pytest.raises(ValueError, match="非数字"):
        parse_csv("\n".join(good + ["9,P9,abc,0,0,点位型"]) + "\n")
    with pytest.raises(ValueError, match="名称为空"):
        parse_csv("\n".join(good + ["9, ,0,0,0,点位型"]) + "\n")


# --- ② 落盘 BOM 与 export→import 往返 -------------------------------------------------- #
def test_export_csv_writes_utf8_bom(tmp_path: pathlib.Path):
    win = _StubWin()
    target = tmp_path / "prog.csv"
    export_csv(win, str(target))
    assert target.read_bytes()[:3] == b"\xef\xbb\xbf"


def test_export_then_import_csv_roundtrip(tmp_path: pathlib.Path):
    win = _StubWin()
    target = tmp_path / "prog.csv"
    export_csv(win, str(target))
    win.step2.points = None                              # 模拟「清空后导入」
    points = import_file(win, str(target))
    assert [(w.id, w.name, w.pos_mm) for w in points] == \
           [(w.id, w.name, w.pos_mm) for w in WPS]
    assert any("占位恢复" in line for line in win.store.lines)   # 清单级恢复的如实声明


def test_import_rejects_bad_csv_without_touching_points(tmp_path: pathlib.Path):
    win = _StubWin()
    bad = tmp_path / "bad.csv"
    bad.write_text("X,Y,Z\n1,2,3\n", encoding="utf-8")
    assert import_file(win, str(bad)) is None
    assert win.step2.points is None                      # ⛔ 失败不落半成品
    assert any("导入未成功" in line for line in win.store.lines)


# --- ③ JSON（proj/v1 工程原文）无损恢复 ------------------------------------------------ #
def _proj_file(tmp_path: pathlib.Path) -> pathlib.Path:
    cfg = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
    project = build_project(cfg, None, None, WPS, None, None)
    return save(project, tmp_path / "prog.json")


def test_import_json_restores_waypoints(tmp_path: pathlib.Path):
    win = _StubWin()
    source = _proj_file(tmp_path)
    assert json.loads(source.read_text(encoding="utf-8"))["$schema"] == "proj/v1"
    points = import_file(win, str(source))
    assert [(w.id, w.name, w.pos_mm, w.normal, w.source_face) for w in points] == \
           [(w.id, w.name, w.pos_mm, w.normal, w.source_face) for w in WPS]


def test_import_rejects_broken_json_without_touching_points(tmp_path: pathlib.Path):
    win = _StubWin()
    broken = tmp_path / "broken.json"
    broken.write_text('{"$schema": "proj/v9"}', encoding="utf-8")
    assert import_file(win, str(broken)) is None
    assert win.step2.points is None
    assert any("导入未成功" in line for line in win.store.lines)
