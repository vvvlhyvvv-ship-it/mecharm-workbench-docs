"""顶栏（01 蓝图 §3.3 七区；T13 重构件）。

从左到右：①品牌区（LOGO 占位＋brand_name＋brand_sub，全读 ui.yaml ⛔ 零字面量）②菜单按钮组
（三维导入·徽标＝件数｜装配体模式·禁用｜测量·禁用｜报警与日志·徽标位留接口）③使能按钮（Δ-11
恒禁用＋「待契约回执」，app/chips.py）④数据芯片三枚（app/chips.py）⑤灯组（ModeBadge 仿真/联动
＋OnlineLight 链路＋VerdictLamp 轨迹判定）⑥用户盒（头像字＋姓名＋工号＋走时日期时间＋「退出」）。
**没有**模式组（Δ-1：三模式归 PLC）与「21:9 预览」钮（Δ-8）。

挂点预埋（T13 卡步骤 8）：``import_requested`` 信号——T14 连接即替换默认「待后续版本」提示框，
**不回改本件**；``set_alarm_count`` 留给 T16 接数。退出＝``logout_requested``（shell 回登录页）。
颜色/字号一律走 app.theme 全局 QSS，本模块不写内联样式。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtCore import QTimer, Signal
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app.chips import DASH, EnableButton, StatChips, VerdictLamp
from app.mode import ModeBadge, OnlineLight
from app.theme import TOKENS
from core.config.ui_config import UiConfig

LATER_NOTE = "待后续版本"           # 期 3 功能的禁用提示（Δ-7）


class TopBar(QWidget):
    """顶栏七区。品牌/用户身份只读 ui.yaml；徽标数值由外壳按内核真值回填。"""

    import_requested = Signal()
    logout_requested = Signal()

    def __init__(self, ui: UiConfig, badge: ModeBadge, light: OnlineLight,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("TopBar")
        self.setFixedHeight(int(TOKENS["topbar_h"]))
        self._ui = ui
        row = QHBoxLayout(self)
        row.setContentsMargins(12, 0, 12, 0)
        row.setSpacing(10)

        # ① 品牌区：LOGO 占位（品牌名首字）＋名称＋副标
        logo = QLabel(ui.brand_name[:1])
        logo.setProperty("tone", "accent")
        brand = QVBoxLayout()
        brand.setSpacing(0)
        self._brand_name = QLabel(ui.brand_name)
        self._brand_name.setObjectName("AppTitle")
        self._brand_sub = QLabel(ui.brand_sub)
        self._brand_sub.setProperty("tone", "dim")
        brand.addWidget(self._brand_name)
        brand.addWidget(self._brand_sub)
        row.addWidget(logo)
        row.addLayout(brand)
        row.addWidget(_vdiv())

        # ② 菜单按钮组（无模式组 Δ-1、无 21:9 预览 Δ-8）
        self._import_btn = QPushButton("三维导入")
        self._import_btn.clicked.connect(self.import_requested.emit)
        # 默认无浮层：wiring 连 import_requested 弹「待后续版本」；T14 重连该信号即换真浮层
        self._import_badge = QLabel(DASH)
        self._import_badge.setProperty("tone", "dim")
        self._assembly_btn = _disabled_menu("装配体模式")
        self._measure_btn = _disabled_menu("测量")
        self._alarm_btn = _disabled_menu("报警与日志")
        self._alarm_badge = QLabel(DASH)               # 徽标位留接口，T16 接数
        self._alarm_badge.setProperty("tone", "dim")
        for w in (self._import_btn, self._import_badge, self._assembly_btn,
                  self._measure_btn, self._alarm_btn, self._alarm_badge):
            row.addWidget(w)
        row.addWidget(_vdiv())

        # ③④⑤ 右半区：使能钮（Δ-11）＋芯片＋灯组（ModeBadge/OnlineLight 由外壳传入）
        self._enable = EnableButton()
        self.chips = StatChips()
        self.verdict = VerdictLamp()
        self.badge, self.light = badge, light
        for w in (self._enable, self.chips, badge, light, self.verdict):
            row.addWidget(w)
        row.addWidget(_vdiv())

        # ⑥ 用户盒：头像字＋姓名·工号＋走时日期时间＋退出
        self._avatar = QLabel(ui.login_name_default[:1])
        self._avatar.setProperty("tone", "accent")
        user = QVBoxLayout()
        user.setSpacing(0)
        self._user_name = QLabel(ui.login_name_default)
        self._user_no = QLabel(f"工号 {ui.login_user_default}")
        self._user_no.setProperty("tone", "dim")
        self._clock = QLabel(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        self._clock.setProperty("mono", "true")
        self._clock.setProperty("tone", "dim")
        user.addWidget(self._user_name)
        user.addWidget(self._user_no)
        user.addWidget(self._clock)
        self._logout = QPushButton("退出")
        self._logout.clicked.connect(self.logout_requested.emit)
        row.addWidget(self._avatar)
        row.addLayout(user)
        row.addWidget(self._logout)
        row.addStretch(1)
        self._ticker = QTimer(self)                    # 走时时钟（数据刷新类，不受 motion_enabled 约束）
        self._ticker.timeout.connect(self._tick_clock)
        self._ticker.start(1000)

    # --- 外壳回填 -------------------------------------------------------------- #
    def set_import_count(self, count: int) -> None:
        self._import_badge.setText(str(count))

    def set_alarm_count(self, count: int | None) -> None:
        self._alarm_badge.setText(DASH if count is None else str(count))

    def set_user(self, user: str, name: str) -> None:
        """进入系统时以登录页实值回填（可改；预填来自 ui.yaml）。"""
        self._user_name.setText(name)
        self._user_no.setText(f"工号 {user}")
        self._avatar.setText(name[:1])

    def _tick_clock(self) -> None:
        self._clock.setText(datetime.now().strftime("%Y-%m-%d %H:%M:%S"))


def _disabled_menu(text: str) -> QPushButton:
    btn = QPushButton(text)
    btn.setEnabled(False)
    btn.setToolTip(LATER_NOTE)
    return btn


def _vdiv() -> QFrame:
    line = QFrame()
    line.setFrameShape(QFrame.Shape.VLine)
    line.setFrameShadow(QFrame.Shadow.Plain)
    line.setFixedWidth(1)
    return line
