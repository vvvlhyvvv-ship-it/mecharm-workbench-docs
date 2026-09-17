"""tests/test_t10_guards.py —— T10 收口的配置守卫（G20）。

① **G20-①**：`tools/config_check.py` 的节点表摘要必须**按 SPEC 遍历生成**。原摘要写死 G17 前的
   「三读三写」，扩表后**静默漏列** 5 个读键（`axis_vel`／`ack`／`alarm_word`／`seq_id`／`cur_seg`）
   与 2 个写键（`seq_id`／`speed_override`）——而该摘要的用途正是「现场当面核对软件用的是哪份参数」，
   漏键＝现场看漏握手要用的键。本用例把摘要文本与 `core/config/schema.py` 的 `READ_NODE_SPEC`／
   `WRITE_NODE_SPEC` **逐键比对**：SPEC 再扩表而摘要没跟上，即在 pytest 内变红，⛔ 不再依赖人眼发现。
② **G20-②**：见 `test_publish_interval_ms_meets_min_data_hz`（常量与 `tools/e2e_smoke.py` 同源）。

归属与边界：`tools/e2e_smoke.py` 唯一写者＝T10；`tools/config_check.py` 的**摘要打印逻辑**经
§7.2-G20-① 授权由 T10 代 T03 改（⛔ 未动任何校验判定）。本文件**不改** `tests/test_config.py`
——该件归 T03，G17／G18 两条例外都明写「24 条用例须全绿且**不得改断言**」，故守卫另立一件。
"""

from __future__ import annotations

import subprocess
import sys

from core.config import REPO_ROOT, load_machine
from core.config.schema import READ_NODE_SPEC, WRITE_NODE_SPEC

CONFIG_CHECK = REPO_ROOT / "tools" / "config_check.py"
SAMPLE = REPO_ROOT / "config" / "machine.yaml"


def _run_config_check() -> subprocess.CompletedProcess[str]:
    """以 CLI 形态跑校验器（本用例要验的正是**退出码与打印文本**，故不走 import）。"""
    return subprocess.run([sys.executable, str(CONFIG_CHECK), str(SAMPLE)], cwd=REPO_ROOT,
                          capture_output=True, encoding="utf-8", errors="replace", check=False)


def _summary_lines(proc: subprocess.CompletedProcess[str]) -> tuple[str, str]:
    """取出「回读节点：」「下发节点：」两行；两者必须是**不同的两行**。

    ⚠️ 这条断言不是凑数：G17 前的实现把读／写节点挤在**同一条 print** 里（一行内同时含两个标记），
    若不要求分行，摘要退回硬编码单行时本用例会拿同一行去比两张 SPEC，漏键的检出面就窄了一半。
    """
    lines = proc.stdout.splitlines()
    read = next((ln for ln in lines if "回读节点" in ln), "")
    write = next((ln for ln in lines if "下发节点" in ln), "")
    assert read, f"摘要缺「回读节点」行：\n{proc.stdout}"
    assert write, f"摘要缺「下发节点」行：\n{proc.stdout}"
    assert read != write, f"读／写节点摘要挤在同一行（G17 前的硬编码形态）：{read}"
    return read, write


def test_config_check_summary_lists_every_spec_node_key() -> None:
    """G20-① 守卫：rc=0，且摘要**逐键列全** SPEC 的读／写节点键（含 NodeId 数组的实配个数）。"""
    proc = _run_config_check()
    assert proc.returncode == 0, (f"config_check 应 rc=0，实得 {proc.returncode}\n"
                                  f"{proc.stdout}{proc.stderr}")
    read, write = _summary_lines(proc)
    for key, is_list in READ_NODE_SPEC:
        assert key in read, f"回读摘要漏列 SPEC 键 {key}（硬编码过期的老毛病）：{read}"
        if is_list:
            count = len(load_machine(SAMPLE).opcua.read_nodes[key])
            assert f"{key} {count} 个" in read, f"回读摘要未按实配个数报 {key}：{read}"
    for key, is_list in WRITE_NODE_SPEC:
        assert key in write, f"下发摘要漏列 SPEC 键 {key}（硬编码过期的老毛病）：{write}"
        if is_list:
            count = len(load_machine(SAMPLE).opcua.write_nodes[key])
            assert f"{key} {count} 个" in write, f"下发摘要未按实配个数报 {key}：{write}"
