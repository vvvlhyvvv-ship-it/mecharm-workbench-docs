"""evidence/T08/_probe_inject.py — 注入探针：改坏 core/collision.py 的判据后 pytest 必须**真失败**。

跑法（worktree 根，输出重定向即 `injection_probe_log.txt`）：
  PYTHONIOENCODING=utf-8 PYTHONPATH=. \
    D:/Miniforge3/envs/mecharm/python.exe evidence/T08/_probe_inject.py > evidence/T08/injection_probe_log.txt 2>&1

纪律（附7-②／项目记忆 evidence-validity）：
  ⛔ 不在本 worktree 里改交付件——`git` 工作树保持干净，缺陷只注入**仓外沙箱副本**（copytree 去 .git）；
  ⛔ 不接受 rc=2（收集错误）冒充 rc=1（断言失败）：每步断言 rc==1 且**失败项集合＝推理出的目标集合**
  （改了哪条判据、哪几条用例本该咬住它，事先写死在 MUTATIONS 里，⛔ 不照输出回填）；
  基线先跑一遍全绿，证明沙箱本身没坏。

旁证（首跑踩出、本轮不处置）：把包络配成 0 会让「父级原点＝本级原点」的连杆代理盒退化成零体积，
OCC 的 MakeBox 抛**原始错**（非人话 CollisionError）。生产不可达：machine.yaml 只读、现值 3.0；
本单不修——`core/collision.py` 已顶到 §4.5-① 的 300 行上限、`tools/config_check.py` 是禁改件 ⇒
留给配置校验那一单（汇报「报备项」已记）。故 M2 用「包络减半」而非「包络归零」做注入。
"""

from __future__ import annotations

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(__file__).resolve().parents[2]
PYTHON = sys.executable
TARGET = "tests/test_collision.py"
COLLISION = "core/collision.py"

# (缺陷名, 注入的文本替换, 推理上**必须**咬住它的用例集合)
MUTATIONS = [
    ("预警带失效：有命中也报 pass（三态塌成两态）",
     ("else VERDICT_WARN if cases else VERDICT_PASS", "else VERDICT_PASS"),
     {"test_three_verdicts_follow_the_hand_computed_gap[408",
      "test_precise_distance_is_b_rep_not_a_bounding_box_or_a_mesh",
      "test_collision_envelope_is_a_load_bearing_parameter"}),
    ("包络被偷改减半：代理盒外扩量不再等于配置值（§8.4 保守包络成摆设）",
     ("gap = scene.cfg.limits.collision_envelope_mm",
      "gap = scene.cfg.limits.collision_envelope_mm / 2.0"),
     {"test_three_verdicts_follow_the_hand_computed_gap[398",   # 断言里锁了 ±3 的代理盒坐标
      "test_three_verdicts_follow_the_hand_computed_gap[408",
      "test_precise_distance_is_b_rep_not_a_bounding_box_or_a_mesh",
      "test_collision_envelope_is_a_load_bearing_parameter",
      "test_cases_are_sorted_worst_first_and_one_per_link_obstacle_pair",
      "test_collision_module_has_no_magic_axis_numbers"}),   # 注入的 2.0 本身就是魔数 ⇒ lint 守卫咬
    ("G19 措辞松口：通过态说「通过」（未建模臂的判定空白被抹平）",
     ("tail.get(self.verdict, '未检出碰撞')", "tail.get(self.verdict, '通过')"),
     {"test_verdict_wording_never_reads_as_an_overall_pass",
      "test_site_config_run_counts_every_modeled_link_including_passive_ones"}),
]


def run(sandbox: pathlib.Path) -> tuple[int, list[str]]:
    """沙箱内跑目标测试文件，返回 (rc, 失败用例 id 列表)。"""
    proc = subprocess.run([PYTHON, "-m", "pytest", "-q", TARGET], cwd=sandbox,
                          capture_output=True, text=True, encoding="utf-8",
                          env={**os.environ, "PYTHONPATH": str(sandbox),
                               "PYTHONIOENCODING": "utf-8"})
    failed = [line.split("::", 1)[1].split(" ", 1)[0]
              for line in proc.stdout.splitlines() if line.startswith("FAILED ")]
    tail = [line for line in proc.stdout.splitlines() if line.strip().endswith("===")
            or " passed" in line or " failed" in line]
    print("   ", tail[-1] if tail else proc.stdout.strip().splitlines()[-1:])
    return proc.returncode, failed


def main() -> int:
    base = pathlib.Path(tempfile.mkdtemp(prefix="t08_inject_"))
    sandbox = base / "repo"          # copytree 要求目标不存在，故落在临时目录的子目录里
    shutil.copytree(REPO, sandbox, ignore=shutil.ignore_patterns(".git", "__pycache__", "*.png"))
    src = sandbox / COLLISION
    original = src.read_text(encoding="utf-8")
    print(f"沙箱: {sandbox}（{REPO} 的副本，⛔ 未动工作树）")
    print("\n=== 0. 基线：沙箱内目标测试全绿（证明沙箱没坏、失败只可能来自注入）===")
    rc, failed = run(sandbox)
    print(f"  rc={rc}｜失败 {len(failed)} 条｜{'对' if rc == 0 and not failed else '⛔ 不对'}")
    if rc != 0:
        shutil.rmtree(base, ignore_errors=True)
        return 1
    for index, (name, (old, new), expected) in enumerate(MUTATIONS, start=1):
        print(f"\n=== {index}. 注入缺陷：{name} ===")
        assert original.count(old) == 1, f"注入点不唯一：{old!r}"
        src.write_text(original.replace(old, new), encoding="utf-8")
        rc, failed = run(sandbox)
        print(f"  rc={rc}（须 1＝断言失败，⛔ 不是 2＝收集错误）｜失败 {len(failed)} 条:")
        for item in failed:
            print("    FAILED", item)
        matched = sorted(e for e in expected if any(f.startswith(e) for f in failed))
        extra = [f for f in failed if not any(f.startswith(e) for e in expected)]
        ok = rc == 1 and matched == sorted(expected) and not extra
        print(f"  判据: rc=1 且 目标集全被咬住 且 无目标外失败 ⇒ {'对' if ok else '⛔ 不对'}"
              f"｜推理目标: {sorted(expected)}｜目标外失败: {extra or '无'}")
        src.write_text(original, encoding="utf-8")
        if not ok:
            shutil.rmtree(base, ignore_errors=True)
            return 1
    shutil.rmtree(base, ignore_errors=True)
    print("\n注入探针结论：三条判据各被推理出的用例咬住（rc=1 真失败），基线全绿。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
