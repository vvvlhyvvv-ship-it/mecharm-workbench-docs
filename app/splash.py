"""载入页＋登录页（同一构图两态，原地切换不另开窗——裁决 9；T12）。

载入态＝真实初始化日志逐行打钩＋进度条（值＝已完成里程碑占比，⛔ 禁假进度匀速走满）；
登录三件套**渲染但禁用**＋提示原文「载入中：登录入口将在初始化完成后出现」（HTML:702）。
就绪态＝日志区收起、登录三件套原地启用（预填可改、不校验口令）。装饰性动效（当前行
游标闪烁）受 ui.yaml ``motion_enabled`` 约束——关＝静止但日志照走（蓝图 §1-11）。
里程碑只报真实发生的步骤（``BootMilestones``）：ICU 计时由 run.py 在 QApplication
之前测好、经 ``PRE_QT`` 回填（⛔ 不得编造）；「视口就绪」取 ``ViewPane.loadFinished``。
演示稿 5 行里的「双视口同帧」「22 轴 / 活动 9」「26 节点」是演示字样 ⇒ 一律真实口径
（Δ-6）。文案全读 ui.yaml、零身份字面量（蓝图 §1-8）；恒 1920×1080 逻辑构图，
由 StageHost 等比缩放（``set_factor``）。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton,
                               QProgressBar, QVBoxLayout, QWidget)

from core.config.ui_config import UiConfig

Center = Qt.AlignmentFlag.AlignHCenter
PRE_QT: dict[str, float] = {}   # run.py 在 QApplication 前记的真实计时；缺键＝该步未测到

BOOT_STEPS: tuple[tuple[str, str], ...] = (
    ("icu", "ICU 预载与入口引导"),
    ("config", "配置加载"),
    ("nodes", "点表校验"),
    ("cache", "缓存目录就绪"),
    ("viewport", "视口就绪"),
)
HINT_LOADING = "载入中：登录入口将在初始化完成后出现"
HINT_READY = "输入完成后回车或点击「进入系统」"


def _repolish(widget: QWidget) -> None:
    """动态属性（tone）变更后让 QSS 属性选择器重新生效（app/theme.py 的既定手法）。"""
    style = widget.style()
    style.unpolish(widget)
    style.polish(widget)


class BootMilestones(QObject):
    """启动里程碑收集器：只登记真实发生并完成的步骤，驱动进度条与逐行打钩。"""

    updated = Signal()
    all_done = Signal()

    def __init__(self, steps: tuple[tuple[str, str], ...]) -> None:
        super().__init__()
        self._labels = dict(steps)
        self._keys = tuple(key for key, _ in steps)
        self._state = {key: "pending" for key in self._keys}
        self._detail: dict[str, str] = {}

    def keys(self) -> tuple[str, ...]: return self._keys
    def total(self) -> int: return len(self._keys)
    def done_count(self) -> int: return sum(1 for k in self._keys if self._state[k] == "done")
    def is_all_done(self) -> bool: return all(self._state[k] == "done" for k in self._keys)
    def state(self, key: str) -> str: return self._state.get(key, "pending")
    def label(self, key: str) -> str: return self._labels.get(key, key)
    def detail(self, key: str) -> str: return self._detail.get(key, "")

    def begin(self, key: str) -> None:
        if key in self._state and self._state[key] == "pending":
            self._state[key] = "current"
            self.updated.emit()

    def mark(self, key: str, detail: str = "") -> None:
        """一个真实步骤完成：记时刻/读数并打钩（detail 里的数字必须是真的）。"""
        if key not in self._state:
            return
        self._state[key] = "done"
        self._detail[key] = detail
        self.updated.emit()
        if self.is_all_done():
            self.all_done.emit()


class SplashPane(QWidget):
    """载入/登录两态页（恒 1920×1080 逻辑构图；entered＝「进入系统」）。"""

    entered = Signal(str, str)

    def __init__(self, ui: UiConfig, boot: BootMilestones | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._ui = ui
        self._boot = boot or BootMilestones(())
        self._ready = False
        self._factor = 1.0
        self._fonts: list[tuple[QObject, float, bool]] = []
        self._build()
        self._boot.updated.connect(self._refresh)
        self._blink = QTimer(self) if ui.motion_enabled else None   # §1-11：动效可关
        if self._blink:
            self._blink.setInterval(600)
            self._blink.timeout.connect(self._on_blink)
            self._blink.start()
        self._refresh()

    # --- 构图（1920×1080 逻辑；字号/固定尺寸随 set_factor 等比） ---------------- #
    def _label(self, text: str, px: float, *, mono: bool = False,
               tone: str | None = None) -> QLabel:
        lab = QLabel(text)
        lab.setAlignment(Center)
        if tone:
            lab.setProperty("tone", tone)
        self._register_font(lab, px, mono)
        return lab

    def _build(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(60, 48, 60, 40)
        root.addStretch(3)
        center = QVBoxLayout()
        center.setSpacing(10)
        self._logo = QFrame()
        self._logo.setObjectName("PlaceholderCard")
        self._logo.setFixedSize(96, 96)
        box = QVBoxLayout(self._logo)
        box.addWidget(self._label("LOGO", 12))
        center.addWidget(self._logo, 0, Center)
        self._company = self._label(self._ui.company, 22)
        self._company_en = self._label(self._ui.company_en, 12, mono=True)
        self._sysname = self._label(self._ui.system_name, 26)
        self._syssub = self._label(f"{self._ui.brand_name}　·　招标编号 {self._ui.bid_no}", 13)
        for w in (self._company, self._company_en, self._sysname, self._syssub):
            center.addWidget(w)
        center.addSpacing(24)
        self._bootlog = self._build_bootlog()
        center.addWidget(self._bootlog, 0, Center)
        self._login = self._build_login()
        center.addWidget(self._login, 0, Center)
        root.addLayout(center)
        root.addStretch(4)
        root.addLayout(self._build_footer())

    def _build_bootlog(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PlaceholderCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(18, 14, 18, 14)
        box.setSpacing(6)
        self._rows: list[tuple[QLabel, QLabel, QLabel]] = []
        for key in self._boot.keys():
            icon = self._label("·", 13, mono=True, tone="dim")
            text = self._label(self._boot.label(key), 13, mono=True)
            detail = self._label("", 13, mono=True, tone="dim")
            row = QHBoxLayout()
            row.setSpacing(10)
            for w in (icon, text, detail):
                row.addWidget(w)
            box.addLayout(row)
            self._rows.append((icon, text, detail))
        return card

    def _build_login(self) -> QFrame:
        card = QFrame()
        card.setObjectName("PlaceholderCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(20, 16, 20, 12)
        box.setSpacing(10)
        row = QHBoxLayout()
        row.setSpacing(12)
        self._user = QLineEdit(self._ui.login_user_default)
        self._name = QLineEdit(self._ui.login_name_default)
        self._enter = QPushButton("进 入 系 统")
        self._enter.setProperty("role", "primary")
        for text, field in (("工 号", self._user), ("姓 名", self._name)):
            field.setFixedWidth(210)
            self._register_font(field, 13)
            row.addWidget(self._label(text, 13))
            row.addWidget(field)
        self._register_font(self._enter, 13)
        row.addSpacing(8)
        row.addWidget(self._enter)
        box.addLayout(row)
        self._hint = self._label(HINT_LOADING, 12, tone="dim")
        box.addWidget(self._hint)
        self._enter.clicked.connect(self._emit_enter)
        for field in (self._user, self._name):
            field.returnPressed.connect(self._emit_enter)
        self._set_login_enabled(False)
        return card

    def _build_footer(self) -> QVBoxLayout:
        foot = QVBoxLayout()
        foot.setSpacing(6)
        bar_row = QHBoxLayout()
        bar_row.setAlignment(Center)
        bar_row.setSpacing(14)
        self._pct = self._label("0%", 12, mono=True)
        self._phase = self._label("初始化", 12)
        self._bar = QProgressBar()
        self._bar.setFixedWidth(480)
        self._bar.setRange(0, 100)
        for w in (self._pct, self._bar, self._phase):
            bar_row.addWidget(w)
        self._status = self._label("正在初始化", 13)
        self._verline = self._label(f"{self._ui.version_text}　·　{self._ui.bidder_note}",
                                    11, mono=True, tone="dim")
        foot.addLayout(bar_row)
        for w in (self._status, self._verline):
            foot.addWidget(w)
        return foot

    # --- 状态与刷新 ------------------------------------------------------------ #
    def _set_login_enabled(self, on: bool) -> None:
        for w in (self._user, self._name, self._enter):
            w.setEnabled(on)

    def _refresh(self) -> None:
        self._bootlog.setVisible(self._boot.total() > 0 and not self._ready)
        for (icon, text, detail), key in zip(self._rows, self._boot.keys()):
            state = self._boot.state(key)
            icon.setProperty("tone", {"done": "ok", "current": "accent"}.get(state, "dim"))
            icon.setText({"done": "✓", "current": "▸"}.get(state, "·"))
            text.setProperty("tone", "dim" if state == "pending" else None)
            detail.setText(self._boot.detail(key))
            for w in (icon, text, detail):
                _repolish(w)
        done = self._boot.total() and round(100 * self._boot.done_count() / self._boot.total())
        self._bar.setValue(done or 0)
        self._pct.setText(f"{self._bar.value()}%")
        if not self._ready:
            self._status.setText(f"正在初始化（{self._boot.done_count()}/{self._boot.total()})")

    def _on_blink(self) -> None:
        """当前行游标闪烁（唯一装饰性动效；motion_enabled=false 时定时器不启动）。"""
        if self._ready:
            return
        for (icon, _text, _detail), key in zip(self._rows, self._boot.keys()):
            if self._boot.state(key) == "current":
                icon.setText("·" if icon.text() == "▸" else "▸")
                _repolish(icon)

    def set_ready_state(self, complete: bool = True) -> None:
        """就地绪态：日志区收起、登录三件套启用（complete＝里程碑是否全部完成）。"""
        if self._ready:
            return
        self._ready = True
        for field, default in ((self._user, self._ui.login_user_default),
                               (self._name, self._ui.login_name_default)):
            if not field.text():
                field.setText(default)
        self._set_login_enabled(True)
        self._hint.setText(HINT_READY)
        self._bar.setValue(100)
        self._pct.setText("100%")
        self._phase.setText("就绪")
        self._status.setText("● 系统就绪 · 请使用工号与姓名登录" if complete
                             else "初始化未全部完成，可先进入系统（剩余项在后台继续）")
        self._refresh()

    def is_ready(self) -> bool:
        return self._ready

    def _emit_enter(self) -> None:
        if not self._ready:
            return
        self.entered.emit(self._user.text().strip() or self._ui.login_user_default,
                          self._name.text().strip() or self._ui.login_name_default)

    # --- 对外读数（e2e/取证核对用） -------------------------------------------- #
    def login_values(self) -> tuple[str, str]:
        return self._user.text().strip(), self._name.text().strip()

    def identity_texts(self) -> list[str]:
        """画面上承载身份信息的字符串（取证档判据扫这些，⛔ 不另立读数口）。"""
        return [self._company.text(), self._company_en.text(), self._syssub.text(), self._verline.text()]

    # --- 等比缩放（由 StageHost 驱动） ------------------------------------------ #
    def _register_font(self, widget: QObject, px: float, mono: bool = False) -> None:
        self._fonts.append((widget, px, mono))
        self._apply_font(widget, px, mono)

    def _apply_font(self, widget: QObject, px: float, mono: bool) -> None:
        font = QFont(widget.font())          # 家族继承应用字体（T11 换字体链后自动跟随）
        font.setPixelSize(max(1, round(px * self._factor)))
        if mono:
            font.setStyleHint(QFont.StyleHint.Monospace)
        widget.setFont(font)

    def set_factor(self, factor: float) -> None:
        """按舞台等比系数重设字号与固定尺寸（登录页恒 1920×1080 逻辑构图）。"""
        if abs(factor - self._factor) < 1e-4:
            return
        self._factor = factor
        for widget, px, mono in self._fonts:
            self._apply_font(widget, px, mono)
        self._logo.setFixedSize(round(96 * factor), round(96 * factor))
        self._bar.setFixedWidth(round(480 * factor))
        for field in (self._user, self._name):
            field.setFixedWidth(round(210 * factor))
