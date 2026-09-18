"""tests/test_ui_config.py —— ui.yaml 加载与校验守卫（T12 卡步骤 10）。

锁五件事：①缺键报错（说人话、点名键）；②坏值报错（类型/取值域/正整数）；
③**未登记键报错**——machine.yaml 侧的白名单校验器会把未登记键静默丢弃（99 台账
L-9／G17 同类教训），ui.yaml 侧反其道行之：未登记即拒载，防「配置写了界面读不到」；
④evidence_profile 全覆盖且覆盖生效（漏一键＝真实身份串漏进取证画面，红线 12）；
⑤process_step_budget 为正整数（T17 读）。
合法样例直接读仓内 config/ui.yaml（真实交付物，⛔ 不在测试里复写身份字面量）。
"""

from __future__ import annotations

import copy
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from core.config.schema import ConfigError
from core.config.ui_config import UI_SCHEMA_VER, load_ui

REPO_UI = pathlib.Path(__file__).resolve().parents[1] / "config" / "ui.yaml"


@pytest.fixture()
def base_data() -> dict:
    with open(REPO_UI, encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def write(tmp_path: pathlib.Path, data: dict) -> str:
    target = tmp_path / "ui.yaml"
    target.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    return str(target)


def test_real_config_loads_with_expected_types(base_data: dict) -> None:
    ui = load_ui(str(REPO_UI))
    assert ui.schema_ver == UI_SCHEMA_VER == base_data["schema_ver"]
    assert isinstance(ui.motion_enabled, bool) and ui.motion_enabled
    assert isinstance(ui.process_step_budget, int) and ui.process_step_budget > 0
    assert isinstance(ui.splash_max_ms, int) and ui.splash_max_ms > 0
    assert ui.stage_default in ("auto", "std", "wide")
    assert ui.brand_name and ui.company and ui.version_text


def test_missing_key_fails_with_key_named(tmp_path: pathlib.Path, base_data: dict) -> None:
    del base_data["watermark"]
    with pytest.raises(ConfigError) as exc:
        load_ui(write(tmp_path, base_data))
    assert "watermark" in str(exc.value)


@pytest.mark.parametrize("key,bad", [
    ("stage_default", "banana"), ("motion_enabled", "yes"),
    ("process_step_budget", 0), ("process_step_budget", 12.5), ("splash_max_ms", "fast"),
    ("version_text", ""), ("schema_ver", "ui/v0"), ("evidence_profile", "占位"),
])
def test_bad_value_fails(tmp_path: pathlib.Path, base_data: dict, key: str, bad: object) -> None:
    base_data[key] = bad
    with pytest.raises(ConfigError) as exc:
        load_ui(write(tmp_path, base_data))
    assert key in str(exc.value)


def test_unknown_top_level_key_fails(tmp_path: pathlib.Path, base_data: dict) -> None:
    base_data["surprise_key"] = "写了也没人读"
    with pytest.raises(ConfigError) as exc:
        load_ui(write(tmp_path, base_data))
    assert "surprise_key" in str(exc.value) and "未登记" in str(exc.value)


def test_unknown_evidence_key_fails(tmp_path: pathlib.Path, base_data: dict) -> None:
    base_data["evidence_profile"]["extra"] = "多写的覆盖键"
    with pytest.raises(ConfigError) as exc:
        load_ui(write(tmp_path, base_data))
    assert "extra" in str(exc.value) and "未登记" in str(exc.value)


def test_evidence_missing_override_key_fails(tmp_path: pathlib.Path, base_data: dict) -> None:
    del base_data["evidence_profile"]["bid_no"]
    with pytest.raises(ConfigError) as exc:
        load_ui(write(tmp_path, base_data), profile="evidence")
    assert "bid_no" in str(exc.value)


def test_evidence_profile_overrides_identity_texts(tmp_path: pathlib.Path,
                                                   base_data: dict) -> None:
    normal = load_ui(write(tmp_path, copy.deepcopy(base_data)))
    evidence = load_ui(str(tmp_path / "ui.yaml"), profile="evidence")
    for key in ("company", "company_en", "bidder_note", "watermark", "bid_no",
                "version_text", "login_user_default", "login_name_default"):
        assert getattr(evidence, key) == base_data["evidence_profile"][key]
        assert getattr(evidence, key) != getattr(normal, key)
    # 非身份键不被动：品牌/系统名两档一致
    assert evidence.brand_name == normal.brand_name
    assert evidence.system_name == normal.system_name


def test_bad_profile_argument_fails() -> None:
    with pytest.raises(ConfigError):
        load_ui(str(REPO_UI), profile="turbo")
