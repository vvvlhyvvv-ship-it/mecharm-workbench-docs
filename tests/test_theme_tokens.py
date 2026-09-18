"""T11 令牌完备性守卫：`app/theme.py` TOKENS 与 01 对齐蓝图 V1.2 §4 三表逐行一致。

锁四件事（T11 派单卡「完成标准」第 1/3 条）：
① 三表必需键全在、值逐行一致（§4-A 颜色／§4-B 尺寸与字号／§4-C 圆角分层）；
② 青底主按钮文字＝深色 `#08161c`（演示稿 `.btn.primary`，不是白字）；
③ accent 为唯一强调色：旧蓝系（#2f6feb/#16202a 系）在 QSS 渲染结果中全部退场；
④ 视口两件与令牌源同步：`view/css/app.css` 与 `view/js/loader.js` 不残留旧令牌值
   （浅色画布 #d9e2ea 在场）。

口径依据：`对齐任务包/01_对齐蓝图_V1.0.md` §4（内部 V1.2）；演示稿
`RoboPath_HMI_交互演示.html` `:root`（HTML:12–35）。⛔ 不得以 `前端任务包/02_界面设计方案`
§4 的旧数值（≥14px／≥40px／圆角 8px 通吃）判本表不合格（00 README §二 裁决 5）。
"""

from __future__ import annotations

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.theme import MONO_FAMILIES, SANS_FAMILIES, TOKENS, build_qss

ROOT = pathlib.Path(__file__).resolve().parents[1]

# §4-A 颜色（含沿用键 off_bg/off_text；演示稿变量名见蓝图行内注）
COLORS = {
    "bg_deep": "#101317", "bg_top": "#161a20", "bg_panel": "#1c222a",
    "bg_card": "#232a34", "border": "#2c3440", "border2": "#3a4553",
    "text": "#dfe6ef", "text_dim": "#93a1b3", "text_faint": "#64748b",
    "accent": "#35d0ff", "accent_deep": "#0d7fa8", "on_accent": "#08161c",
    "ok": "#35e08a", "warn": "#f5b544", "deny": "#ff4d4d",
    "off_bg": "#1a242e", "off_text": "#5a6875", "canvas": "#d9e2ea",
}
# §4-B 尺寸与字号（std 档字面值；wide 倍率归 T12）
SIZES = {
    "body_px": "13", "btn_h": "26", "btn_h_s": "21", "step_px": "14.5",
    "btn_px": "12", "topbar_h": "56", "status_h": "32", "tab_h": "36",
    "tree_row_h": "23", "s1": "4", "s2": "8", "s3": "12", "s4": "16",
    "fs_wide": "1.56",
}
# §4-C 圆角分层（不是一个 8px 通吃）
RADII = {
    "r_modal": "8", "r_card": "0", "r_ctl": "5",
    "r_ctl_s": "4", "r_pill": "999", "r_tab_badge": "8",
}
OLD_PALETTE = ("#16202a", "#101a23", "#1d2a36", "#22303d", "#2c3d4d",
               "#e6edf3", "#9fb0bd", "#2f6feb", "#3d7bf5",
               "#1c7c43", "#d9a521", "#b3261e")


def test_color_tokens_match_blueprint() -> None:
    """§4-A：颜色键全在且逐值一致。"""
    for key, value in COLORS.items():
        assert TOKENS.get(key) == value, f"颜色令牌 {key} 期望 {value}，实得 {TOKENS.get(key)!r}"


def test_size_tokens_match_blueprint() -> None:
    """§4-B：尺寸/字号键全在且逐值一致（正文 13px、控件高 26/21px，裁决 5）。"""
    for key, value in SIZES.items():
        assert TOKENS.get(key) == value, f"尺寸令牌 {key} 期望 {value}，实得 {TOKENS.get(key)!r}"


def test_radius_tiers_exist() -> None:
    """§4-C：圆角分层键在场——模态 8／卡片 0／控件 5／小控件 4／胶囊 999／页签徽标 8。"""
    for key, value in RADII.items():
        assert TOKENS.get(key) == value, f"圆角令牌 {key} 期望 {value}，实得 {TOKENS.get(key)!r}"


def test_primary_button_uses_deep_text_on_cyan() -> None:
    """青底主按钮＝深字 #08161c（非白字）；QSS 渲染结果里不得再出现青底白字。"""
    qss = build_qss()
    assert TOKENS["on_accent"] == "#08161c"
    assert "color: #08161c" in qss, "主按钮/选中态的青底深字未落到 QSS"
    primary = qss.split('QPushButton[role="primary"] {')[1].split("}")[0]
    assert "color: #08161c" in primary, "主按钮选择器未用深字"
    assert "color: #ffffff" not in qss, "QSS 仍有白字残留（青/绿底一律深字）"


def test_old_palette_fully_retired() -> None:
    """唯一强调色＝accent 青；旧蓝系与旧深色系在 QSS 渲染结果中全部退场。"""
    qss = build_qss()
    for stale in OLD_PALETTE:
        assert stale not in qss, f"旧令牌 {stale} 仍在 QSS 中"


def test_viewport_files_follow_token_source() -> None:
    """视口两件与令牌源同步：浅色画布 #d9e2ea 在场、旧值退场、--fs 变量入口已铺。"""
    css = (ROOT / "view/css/app.css").read_text(encoding="utf-8")
    js = (ROOT / "view/js/loader.js").read_text(encoding="utf-8")
    assert "--canvas: #d9e2ea" in css and "--fs: 1" in css, "app.css 缺画布/档位变量入口"
    assert "0xd9e2ea" in js, "loader.js 画布底色未切浅色"
    for stale in ("#16202a", "#2f6feb", "0x16202a", "0x2f6feb"):
        assert stale not in css, f"app.css 残留旧令牌 {stale}"
        assert stale not in js, f"loader.js 残留旧令牌 {stale}"


def test_font_helpers_single_source() -> None:
    """字体链唯一来源：正文走 YaHei UI 系、数值走 Cascadia/Consolas 系（演示稿 --sans/--mono）。"""
    assert SANS_FAMILIES[0] == "Microsoft YaHei UI"
    assert MONO_FAMILIES[0] == "Cascadia Mono"
    qss = build_qss()
    assert "*[mono=\"true\"]" in qss, "QSS 缺等宽数字动态属性入口"
