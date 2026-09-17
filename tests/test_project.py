"""tests/test_project.py —— T10 工程文件（`core/project.py`）承重用例与守卫。

覆盖卡片步骤 5 与完成标准第 3 条：
  ① 存→读回环：点位／路径快照／校核结论快照／配置版本**逐项**相等（⛔ 只比"没报错"不算证据）
  ② 配置版本字段在**文件正文里肉眼可见**（完成标准点名的取证口径）
  ③ 版本兼容策略：缺 `$schema`／格式不认／比本软件新 ⇒ 人话拒载；旧版本走 `_MIGRATIONS` 升级
     （迁移机制用 monkeypatch **临时注册**迁移步验证——仓内没有更早的在产格式，⛔ 不虚构格式史）
  ④ 结构坏掉（缺字段／类型错／三元素数组长度不对／非法 JSON／文件不存在）⇒ 一律 `ProjectError`
     人话，且消息点出坏在哪，⛔ 不返回半成品、⛔ 不用默认值把窟窿填平
  ⑤ 守卫：`to_dict` 的键集必须与 `Project` 的字段集同步（防加字段时静默漏存）＋ core 层不得沾 GUI

夹具纪律（04 §5.5 附则）：只用 `tmp_path` 生成路径，⛔ 不写死仓内绝对路径；只用自造数据，
⛔ 不出现甲方模型／名称／尺寸。
"""

from __future__ import annotations

import ast
import dataclasses
import json
import pathlib

import pytest

from core.collision import VERDICT_WARN, CollisionResult
from core.config import REPO_ROOT, load_machine
from core.geometry.face_point import Waypoint
from core.path import Segment, summarize
from core.project import (SCHEMA, ModelRef, Project, ProjectError, build_project, check_snapshot,
                          config_drift, from_dict, load, migrate, path_snapshot, save, to_dict)

CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
# 自造点位（坐标随手取的整数，⛔ 非甲方工件尺寸）
WPS = [Waypoint(id=1, name="P1", pos_mm=(10.0, 20.0, 30.0), normal=(0.0, 0.0, 1.0), source_face=7),
       Waypoint(id=3, name="起弧点", pos_mm=(-4.5, 0.0, 12.25), normal=(1.0, 0.0, 0.0), source_face=9)]
SEGMENTS = [Segment(id=1, type="LINE", start_name="P1", end_name="P2", start_mm=(0.0, 0.0, 0.0),
                    end_mm=(3.0, 4.0, 0.0), length_mm=5.0, speed_mm_s=50.0, duration_s=0.1,
                    joints_start={"X1": 0.0}, joints_end={"X1": 5.0}, blocked=False, reason="")]


def _result() -> CollisionResult:
    """一份**预警态**校核结论（含 2 根未建模轴 ⇒ 顺带锁住 G19 覆盖面句被原样存进快照）。"""
    return CollisionResult(verdict=VERDICT_WARN, cases=(), path_hash="abc123", modeled_links=13,
                           unmodeled_axes=("ZA1", "RA"), sample_count=42, elapsed_ms=12.5)


def _full() -> Project:
    """字段填满的工程（每个可空字段都非空 ⇒ 回环用例才真的覆盖到全部读写字段）。"""
    model = ModelRef(source_path="D:/tmp/self_made_box.step", is_brep=True, part_count=3)
    return build_project(CFG, "scale_crush", model, WPS,
                         path_snapshot(SEGMENTS, summarize(SEGMENTS), "contour", False),
                         check_snapshot(_result()))


# 参数化用例要的「合法原始 dict」：parametrize 装饰器在 import 期求值 ⇒ 必须早于它定义。
WPS_RAW = to_dict(_full())["waypoints"]
CHECK_RAW = to_dict(_full())["check"]


def _write(tmp_path: pathlib.Path, raw: object, name: str) -> pathlib.Path:
    target = tmp_path / name
    target.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
    return target


def test_save_load_roundtrip_keeps_every_field(tmp_path: pathlib.Path) -> None:
    """①：存→读回环，整个 Project 逐字段相等（含点位元组、两份快照与配置版本）。"""
    target = save(_full(), tmp_path / "sub" / "a.mproj")     # 顺带验父目录自动建
    back = load(target)
    assert back == _full()
    assert back.waypoints[1].name == "起弧点"                # 中文点位名经 UTF-8 往返不走样
    assert back.check is not None and back.check.verdict == VERDICT_WARN
    assert back.path is not None and back.path.segments[0]["type"] == "LINE"
    assert back.model is not None and back.model.is_brep is True


def test_schema_and_config_version_visible_in_file_text(tmp_path: pathlib.Path) -> None:
    """②：完成标准点名「配置版本字段在文件里可见」⇒ 直接查**文件正文**，不查解析后的对象。"""
    text = save(_full(), tmp_path / "b.mproj").read_text(encoding="utf-8")
    assert f'"$schema": "{SCHEMA}"' in text
    assert f'"config_ver": "{CFG.machine.schema_ver}"' in text
    assert f'"config_name": "{CFG.machine.name}"' in text
    assert text.index("$schema") < text.index("config_ver")   # 版本字段在文件头，现场一眼可见


def test_to_dict_keys_stay_in_sync_with_project_fields() -> None:
    """⑤ 守卫：`to_dict` 用 `asdict` 展开 ⇒ 键集必须＝字段集（只 `schema` 改名为 `$schema`）。
    这条锁的是「日后给 Project 加字段」不会静默漏存（04 §5.5 附7-③ 那一族）。"""
    fields = {f.name for f in dataclasses.fields(Project)}
    assert set(to_dict(_full())) == (fields - {"schema"}) | {"$schema"}


def test_newer_schema_is_refused_with_upgrade_hint(tmp_path: pathlib.Path) -> None:
    """③：比本软件新的版本一律拒载并提示升级——硬读会静默丢新字段（附7-③ 同族）。"""
    raw = dict(to_dict(_full()), **{"$schema": "proj/v2"})
    with pytest.raises(ProjectError) as info:
        load(_write(tmp_path, raw, "future.mproj"))
    assert "proj/v2" in str(info.value) and "升级软件" in str(info.value)


def test_missing_or_unknown_schema_is_refused(tmp_path: pathlib.Path) -> None:
    """③：缺 `$schema`／类型不对／格式不认 ⇒ 人话拒载（⛔ 不猜版本、⛔ 不按 v1 硬读）。"""
    base = to_dict(_full())
    cases = [(dict(base, **{"$schema": None}), "$schema", "none.mproj"),
             ({k: v for k, v in base.items() if k != "$schema"}, "缺 $schema 字段", "missing.mproj"),
             (dict(base, **{"$schema": "mecharm-1"}), "不是本软件的格式", "alien.mproj")]
    for raw, needle, name in cases:
        with pytest.raises(ProjectError) as info:
            load(_write(tmp_path, raw, name))
        assert needle in str(info.value), f"{raw.get('$schema')!r} 的报错没点到 {needle!r}：{info.value}"


def test_old_schema_is_upgraded_by_registered_step(monkeypatch: pytest.MonkeyPatch) -> None:
    """③：迁移机制走得通——临时注册 `proj/v0`→`proj/v1` 一步，旧文件升完即可正常定型。

    ⚠️ 用 monkeypatch 注册迁移步、而不是在仓里造一个「历史上的 v0 工程」：`_MIGRATIONS` 当前为空
    是事实（v1 是首个在产版本），本用例要验的是「真出旧版本时机制可用」，⛔ 不虚构格式史。
    """
    from core import project as mod

    def to_v1(raw: dict) -> dict:
        raw["$schema"] = SCHEMA
        raw["saved_at"] = "1970-01-01T00:00:00+00:00"      # 旧格式没有该字段，迁移步负责补
        return raw

    monkeypatch.setitem(mod._MIGRATIONS, "proj/v0", to_v1)
    raw = dict(to_dict(_full()), **{"$schema": "proj/v0"})
    raw.pop("saved_at")
    assert migrate(raw)["$schema"] == SCHEMA
    assert from_dict(migrate(raw)).saved_at == "1970-01-01T00:00:00+00:00"


def test_old_schema_without_migration_step_is_refused() -> None:
    """③：**今天的真实情形**——收到 `proj/v0` 而表里没有迁移步 ⇒ 人话拒载，⛔ 不按 v1 硬读。"""
    with pytest.raises(ProjectError, match="无迁移步"):
        migrate({"$schema": "proj/v0"})


def test_migration_loop_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    """③ 守卫：迁移步写错（升完还是自己）⇒ 报「成环」而不是死循环挂住界面。"""
    from core import project as mod

    def stuck(raw: dict) -> dict:
        raw["$schema"] = "proj/v0"
        return raw

    monkeypatch.setitem(mod._MIGRATIONS, "proj/v0", stuck)
    with pytest.raises(ProjectError, match="成环"):
        migrate({"$schema": "proj/v0"})


@pytest.mark.parametrize("mutate, needle", [
    (lambda d: d.pop("saved_at"), "缺字段 saved_at"),
    (lambda d: d.update(saved_at=123), "saved_at 应是 str"),
    (lambda d: d.update(waypoints=[{"id": 1}]), "缺字段 waypoints[0].name"),
    (lambda d: d.update(waypoints=[dict(WPS_RAW[0], pos_mm=[1.0, 2.0])]), "应是 3 个数"),
    (lambda d: d.update(waypoints=[dict(WPS_RAW[0], normal=["a", 0, 0])]), "含非数字"),
    (lambda d: d.update(model={"source_path": "x"}), "缺字段 model.is_brep"),
    (lambda d: d.update(check=dict(CHECK_RAW, elapsed_ms="快")), "应是数字"),
    (lambda d: d.update(path=[]), "path 应是对象或 null"),
])
def test_broken_structure_is_refused_in_plain_words(mutate, needle: str) -> None:
    """④：结构坏掉一律 `ProjectError` 人话，且**消息点出坏在哪个字段**（不是笼统一句"格式错误"）。"""
    raw = to_dict(_full())
    mutate(raw)
    with pytest.raises(ProjectError) as info:
        from_dict(raw)
    assert needle in str(info.value), f"报错没点到 {needle!r}：{info.value}"


def test_unreadable_file_is_refused(tmp_path: pathlib.Path) -> None:
    """④：文件不存在／非法 JSON／顶层不是对象 ⇒ 三种人话各不相同（现场据此知道该修哪一头）。"""
    with pytest.raises(ProjectError, match="找不到工程文件"):
        load(tmp_path / "nope.mproj")
    truncated = tmp_path / "truncated.mproj"
    truncated.write_text('{"$schema": "proj/v1",', encoding="utf-8")     # 写了一半就断
    with pytest.raises(ProjectError, match="不是合法 JSON"):
        load(truncated)
    with pytest.raises(ProjectError, match="顶层应是对象"):
        load(_write(tmp_path, [1, 2], "arr.mproj"))


def test_sparse_project_roundtrips_with_nones(tmp_path: pathlib.Path) -> None:
    """空工程（未选模式、无模型、无路径、无校核）也是合法文件：可存可读，可空字段回到 None。"""
    bare = build_project(CFG, None, None, [], None, None)
    back = load(save(bare, tmp_path / "bare.mproj"))
    assert back == bare
    assert (back.mode, back.model, back.path, back.check) == (None, None, None, None)


def test_config_drift_reports_only_on_mismatch() -> None:
    """配置版本一致 ⇒ None（不打扰）；不一致 ⇒ 人话告警且带两个版本号，要求重新生成与校核。"""
    assert config_drift(_full(), CFG) is None
    other = dataclasses.replace(CFG, machine=dataclasses.replace(CFG.machine, schema_ver="9.9"))
    text = config_drift(_full(), other)
    assert text is not None
    for needle in (CFG.machine.schema_ver, "9.9", "重新生成路径", "重新校核"):
        assert needle in text, f"告警缺 {needle!r}：{text}"


def test_snapshots_keep_core_wording_verbatim() -> None:
    """快照存的是 core 的**人话原文**：G19 覆盖面标注与三态结论一字不改（⛔ 本层不改写判定措辞）。"""
    result = _result()
    snap = check_snapshot(result)
    assert (snap.sentence, snap.coverage) == (result.describe(), result.coverage())
    assert "2 根未建模臂" in snap.coverage and "干涉未校核" in snap.coverage
    assert snap.path_hash == "abc123" and snap.elapsed_ms == 12.5
    path = path_snapshot(SEGMENTS, summarize(SEGMENTS), "contour", False)
    assert path.segments[0]["reason"] == "" and path.segments[0]["length_mm"] == 5.0
    assert path.summary == summarize(SEGMENTS).describe()


_BANNED_ROOTS = ("PySide6", "shiboken6", "app", "comm")


def _imported_roots(path: pathlib.Path) -> tuple[set[str], list[int]]:
    """AST 取该文件 import 的**顶层包名**，外加「越级相对导入」的行号（level≥2 ＝ 逃出 core 包）。

    ⛔ 不做源码文本搜索：docstring 里写一句「本件无 PySide6 依赖」会被文本匹配当成违规（假红），
    而真 import 了 GUI 又可能因写法不同漏掉（假绿）。「core 不得 import GUI」的判据只能落在语法树上。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    roots: set[str] = set()
    escaping: list[int] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level >= 2:
                escaping.append(node.lineno)
            elif node.module:
                roots.add(node.module.split(".")[0])
    return roots, escaping


def test_project_module_stays_gui_free() -> None:
    """⑤ 守卫：`core/project.py` 属 core 层 ⇒ ⛔ 不得 import GUI／app／comm（03 §3 铁律）。"""
    target = pathlib.Path(__file__).resolve().parents[1] / "core" / "project.py"
    roots, escaping = _imported_roots(target)
    assert roots, f"AST 一个 import 都没读到 ⇒ 守卫已空转（空集合会让断言恒真，04 §5.5 附7-①）：{target}"
    hit = sorted(roots & set(_BANNED_ROOTS))
    assert not hit, f"core/project.py import 了 {hit}：core 层不得依赖 GUI／app／comm"
    assert not escaping, f"core/project.py 第 {escaping} 行有越级相对导入（逃出了 core 包）"
    assert {"json", "pathlib", "core"} <= roots, f"连自己的正常依赖都没读到，守卫读错文件了：{sorted(roots)}"
