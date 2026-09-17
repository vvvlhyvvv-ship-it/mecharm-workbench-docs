"""§7-⑦ 取证：工程保存 → 改点 → 加载回滚 ＋ 配置版本字段可见（T10 卡片步骤 5）。

跑法（worktree 根，⛔ 不需 QT_QPA_PLATFORM：`core/project.py` 是 GUI-free 的，本脚本不起 Qt）：

    PYTHONPATH=. PYTHONIOENCODING=utf-8 python evidence/T10/_drive_project.py

⛔ 入库边界（`evidence/README.md`）：点位／路径段／校核结论全是现场构造的**自造基本体**，不引用任何
甲方模型、名称或尺寸；工程文件落 `tempfile.TemporaryDirectory(prefix="t10_")`，**不落仓内**，日志里
只留临时路径与字段值。

各节对应卡片步骤 5 与派单 §7-⑦ 的判据：
  【1】存盘成功，路径在 temp 里
  【2】`$schema`／`config_name`／`config_ver` 在**文件正文**里可见（不是只在解析后的对象里）
  【3】【4】改点 → 加载 ⇒ 点位回到存盘时的值（「加载回滚」）
  【5】配置版本比对：一致＝无告警；不一致＝人话告警（不静默、不自动改数）
  【6】版本策略三态拒载：比本软件新／缺 `$schema`／格式不认
  【7】旧版本按 `_MIGRATIONS` 逐级升级（机制可用；仓内**无**虚构的 v0 格式史）
  【8】派生结果（路径段／校核结论）按**快照**存取，加载后是「当时算出了什么」的记录，
      G19 覆盖面标注原样留着，⛔ 不当现成结论继续用
"""

from __future__ import annotations

import dataclasses
import json
import pathlib
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))   # 允许直接 python 跑本文件

from core.collision import VERDICT_WARN, CollisionResult          # noqa: E402
from core.config import REPO_ROOT, load_machine                   # noqa: E402
from core.geometry.face_point import Waypoint                     # noqa: E402
from core.path import Segment, summarize                          # noqa: E402
from core.project import (SCHEMA, ModelRef, Project, ProjectError,  # noqa: E402
                          build_project, check_snapshot, config_drift, load, path_snapshot, save)

CFG = load_machine(str(REPO_ROOT / "config" / "machine.yaml"))
# 自造点位：坐标随手取的整数／小数，⛔ 非甲方工件尺寸；点位名一个英文一个中文（顺带验 UTF-8 往返）
WPS = [Waypoint(id=1, name="P1", pos_mm=(10.0, 20.0, 30.0), normal=(0.0, 0.0, 1.0), source_face=7),
       Waypoint(id=2, name="起弧点", pos_mm=(-4.5, 0.0, 12.25), normal=(1.0, 0.0, 0.0), source_face=9)]
SEGMENTS = [Segment(id=1, type="LINE", start_name="P1", end_name="起弧点", start_mm=(10.0, 20.0, 30.0),
                    end_mm=(-4.5, 0.0, 12.25), length_mm=25.0, speed_mm_s=50.0, duration_s=0.5,
                    joints_start={"X1": 0.0}, joints_end={"X1": 25.0}, blocked=False, reason="")]
EDITED = (999.0, 888.0, 777.0)      # 【3】里假装操作员把 P1 拖到的新坐标（⛔ 不落盘）


def rule(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def make_project() -> Project:
    """一份字段填满的工程（预警态校核结论，含 2 根未建模轴 ⇒ 顺带把 G19 覆盖面句存进快照）。"""
    result = CollisionResult(verdict=VERDICT_WARN, cases=(), path_hash="abc123", modeled_links=13,
                             unmodeled_axes=("ZA1", "RA"), sample_count=42, elapsed_ms=12.5)
    model = ModelRef(source_path="D:/tmp/self_made_box.step", is_brep=True, part_count=3)
    return build_project(CFG, "scale_crush", model, WPS,
                         path_snapshot(SEGMENTS, summarize(SEGMENTS), "contour", False),
                         check_snapshot(result))


def main() -> int:
    tmp = tempfile.TemporaryDirectory(prefix="t10_")
    root = pathlib.Path(tmp.name)
    project = make_project()

    rule("【1】存盘：工程写到临时目录（⛔ 不落仓内）")
    target = save(project, root / "工程存档演示.mproj")     # 顺带验中文文件名与父目录自动建
    print(f"落盘路径：{target}")
    print(f"字节数：{target.stat().st_size}　后缀：{target.suffix}　在临时目录内：{root in target.parents}")

    rule("【2】配置版本字段在**文件正文**里可见（现场用记事本就能核对）")
    text = target.read_text(encoding="utf-8")
    print("---- 文件正文前 8 行 ----")
    for line in text.splitlines()[:8]:
        print(line)
    print("---- 判据 ----")
    q = chr(34)                       # 3.11 的 f-string 表达式里不许出现反斜杠 ⇒ 用 chr(34) 拼引号
    schema_line = f"{q}$schema{q}: {q}{SCHEMA}{q}"
    name_line = f"{q}config_name{q}: {json.dumps(CFG.machine.name, ensure_ascii=False)}"
    ver_line = f"{q}config_ver{q}: {q}{CFG.machine.schema_ver}{q}"
    print(f"$schema 在正文里：{schema_line in text}（字面 {schema_line}）"
          f"　且位于 config_ver 之前：{text.index('$schema') < text.index('config_ver')}")
    print(f"config_name 在正文里：{name_line in text}（字面 {name_line}）")
    print(f"config_ver 在正文里：{ver_line in text}（字面 {ver_line}）")
    print(f"对照当前 machine.yaml：name ＝ {CFG.machine.name}、schema_ver ＝ {CFG.machine.schema_ver}")

    rule("【3】改点：操作员在内存里把 P1 拖到新坐标（⛔ 未存盘）")
    edited = dataclasses.replace(project, waypoints=(dataclasses.replace(WPS[0], pos_mm=EDITED), WPS[1]))
    print(f"存盘时的 P1：{project.waypoints[0].pos_mm}")
    print(f"改点后的 P1：{edited.waypoints[0].pos_mm}　← 这是当前编辑态，文件里还是旧值")

    rule("【4】加载回滚：load 回来 ⇒ 点位回到存盘时的值")
    back = load(target)
    print(f"load 读到的 P1：{back.waypoints[0].pos_mm}")
    print(f"等于存盘时原值：{back.waypoints[0].pos_mm == project.waypoints[0].pos_mm}"
          f"　不等于编辑态：{back.waypoints[0].pos_mm != EDITED}")
    print(f"整个工程逐字段相等：{back == project}")
    print(f"中文点位名往返不走样：{back.waypoints[1].name!r}")
    print("⇒ 加载＝按存盘内容覆盖当前编辑态（回滚成立），⛔ 不做「合并两边」那种猜人心的事")

    rule("【5】配置版本比对：一致＝无告警；不一致＝人话告警")
    print(f"版本一致时 config_drift() → {config_drift(back, CFG)!r}　（None＝不吵用户）")
    fake = dataclasses.replace(back, config_ver="machine/v999_假版本")
    print("版本不一致时 config_drift() →")
    print(f"  {config_drift(fake, CFG)}")

    rule("【6】版本策略三态拒载：一律人话，⛔ 不猜版本、⛔ 不硬读")
    cases = [("比本软件新", dict(json.loads(text), **{"$schema": "proj/v2"})),
             ("缺 $schema", {k: v for k, v in json.loads(text).items() if k != "$schema"}),
             ("格式不认", dict(json.loads(text), **{"$schema": "mecharm-1"}))]
    for label, raw in cases:
        probe = root / f"{label}.mproj"
        probe.write_text(json.dumps(raw, ensure_ascii=False), encoding="utf-8")
        try:
            load(probe)
            print(f"  ✗ {label}：竟然读进来了（判据失效）")
        except ProjectError as exc:
            print(f"  ✓ {label} ⇒ ProjectError：{exc}")

    rule("【7】旧版本按 _MIGRATIONS 逐级升级（机制可用）")
    from core import project as mod
    old = dict(json.loads(text), **{"$schema": "proj/v0"})
    old.pop("saved_at")            # 假装 v0 格式还没有这个字段，由迁移步负责补

    def to_v1(raw: dict) -> dict:
        raw["$schema"] = SCHEMA
        raw["saved_at"] = "1970-01-01T00:00:00+00:00"
        return raw

    probe = root / "old.mproj"
    probe.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    try:
        load(probe)
        print("  ✗ 未注册迁移步就读进来了（判据失效）")
    except ProjectError as exc:
        print(f"  ✓ 未注册迁移步 ⇒ 拒载：{exc}")
    mod._MIGRATIONS["proj/v0"] = to_v1
    try:
        upgraded = load(probe)
        print(f"  ✓ 注册 proj/v0→proj/v1 一步后 ⇒ 升级并定型成功，$schema={upgraded.schema}、"
              f"saved_at={upgraded.saved_at}、点位数={len(upgraded.waypoints)}")
    finally:
        mod._MIGRATIONS.pop("proj/v0", None)
    print("  ⚠️ 迁移表在仓内**当前为空**：v1 是首个在产版本，⛔ 不为「让迁移看起来有内容」虚构 v0 格式史；"
          "本节用临时注册的迁移步证明机制可用")

    rule("【8】派生结果是**快照**：路径段与校核结论只作「当时算出了什么」的记录")
    print(f"路径快照汇总：{back.path.summary}")
    print(f"逐段摘要：{[dict(seg) for seg in back.path.segments]}")
    print(f"校核结论：{back.check.sentence}")
    print(f"G19 覆盖面标注（原样存下来，免得日后只看文件把「未检出碰撞」误读成「通过」）：{back.check.coverage}")
    print(f"路径指纹：{back.check.path_hash}　耗时：{back.check.elapsed_ms} ms")
    print("⇒ 加载后点位一恢复，步骤③④由既有作废链自动清空，⛔ 不把快照当现成结论继续用")

    tmp.cleanup()
    print(f"\n临时目录已清理：{not pathlib.Path(root).exists()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
