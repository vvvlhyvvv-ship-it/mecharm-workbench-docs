"""core.config.ui_config —— ui.yaml（界面文案单一来源）的定型与强校验（T12）。

并入 core/config 既有体系：错误类型复用 ``schema.ConfigError``、语义同 ``loader.py``
的「问题一次性收集再抛」（一次改完全部问题，不逐条抛）。与 machine.yaml 的加载器
分件不分家：本件只认 ``config/ui.yaml`` 一份文件，``schema_ver`` 单列、不与业务键混。

键表即白名单（99 台账 L-9 的教训反过来用）：**未登记的键一律拒载报错**——machine.yaml
的校验器按 SPEC 遍历、未登记键被静默丢弃；ui.yaml 的键全是对外文案，静默丢键等于
「配置写了但界面读不到」，故这里把静默丢弃改成显式报错，配套用例锁死该行为。
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace

import yaml

from core.config.schema import ConfigError

UI_SCHEMA_VER = "ui/v1"
PROFILES = ("default", "evidence")
STAGE_DEFAULTS = ("auto", "std", "wide")
# 文本键：非空字符串（身份类文案，代码里禁写字面量——蓝图 §1-8）。
TEXT_KEYS = ("brand_name", "brand_sub", "system_name", "company", "company_en",
             "bidder_note", "bid_no", "watermark", "version_text",
             "login_user_default", "login_name_default")
INT_KEYS = ("splash_max_ms", "process_step_budget")     # 正整数（ms／工步数）
# 取证档必须**全覆盖**的键：漏一键＝该身份串以真实值漏进取证画面（红线 12）。
EVIDENCE_KEYS = ("company", "company_en", "bidder_note", "watermark", "bid_no",
                 "version_text", "login_user_default", "login_name_default")
TOP_KEYS = ("schema_ver",) + TEXT_KEYS + INT_KEYS + ("motion_enabled", "stage_default",
                                                     "evidence_profile")


@dataclass(frozen=True)
class UiConfig:
    """ui.yaml 的定型结果。文案单位＝无（纯展示串）；splash_max_ms＝ms；
    process_step_budget＝工步数；stage_default 见蓝图 §5 档位表。"""

    schema_ver: str
    brand_name: str
    brand_sub: str
    system_name: str
    company: str
    company_en: str
    bidder_note: str
    bid_no: str
    watermark: str
    version_text: str
    login_user_default: str
    login_name_default: str
    splash_max_ms: int
    motion_enabled: bool
    process_step_budget: int
    stage_default: str


def _read(path: str) -> Mapping:
    """读文件并解析；不可读／非法 YAML／顶层非映射 → 直接抛 ConfigError。"""
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except OSError as exc:
        raise ConfigError(f"{path}: 无法读取界面配置 → {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"{path}: YAML 解析失败 → {exc}") from exc
    if not isinstance(data, Mapping):
        raise ConfigError(f"{path}: 顶层应为映射，实得 {type(data).__name__}")
    return data


def _format(path: str, problems: list[str]) -> ConfigError:
    detail = "\n".join(f"  - {item}" for item in problems)
    return ConfigError(f"{path}: 界面配置校验不通过，共 {len(problems)} 项问题\n{detail}")


def _check_texts(problems: list[str], data: Mapping) -> dict[str, str]:
    out: dict[str, str] = {}
    for key in TEXT_KEYS:
        raw = data.get(key)
        if not isinstance(raw, str) or not raw:
            problems.append(f"{key}: 缺必填键或应为非空字符串，实得 {raw!r}")
        else:
            out[key] = raw
    return out


def _check_ints(problems: list[str], data: Mapping) -> dict[str, int]:
    out: dict[str, int] = {}
    for key in INT_KEYS:
        raw = data.get(key)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw <= 0:
            problems.append(f"{key}: 应为正整数，实得 {raw!r}")
        else:
            out[key] = raw
    return out


def _check_evidence(problems: list[str], raw: object) -> dict[str, str]:
    """取证档覆盖节：键必须「不多不少」等于 EVIDENCE_KEYS，值一律非空字符串。"""
    if not isinstance(raw, Mapping):
        problems.append(f"evidence_profile: 应为映射，实得 {type(raw).__name__}")
        return {}
    out: dict[str, str] = {}
    for key in sorted(set(raw) - set(EVIDENCE_KEYS)):
        problems.append(f"evidence_profile.{key}: 未登记的覆盖键（合法键：{'、'.join(EVIDENCE_KEYS)}）")
    for key in EVIDENCE_KEYS:
        value = raw.get(key)
        if not isinstance(value, str) or not value:
            problems.append(f"evidence_profile.{key}: 取证档缺覆盖键或值为空——漏一键即真实身份串"
                            f"漏进取证画面，必须全覆盖")
        else:
            out[key] = value
    return out


def _validate(path: str, data: Mapping) -> tuple[dict, dict, dict, str, bool, str]:
    problems: list[str] = []
    for key in sorted(set(data) - set(TOP_KEYS)):
        problems.append(f"{key}: 未登记的键（ui.yaml 键表在 core/config/ui_config.py，加键先登记）")
    version = data.get("schema_ver")
    if not isinstance(version, str) or not version:
        problems.append(f"schema_ver: 缺必填键或应为非空字符串，实得 {version!r}")
    elif version != UI_SCHEMA_VER:
        problems.append(f"schema_ver: 应为 {UI_SCHEMA_VER}（本加载器不认此版本），实得 {version!r}")
    texts = _check_texts(problems, data)
    ints = _check_ints(problems, data)
    motion = data.get("motion_enabled")
    if not isinstance(motion, bool):
        problems.append(f"motion_enabled: 应为布尔值，实得 {motion!r}")
    stage = data.get("stage_default")
    if stage not in STAGE_DEFAULTS:
        problems.append(f"stage_default: 取值应为 {'|'.join(STAGE_DEFAULTS)} 之一，实得 {stage!r}")
    evidence = _check_evidence(problems, data.get("evidence_profile"))
    if problems:
        raise _format(path, problems)
    return texts, ints, evidence, version, motion, stage


def load_ui(path: str, profile: str = "default") -> UiConfig:
    """读取并强校验 ui.yaml，返回定型后的 UiConfig。

    profile="evidence" 时以 evidence_profile 节覆盖身份类键（裁决 7：凡入 evidence/
    的截图一律取证档启动）。校验不通过抛 ConfigError，消息列出全部问题项。
    """
    if profile not in PROFILES:
        raise ConfigError(f"ui-profile: 取值应为 {'|'.join(PROFILES)} 之一，实得 {profile!r}")
    texts, ints, evidence, version, motion, stage = _validate(path, _read(path))
    if profile == "evidence":
        texts = {**texts, **evidence}
    return UiConfig(schema_ver=version, motion_enabled=motion, stage_default=stage,
                    splash_max_ms=ints["splash_max_ms"],
                    process_step_budget=ints["process_step_budget"], **texts)


def to_evidence(config: UiConfig, overrides: Mapping[str, str]) -> UiConfig:
    """按已校验的覆盖表生成取证档配置（供调用方在不重读盘的情况下切换档）。"""
    return replace(config, **{key: str(value) for key, value in overrides.items()})
