"""tests/test_config.py —— T03 参数体系 machine.yaml 强校验测试。

覆盖 T03 卡步骤 6 的全部要求：
  ① 合法样例过（现场样例 config/machine.yaml ＋最小样例 tests/fixtures/ok_minimal.yaml）
  ② 6 类非法样例逐项拒（缺字段／类型错／行程 min≥max／modes 子集与轨迹级上限／
     ratio 耦合／cache_dir 相对路径），并断言**消息一次列全**问题项数与字段名
  ③ pending 占位轴只告警不拒绝，告警文本列出全部轴名
  ④ modes 子集 ⊆ axes 且轨迹级轴计数 ≤ TRAJECTORY_AXES_MAX
  ⑤ ratio 耦合 ratio > 0 且 master 存在于 axes
  ⑥ cache_dir 仓内路径拒载（相对路径用静态 fixture；仓内绝对路径在 tmp_path 现场生成，
     因为仓根随 worktree／合并位置变化，写死会假通过）

单位口径见 S-1 契约第 7 章：直线轴 mm、回转轴 deg；坐标系＝设备坐标系。
"""

from __future__ import annotations

import importlib
import pathlib
import re

import pytest
import yaml

from core.config import (AXIS_KEYS, LIMIT_KEYS, LINK_KEYS, MACHINE_KEYS, MODE_KEYS, OPCUA_KEYS,
                         REPO_ROOT, TRAJECTORY_AXES_MAX, ZERO_OFFSET_KEY, ConfigError,
                         load_machine)

FIXTURES = pathlib.Path(__file__).resolve().parent / "fixtures"
SAMPLE = REPO_ROOT / "config" / "machine.yaml"
MINIMAL = FIXTURES / "ok_minimal.yaml"
COUNT = re.compile(r"共 (\d+) 项问题")

# (fixture 文件名, 期望问题项数, 期望消息里出现的字段名/关键词)
ILLEGAL = [
    ("bad_missing_field.yaml", 2, ("zero_offset_mm", "clearance_warn_mm")),
    ("bad_type.yaml", 3, ("travel", "scale", "publish_interval_ms")),
    ("bad_travel.yaml", 1, ("travel", "min 必须 < max")),
    ("bad_direction.yaml", 1, ("direction", "应为 1／-1")),
    ("bad_modes.yaml", 2, ("轴 id 不在 axes 表内", f"轨迹级轴 10 个 > 上限 {TRAJECTORY_AXES_MAX}")),
    ("bad_coupling_ratio.yaml", 2, ("coupling.ratio", "coupling.master")),
    ("bad_cache_dir_relative.yaml", 1, ("cache_dir", "必须是仓外绝对路径")),
]


def _load_error(path: pathlib.Path) -> str:
    """加载 path 并断言必抛 ConfigError，返回消息全文（供逐项断言）。"""
    with pytest.raises(ConfigError) as caught:
        load_machine(str(path))
    return str(caught.value)


def _write_variant(tmp_path: pathlib.Path, mutate) -> pathlib.Path:
    """以 ok_minimal.yaml 为基线，按 mutate 改一处后写到 tmp_path，返回新路径。"""
    data = yaml.safe_load(MINIMAL.read_text(encoding="utf-8"))
    mutate(data)
    out = tmp_path / "variant.yaml"
    out.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return out


# --------------------------------------------------------------------------
# ① 合法样例
# --------------------------------------------------------------------------

def test_sample_machine_yaml_loads() -> None:
    """现场样例 config/machine.yaml 必须能加载，且关键口径与 G11／过渡期口径一致。"""
    cfg = load_machine(str(SAMPLE))
    assert len(cfg.axes) == 22, "实机 22 轴（04 §7.2-G11）"
    assert cfg.opcua.pack_profile == "v1_2_8axis", "契约 V1.3 冻结前一律走 8 轴布局"
    assert len(cfg.opcua.read_nodes["axis_pos"]) == 8, "axis_pos 节点数须随 pack_profile"
    assert cfg.limits.collision_envelope_mm == 3.0, "契约 §8.4 建议 2–5 mm 取中"
    assert len(cfg.links) == 13 and len(cfg.modes) == 5


def test_sample_axis_coupling_is_config_driven() -> None:
    """双驱同步与倍速链都必须是配置驱动（04 附3），不是写死在代码里。"""
    cfg = load_machine(str(SAMPLE))
    gantry = cfg.axes["X1"].coupling
    assert gantry is not None and gantry.type == "sync"
    assert gantry.group == "gantry_travel" and gantry.sync_tol_mm == 0.5
    tube = cfg.axes["X3"].coupling
    assert tube is not None and tube.type == "ratio" and tube.ratio == 2.0


def test_sample_cache_dir_is_absolute_and_outside_repo() -> None:
    """缓存目录须为仓外绝对路径（缓存是甲方几何真身，远端为公开仓）。"""
    cache = pathlib.Path(load_machine(str(SAMPLE)).paths.cache_dir)
    assert cache.is_absolute()
    assert cache != REPO_ROOT and REPO_ROOT not in cache.parents


def test_sample_declares_localappdata_default() -> None:
    """样例里 cache_dir 的默认值口径须是 %LOCALAPPDATA%\\mecharm\\cache（仓外）。"""
    text = SAMPLE.read_text(encoding="utf-8")
    assert r"%LOCALAPPDATA%\mecharm\cache" in text


def test_minimal_fixture_loads_without_warnings() -> None:
    """最小样例不含 pending 键 ⇒ 加载成功且 warnings 为空（轴数是配置驱动的）。"""
    cfg = load_machine(str(MINIMAL))
    assert len(cfg.axes) == 2 and cfg.warnings == ()


# --------------------------------------------------------------------------
# ② 非法样例：逐项拒，且消息一次列全
# --------------------------------------------------------------------------

@pytest.mark.parametrize("name,count,tokens", ILLEGAL, ids=[case[0] for case in ILLEGAL])
def test_illegal_samples_rejected(name: str, count: int, tokens: tuple[str, ...]) -> None:
    """每类非法样例都必须拒载，消息含全部字段名，且问题项数与注入缺陷数一致。"""
    message = _load_error(FIXTURES / name)
    found = COUNT.search(message)
    assert found, f"消息未按「共 N 项问题」格式汇总：\n{message}"
    assert int(found.group(1)) == count, f"{name} 期望 {count} 项，实得消息：\n{message}"
    for token in tokens:
        assert token in message, f"{name} 消息缺 `{token}`：\n{message}"


def test_missing_section_rejected(tmp_path: pathlib.Path) -> None:
    """缺必填节（此处删 limits）→ 拒载并点名该节，不做默认值兜底。"""
    message = _load_error(_write_variant(tmp_path, lambda data: data.pop("limits")))
    assert "缺必填节 `limits`" in message


def test_nonexistent_file_rejected(tmp_path: pathlib.Path) -> None:
    """文件不存在 → ConfigError（不是 FileNotFoundError 裸抛给调用方）。"""
    message = _load_error(tmp_path / "no_such_machine.yaml")
    assert "无法读取配置文件" in message


def test_cache_dir_in_repo_rejected(tmp_path: pathlib.Path) -> None:
    """cache_dir 写成仓内绝对路径 → 拒载。

    此例**不能**做静态 fixture：仓根在 worktree 与合并后不同，写死路径会假通过。
    """
    inside = REPO_ROOT / "cache"
    message = _load_error(_write_variant(tmp_path,
                                        lambda data: data["paths"].update(cache_dir=str(inside))))
    assert "不得落在仓根目录内" in message


# --------------------------------------------------------------------------
# ③ pending 占位轴：只告警不拒绝
# --------------------------------------------------------------------------

def test_pending_axes_warn_without_rejecting() -> None:
    """样例 22 轴全为占位（pending: true）⇒ 不抛错，告警一条且列出全部轴名。"""
    cfg = load_machine(str(SAMPLE))
    assert len(cfg.warnings) == 1, cfg.warnings
    warning = cfg.warnings[0]
    assert "pending" in warning and "占位" in warning
    for axis_id in cfg.axes:
        assert axis_id in warning, f"告警未列出轴 {axis_id}：{warning}"


def test_pending_flag_defaults_to_false() -> None:
    """pending 键可省；最小样例两轴均按 false 解析（故上例 warnings 为空）。"""
    axes = load_machine(str(MINIMAL)).axes
    assert all(axis.pending is False for axis in axes.values())


# --------------------------------------------------------------------------
# ④⑤ 跨节不变量（对现场样例直接断言，防后续改 yaml 改坏）
# --------------------------------------------------------------------------

def test_modes_are_subsets_and_within_trajectory_cap() -> None:
    """每个工作模式的轴子集必须 ⊆ axes，且其中轨迹级轴数 ≤ 上限（下发段容量）。"""
    cfg = load_machine(str(SAMPLE))
    for mode in cfg.modes:
        assert set(mode.axes) <= set(cfg.axes), f"模式 {mode.id} 引用了不存在的轴"
        trajectory = [axis_id for axis_id in mode.axes
                      if cfg.axes[axis_id].role == "trajectory"]
        assert len(trajectory) <= TRAJECTORY_AXES_MAX, f"模式 {mode.id} 轨迹级轴超限"


def test_ratio_couplings_have_existing_master_and_positive_ratio() -> None:
    """ratio 耦合：master 必须在 axes 表内、ratio 必须为正（否则 fk 展开即错）。"""
    axes = load_machine(str(SAMPLE)).axes
    ratios = [axis for axis in axes.values()
              if axis.coupling is not None and axis.coupling.type == "ratio"]
    assert ratios, "样例应至少含一条倍速链（X3 三级筒 1:2）"
    for axis in ratios:
        assert axis.coupling.master in axes, f"{axis.id} 的 master 不在 axes 表内"
        assert axis.coupling.ratio > 0.0, f"{axis.id} 的 ratio 非正"


def test_links_form_known_parent_chain() -> None:
    """连杆表 parent 必须指向表内 id 或 null（根），否则 fk 无法建树。"""
    cfg = load_machine(str(SAMPLE))
    known = {link.id for link in cfg.links}
    roots = [link for link in cfg.links if link.parent is None]
    assert len(roots) == 1, f"应只有一个根连杆，实得 {[link.id for link in roots]}"
    for link in cfg.links:
        assert link.parent is None or link.parent in known, f"{link.id} 的 parent 不存在"


def test_sample_lists_every_required_key_explicitly() -> None:
    """样例必须把 03 §4 的必填键**逐个显式写出**（含值写 null 的 scale／coupling／parent）。

    加载器对「键缺失」与「值为 null」的处置并不相同（scale／coupling 允许 null），故这里直接查
    原文：防后续会话把 `coupling: null` 一类显式占位删掉而静默改变语义（该文件是全部单只读的
    热点文件，Q 回执冻结后只改此文件不改码）。同时锁定「回执前 22 轴一律 pending」的过渡期口径。
    """
    data = yaml.safe_load(SAMPLE.read_text(encoding="utf-8"))
    assert set(MACHINE_KEYS) <= set(data["machine"])
    for axis in data["axes"]:
        assert set(AXIS_KEYS) <= set(axis), f"轴 {axis.get('id')} 缺键"
        assert ZERO_OFFSET_KEY[axis["type"]] in axis, f"轴 {axis['id']} 缺零点键"
        assert axis["pending"] is True, f"轴 {axis['id']} 在回执前不得取消 pending 占位"
    for mode in data["modes"]:
        assert set(MODE_KEYS) <= set(mode), f"模式 {mode.get('id')} 缺键"
    for link in data["links"]:
        assert set(LINK_KEYS) <= set(link), f"连杆 {link.get('id')} 缺键"
    assert set(LIMIT_KEYS) <= set(data["limits"])
    assert set(OPCUA_KEYS) <= set(data["opcua"])


def test_package_root_reexports_every_public_symbol() -> None:
    """包化后调用形态一字不变：``__all__`` 里的符号都能从包根 `core.config` 导入。

    不另建 `tests/test_public_api.py`——该文件名已被 T04／T05 派单卡各自认领，建了就撞文件。
    """
    package = importlib.import_module("core.config")
    missing = [name for name in package.__all__ if not hasattr(package, name)]
    assert not missing, f"包根缺 re-export：{missing}"
    assert {"load_machine", "ConfigError", "MachineConfig"} <= set(package.__all__)
