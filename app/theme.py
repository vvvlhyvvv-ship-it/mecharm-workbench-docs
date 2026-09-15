"""全局视觉 token 与 Qt 样式表的唯一定义处（02 设计方案 §4 视觉硬指标落地）。

铁律：字号、按钮规格、配色一律在此集中定义，其他模块**禁散写**内联样式；
需要按状态变色时用 Qt 动态属性（property）配合本表的属性选择器，并在切换属性后
调用 style().unpolish(w)/polish(w) 让 QSS 重新生效。

口径来源：02_界面设计方案 §4——深色底 #16202a 系；报警红 #b3261e／通过绿 #1c7c43／
预警黄；正文≥14px、步骤标题16px、主按钮文字16px粗体、按钮高≥40px；状态=颜色+图标+文字。
"""

from __future__ import annotations

from string import Template

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# 设计 token：颜色与尺寸为唯一真值，QSS 与量测汇报都引这里（单位 px）。
TOKENS: dict[str, str] = {
    "bg_deep": "#16202a",       # 主背景（车间反光环境的深色底）
    "bg_top": "#101a23",        # 顶栏
    "bg_panel": "#1d2a36",      # 左树栏 / 右上下文栏
    "bg_card": "#22303d",       # 卡片 / 占位页
    "border": "#2c3d4d",        # 分隔边框
    "text": "#e6edf3",          # 正文
    "text_dim": "#9fb0bd",      # 次要文字
    "accent": "#2f6feb",        # 当前步高亮（蓝）
    "ok": "#1c7c43",            # 通过绿
    "warn": "#d9a521",          # 预警黄
    "deny": "#b3261e",          # 报警红
    "off_bg": "#1a242e",        # 置灰背景
    "off_text": "#5a6875",      # 置灰文字
    "body_px": "14",            # 正文 ≥14px
    "step_px": "16",            # 步骤标题 16px
    "btn_px": "16",             # 主按钮文字 16px
    "btn_h": "40",              # 按钮高 ≥40px
}

# 用 string.Template（占位符 $name）而非 format/f-string：QSS 满是 {}，
# 而 QSS 不出现 $，故 Template 不需要转义任何花括号。
_QSS = Template(
    """
    * { font-family: "Microsoft YaHei", "Segoe UI", sans-serif; }

    QWidget {
        background-color: $bg_deep;
        color: $text;
        font-size: ${body_px}px;
    }

    /* ---- 顶栏 ---- */
    #TopBar { background-color: $bg_top; border-bottom: 1px solid $border; }
    #AppTitle { font-size: ${step_px}px; font-weight: bold; color: $text; }

    /* ---- 步骤条：三态用动态属性 state=current/done/off ---- */
    #StepBar { background-color: $bg_top; }
    QPushButton[step="true"] {
        background-color: $bg_card; color: $text_dim;
        border: 1px solid $border; border-radius: 6px;
        min-height: ${btn_h}px; padding: 4px 12px;
        font-size: ${step_px}px; text-align: left;
    }
    QPushButton[step="true"][state="current"] {
        background-color: $accent; color: #ffffff; border-color: $accent; font-weight: bold;
    }
    QPushButton[step="true"][state="done"] {
        background-color: $bg_card; color: $text; border-color: $ok;
    }
    QPushButton[step="true"][state="off"] {
        background-color: $off_bg; color: $off_text; border-color: $border;
    }
    QPushButton[step="true"]:hover:!disabled { border-color: $accent; }

    /* ---- 左树栏 / 右上下文栏 ---- */
    #LeftPane, #RightPane { background-color: $bg_panel; }
    #LeftPane { border-right: 1px solid $border; }
    #RightPane { border-left: 1px solid $border; }
    #PaneTitle { font-size: ${step_px}px; font-weight: bold; color: $text; }
    #PlaceholderCard {
        background-color: $bg_card; border: 1px solid $border; border-radius: 8px;
    }
    #PlaceholderTitle { font-size: ${step_px}px; font-weight: bold; color: $text; }
    #PlaceholderBody { color: $text_dim; }

    /* ---- 主按钮：占右栏整宽、16px 粗体、高 ≥40px ---- */
    QPushButton[role="primary"] {
        background-color: $accent; color: #ffffff; border: none; border-radius: 6px;
        min-height: ${btn_h}px; font-size: ${btn_px}px; font-weight: bold;
    }
    QPushButton[role="primary"]:disabled { background-color: $off_bg; color: $off_text; }
    QPushButton[role="primary"]:hover:!disabled { background-color: #3d7bf5; }

    /* ---- 普通按钮 ---- */
    QPushButton {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-radius: 6px; min-height: ${btn_h}px; padding: 4px 12px;
    }
    QPushButton:hover:!disabled { border-color: $accent; }
    QPushButton:disabled { background-color: $off_bg; color: $off_text; }

    /* ---- 工作模式选择器 / 下拉 ---- */
    QComboBox {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-radius: 6px; min-height: 32px; padding: 2px 8px;
    }
    QComboBox QAbstractItemView {
        background-color: $bg_card; color: $text; selection-background-color: $accent;
    }

    /* ---- 模式徽标 / 在线灯：颜色+文字双通道 ---- */
    QLabel[badge="sim"] { color: #ffffff; background-color: $accent;
        border-radius: 4px; padding: 2px 8px; font-weight: bold; }
    QLabel[badge="live"] { color: #ffffff; background-color: $ok;
        border-radius: 4px; padding: 2px 8px; font-weight: bold; }
    QLabel[online="true"] { color: $ok; font-weight: bold; }
    QLabel[online="false"] { color: $off_text; }

    /* ---- 底部状态栏 ---- */
    #StatusBar { background-color: $bg_top; border-top: 1px solid $border; }
    #LogLine { color: $text; }
    #FreqBadge { color: $text_dim; }
    #VersionLabel { color: $text_dim; }

    /* ---- 折叠按钮 ---- */
    QPushButton[collapse="true"] {
        background-color: transparent; border: none; color: $text_dim; min-height: 24px;
    }
    """
)


def build_qss() -> str:
    """返回渲染后的全局 QSS 字符串（token 注入完成）。"""
    return _QSS.substitute(TOKENS)


def apply_theme(app: QApplication) -> None:
    """把全局样式表与默认字体设到 QApplication 上（外壳启动时调用一次）。"""
    app.setStyleSheet(build_qss())
    font = QFont("Microsoft YaHei")
    font.setPixelSize(int(TOKENS["body_px"]))
    app.setFont(font)
