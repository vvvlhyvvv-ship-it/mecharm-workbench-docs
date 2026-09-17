"""tests/test_t10_guards.py —— T10 收口的配置守卫（G20）与打包资源定位守卫（F4）。

① **G20-①**：`tools/config_check.py` 的节点表摘要必须**按 SPEC 遍历生成**。原摘要写死 G17 前的
   「三读三写」，扩表后**静默漏列** 5 个读键（`axis_vel`／`ack`／`alarm_word`／`seq_id`／`cur_seg`）
   与 2 个写键（`seq_id`／`speed_override`）——而该摘要的用途正是「现场当面核对软件用的是哪份参数」，
   漏键＝现场看漏握手要用的键。本用例把摘要文本与 `core/config/schema.py` 的 `READ_NODE_SPEC`／
   `WRITE_NODE_SPEC` **逐键比对**：SPEC 再扩表而摘要没跟上，即在 pytest 内变红，⛔ 不再依赖人眼发现。
② **G20-②**：见 `test_publish_interval_ms_meets_min_data_hz`（常量与 `tools/e2e_smoke.py` 同源）。
③ **雷(b)／F4**（T02 遗留）：`app/viewpane.py` 原用 `Path(__file__).resolve().parents[1]/"view"`
   定位 index.html——PyInstaller onedir 下本模块被收进 PYZ 归档、`__file__` 成了归档内虚拟路径，
   数父目录得到的位置与 `--add-data` 实际落地位置不再必然重合 ⇒ dist 起不来视口。现改为
   `resource_root()`（打包态取 `sys._MEIPASS`、开发态取仓根）。
   ⚠️ **本机没有任何打包器**（PyInstaller／Nuitka／cx_Freeze 全无；加装要动 `environment.yml`／
   `requirements.lock.txt`，属 §5 禁改件，待授权）⇒ 下面三条用**模拟的 onedir 目录树**验定位逻辑，
   是用例级证明，⛔ **不等于** dist 实机双击 exe 的启动证明（后者挂在打包单，本轮如实报挂起）。

归属与边界：`tools/e2e_smoke.py` 唯一写者＝T10；`tools/config_check.py` 的**摘要打印逻辑**经
§7.2-G20-① 授权由 T10 代 T03 改（⛔ 未动任何校验判定）；`app/viewpane.py` 的资源定位经派单
§4-雷(b) 点名授权修改。本文件**不改** `tests/test_config.py`——该件归 T03，G17／G18 两条例外都
明写「24 条用例须全绿且**不得改断言**」，故守卫另立一件。
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest

from app import viewpane
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


# --- 雷(b)／F4：onedir 打包下的资源定位 ------------------------------------------------------- #
# 本机**没有任何打包器**（PyInstaller／Nuitka／cx_Freeze 全无，加装属 §5 禁改件范围、待授权）⇒ 下面
# 三条用**模拟的 onedir 目录树**验定位逻辑本身。⚠️ 这是用例级证明，⛔ 不等于 dist 实机启动证明。
def _fake_onedir(tmp_path: pathlib.Path, with_view: bool) -> pathlib.Path:
    """造一个 PyInstaller onedir 的 `_internal` 目录（可选带 view/index.html）。"""
    internal = tmp_path / "dist" / "mecharm" / "_internal"
    internal.mkdir(parents=True)
    if with_view:
        (internal / "view").mkdir()
        (internal / "view" / "index.html").write_text("<html></html>", encoding="utf-8")
    return internal


def test_frozen_resource_root_follows_meipass(tmp_path: pathlib.Path,
                                              monkeypatch: pytest.MonkeyPatch) -> None:
    """F4：打包态资源根＝`sys._MEIPASS`，⛔ 不再按 `__file__` 数父目录（原写法在 dist 里指空）。

    ⚠️ 用例级证明（模拟 onedir 树），⛔ 不是 dist 实机启动证明——后者挂在打包单。
    """
    internal = _fake_onedir(tmp_path, with_view=True)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    assert viewpane.resource_root() == internal
    target = viewpane.index_html()
    assert target == internal / "view" / "index.html"
    assert target.exists(), "模拟包内明明有 index.html 却没定位到 ⇒ F4 未真修好"
    assert REPO_ROOT not in target.parents, "打包态还指着开发仓 ⇒ dist 里必然找不到文件"


def test_dev_resource_root_is_repo_root(monkeypatch: pytest.MonkeyPatch) -> None:
    """开发态（没有 `_MEIPASS`）＝仓根，且仓内真实的 view/index.html 能定位到。"""
    monkeypatch.delattr(sys, "_MEIPASS", raising=False)
    assert viewpane.resource_root() == REPO_ROOT
    target = viewpane.index_html()
    assert target == REPO_ROOT / "view" / "index.html"
    assert target.exists(), "连开发态都找不到 index.html ⇒ 定位逻辑本身坏了（不是打包问题）"


def test_frozen_missing_view_does_not_fall_back_to_repo(tmp_path: pathlib.Path,
                                                        monkeypatch: pytest.MonkeyPatch) -> None:
    """F4 配套：打包态文件缺失时**照样返回打包态路径**，⛔ 不偷偷回落开发仓。

    回落会把「包没打全」伪装成能跑，还会让错误卡印一个 dist 里不存在的开发路径，把打包缺陷指向
    错误方向（04 §5.5 附7 那一族：看着绿、实则掏空）⇒ 本用例专门锁住「不回落」这条。
    ⚠️ 用例级证明（模拟 onedir 树），⛔ 不是 dist 实机启动证明。
    """
    internal = _fake_onedir(tmp_path, with_view=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(internal), raising=False)
    target = viewpane.index_html()
    assert target == internal / "view" / "index.html"
    assert not target.exists(), "模拟包里本就没有 view/，这条前提坏了后面断言就没意义"
    assert REPO_ROOT not in target.parents, "回落到了开发态仓根 ⇒ 打包漏件会被掩盖"
