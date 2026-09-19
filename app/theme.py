"""全局视觉 token 与 Qt 样式表的唯一定义处（01 对齐蓝图 V1.2 §4 三表落地，T11）。

铁律：字号、按钮规格、配色一律在此集中定义，其他模块**禁散写**内联样式；
需要按状态变色时用 Qt 动态属性（property）配合本表的属性选择器，并在切换属性后
调用 style().unpolish(w)/polish(w) 让 QSS 重新生效。字体同源：正文=SANS_FAMILIES、
数值读数=mono_font()／`[mono="true"]` 选择器（等宽数字的 Qt 近似），界面代码禁散写字体名。

口径来源：`对齐任务包/01_对齐蓝图_V1.0.md` §4（内部 V1.2）——A 颜色／B 尺寸与字号／
C 圆角分层三表，逐项对应演示稿 RoboPath_HMI_交互演示.html `:root`（HTML:12–35）。
青色 #35d0ff 为唯一强调色，主按钮/选中态青底配深字 #08161c；正文 13px、常规控件高
26px（紧凑 21px）、圆角分层（模态 8／控件 5／小控件 4／胶囊 999／卡片 0）。
wide 档 ×1.56 由 T12 读 `fs_wide` 实现，本表只落 std 档字面值。
⛔ 数值不得取自 `前端任务包/02_界面设计方案` §4（其现行 V2.0 §4 与本表一致；升版前旧稿数值已被演示稿覆盖，仍以本蓝图为准）。
"""

from __future__ import annotations

from string import Template

from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication

# 字体链（演示稿 --sans/--mono，HTML:18–19；Qt 无 system-ui/ui-monospace，按 Windows 等价族近似）。
SANS_FAMILIES = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI")
MONO_FAMILIES = ("Cascadia Mono", "Consolas", "Courier New")
_SANS_QSS = '"Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI"'
_MONO_QSS = '"Cascadia Mono", "Consolas", "Courier New"'

# 设计 token（01 蓝图 §4-A/B/C 逐行；std 档字面值，单位 px；圆角分层 ⛔ 不是一个 8px 通吃）。
TOKENS: dict[str, str] = {
    # ---- A 颜色（演示稿变量名注在行尾）----
    "bg_deep": "#101317",      # 主背景（--bg-0）
    "bg_top": "#161a20",       # 顶栏/底栏（--bg-1）
    "bg_panel": "#1c222a",     # 左树栏 / 右上下文栏（--bg-2）
    "bg_card": "#232a34",      # 卡片 / 输入面（--bg-3）
    "border": "#2c3440",       # 分隔边框（--line）
    "border2": "#3a4553",      # 强边框/hover 边（--line-2）
    "text": "#dfe6ef",         # 正文（--txt）
    "text_dim": "#93a1b3",     # 次要文字（--txt-2）
    "text_faint": "#64748b",   # 最弱文字/单位（--txt-3）
    "accent": "#35d0ff",       # 唯一强调色：青（--cyan）
    "accent_deep": "#0d7fa8",  # 青的深档：边框/hover 用（--cyan-d）
    "on_accent": "#08161c",    # 青底上的文字（青底深字，非白字）
    "ok": "#35e08a",           # 通过绿（--green）
    "warn": "#f5b544",         # 预警黄（--amber）
    "deny": "#ff4d4d",         # 报警红（--red，仅报警/禁止）
    "off_bg": "#1a242e",       # 置灰背景（沿用：演示稿禁用态 opacity，Qt 无等价物）
    "off_text": "#5a6875",     # 置灰文字（同上沿用）
    "canvas": "#d9e2ea",       # 视口画布浅底（--canvas；渲染值同步 view/js/loader.js BG）
    # ---- B 尺寸与字号（std 档；wide 档＝×fs_wide，由 T12 实现倍率）----
    "body_px": "13",           # 正文基准（演示稿 .app 13px）
    "btn_h": "26",             # 常规控件高（--ctl）
    "btn_h_s": "21",           # 紧凑控件高（--ctl-s）
    "step_px": "14.5",         # 品牌名级标题（卡片标题 h3 用 body_px）
    "btn_px": "12",            # 按钮文字（.btn.tiny 用 11.5）
    "topbar_h": "56",          # 顶栏高
    "status_h": "32",          # 底栏高
    "tab_h": "36",             # 左栏页签头高
    "tree_row_h": "23",        # 装配树行高
    "s1": "4",                 # 节奏间距 s1..s4（--s1..--s4）
    "s2": "8",
    "s3": "12",
    "s4": "16",
    "fs_wide": "1.56",         # wide 档统一倍率（T12 读取，本单不实现缩放）
    # ---- C 圆角分层 ----
    "r_modal": "8",            # 模态／浮层
    "r_card": "0",             # 卡片/面板：演示稿 .card 只有 border-bottom，无圆角
    "r_ctl": "5",              # 常规控件（按钮/输入/下拉/芯片/灯/头像，--ctr）
    "r_ctl_s": "4",            # 小控件（tiny 钮/图标钮/开关/表内钮）
    "r_pill": "999",           # 徽标胶囊（顶栏菜单徽标）
    "r_tab_badge": "8",        # 页签徽标（近胶囊）
}

# 用 string.Template（占位符 $name）而非 format/f-string：QSS 满是 {}，
# 而 QSS 不出现 $，故 Template 不需要转义任何花括号。
_QSS = Template(
    """
    * { font-family: $sans; }
    *[mono="true"] { font-family: $mono; }

    QWidget {
        background-color: $bg_deep;
        color: $text;
        font-size: ${body_px}px;
    }

    /* ---- 顶栏 ---- */
    #TopBar { background-color: $bg_top; border-bottom: 1px solid $border; }
    #AppTitle { font-size: ${step_px}px; font-weight: 600; color: $text; }

    /* ---- 步骤条：三态用动态属性 state=current/done/off ---- */
    #StepBar { background-color: $bg_top; }
    QPushButton[step="true"] {
        background-color: $bg_card; color: $text_dim;
        border: 1px solid $border; border-radius: ${r_ctl}px;
        min-height: ${btn_h}px; padding: ${s1}px ${s3}px;
        font-size: ${step_px}px; text-align: left;
    }
    QPushButton[step="true"][state="current"] {
        background-color: $accent; color: $on_accent; border-color: $accent; font-weight: 600;
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
    #PaneTitle { font-size: ${body_px}px; font-weight: 600; color: $text; }
    #PlaceholderCard {
        background-color: $bg_card; border: 1px solid $border; border-radius: ${r_card}px;
    }
    #PlaceholderTitle { font-size: ${body_px}px; font-weight: 600; color: $text; }
    #PlaceholderBody { color: $text_dim; }

    /* ---- 左栏装配树 ---- */
    QTreeWidget {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-radius: ${r_card}px; outline: none;
    }
    QTreeWidget::item { min-height: ${tree_row_h}px; }
    QTreeWidget::item:hover { background-color: $border; }
    QTreeWidget::item:selected { background-color: $accent; color: $on_accent; }
    QHeaderView::section {
        background-color: $bg_panel; color: $text_dim; border: none; padding: ${s1}px ${s2}px;
    }

    /* ---- 步骤①导入结果行：实体绿 / 面片红 / 进行中灰（颜色+文字双通道） ---- */
    QLabel[result="brep"] { color: $ok; font-weight: bold; }
    QLabel[result="mesh"] { color: $deny; font-weight: bold; }
    QLabel[result="busy"] { color: $text_dim; }

    /* ---- 步骤①三阶段进度条 ---- */
    QProgressBar {
        background-color: $off_bg; border: 1px solid $border; border-radius: ${r_ctl}px;
        text-align: center; color: $text; min-height: ${btn_h_s}px;
    }
    QProgressBar::chunk { background-color: $accent; border-radius: ${r_ctl_s}px; }

    /* ---- 主按钮：青底深字（演示稿 .btn.primary），高 26px、12px 粗体 ---- */
    QPushButton[role="primary"] {
        background-color: $accent; color: $on_accent; border: none; border-radius: ${r_ctl}px;
        min-height: ${btn_h}px; font-size: ${btn_px}px; font-weight: bold;
    }
    QPushButton[role="primary"]:disabled { background-color: $off_bg; color: $off_text; }
    QPushButton[role="primary"]:hover:!disabled { background-color: $accent_deep; }

    /* ---- 普通按钮 ---- */
    QPushButton {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-radius: ${r_ctl}px; min-height: ${btn_h}px;
        padding: ${s1}px ${s3}px; font-size: ${btn_px}px;
    }
    QPushButton:hover:!disabled { border-color: $accent_deep; }
    QPushButton:disabled { background-color: $off_bg; color: $off_text; }

    /* ---- 左栏三页签（T13 范式）：动态属性 state=current/todo ——
       T13 建件时本表冻结无法配样式，指挥侧 2026-09-19 补（页签头高＝tab_h 令牌） ---- */
    QPushButton[state="current"] {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-bottom: 2px solid $accent; min-height: ${tab_h}px;
        padding: ${s1}px ${s3}px; font-size: ${body_px}px; border-radius: ${r_ctl_s}px;
    }
    QPushButton[state="todo"] {
        background-color: $bg_panel; color: $text_dim; border: 1px solid transparent;
        min-height: ${tab_h}px; padding: ${s1}px ${s3}px; font-size: ${body_px}px;
        border-radius: ${r_ctl_s}px;
    }

    /* ---- 工作模式选择器 / 下拉 ---- */
    QComboBox {
        background-color: $bg_card; color: $text; border: 1px solid $border;
        border-radius: ${r_ctl}px; min-height: ${btn_h}px; padding: ${s1}px ${s2}px;
    }
    QComboBox QAbstractItemView {
        background-color: $bg_card; color: $text;
        selection-background-color: $accent; selection-color: $on_accent;
    }

    /* ---- 模式徽标（胶囊，青/绿底配深字）/ 在线灯：颜色+文字双通道 ---- */
    QLabel[badge="sim"] { color: $on_accent; background-color: $accent;
        border-radius: ${r_pill}px; padding: ${s1}px ${s2}px; font-weight: 600; }
    QLabel[badge="live"] { color: $on_accent; background-color: $ok;
        border-radius: ${r_pill}px; padding: ${s1}px ${s2}px; font-weight: 600; }
    QLabel[online="true"] { color: $ok; font-weight: bold; }
    QLabel[online="false"] { color: $off_text; }

    /* ---- 着色文字：动态属性 tone → 语义色（「颜色＋图标＋文字」三通道里的颜色通道） ----
       ⚠️ 必须走 QSS 属性选择器、⛔ 不用 setPalette：全局 QSS 只要给了 color（连上面 `QWidget {}`
       那条通配都算），Qt 就按样式表算调色板、**忽略**手工 setPalette 的那份——T10 已实测：
       用调色板着色的标签渲染出来仍是 $text_dim／$text（见 T10 交付汇报的发现项）。 */
    QLabel[tone="ok"] { color: $ok; font-weight: bold; }
    QLabel[tone="warn"] { color: $warn; font-weight: bold; }
    QLabel[tone="deny"] { color: $deny; font-weight: bold; }
    QLabel[tone="accent"] { color: $accent; font-weight: bold; }
    QLabel[tone="dim"] { color: $text_dim; }

    /* ---- 底部状态栏（频率角标＝数值读数，走等宽字体）---- */
    #StatusBar { background-color: $bg_top; border-top: 1px solid $border; }
    #LogLine { color: $text; }
    #FreqBadge { color: $text_dim; font-family: $mono; }
    /* 数据频率角标：实测低于标称一半即变黄（卡片步骤②；由 app/livectl.py 置 hz 属性）。
       必须排在上面那条基础规则**之后**，免得层叠顺序让灰盖掉黄。 */
    #FreqBadge[hz="low"] { color: $warn; font-weight: bold; }
    #VersionLabel { color: $text_dim; }

    /* ---- 折叠按钮 ---- */
    QPushButton[collapse="true"] {
        background-color: transparent; border: none; color: $text_dim; min-height: ${btn_h_s}px;
    }
    """
)


def build_qss() -> str:
    """返回渲染后的全局 QSS 字符串（token＋字体链注入完成）。"""
    return _QSS.substitute({**TOKENS, "sans": _SANS_QSS, "mono": _MONO_QSS})


def base_font() -> QFont:
    """正文默认字体：--sans 链（Microsoft YaHei UI 系）＋13px（01 蓝图 §4-B）。"""
    font = QFont()
    font.setFamilies(SANS_FAMILIES)
    font.setPixelSize(int(TOKENS["body_px"]))
    return font


def mono_font() -> QFont:
    """数值读数等宽字体：--mono 链（Cascadia Mono/Consolas 系）。

    Qt 无 font-variant-numeric，等宽数字（tabular-nums）以等宽字体族近似；
    setStyleHint 保证三族全 miss 时仍回落系统等宽，不会散落成比例字体。
    """
    font = QFont()
    font.setFamilies(MONO_FAMILIES)
    font.setStyleHint(QFont.StyleHint.Monospace, QFont.StyleStrategy.PreferQuality)
    font.setPixelSize(int(TOKENS["body_px"]))
    return font


def apply_theme(app: QApplication) -> None:
    """把全局样式表与默认字体设到 QApplication 上（外壳启动时调用一次）。"""
    app.setStyleSheet(build_qss())
    app.setFont(base_font())
