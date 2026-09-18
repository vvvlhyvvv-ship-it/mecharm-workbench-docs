"""舞台与缩放（01 蓝图 §5 的 Qt 侧落地，T12）。

「固定逻辑尺寸＋等比缩放」的形态：窗口按宽高比选档（≥2.0 → wide，否则 std；
``--stage`` 可强制，ui.yaml ``stage_default`` 给默认），载入/登录页恒 login 档
1920×1080、**不参与 wide**（演示稿 HTML:747 口径）——带鱼屏上登入画面仍按 16:9
出图、四周留边填 ``#0b0d10``。

缩放分两层（蓝图 §5 关键口径）：
  ① 原生控件＝T11 的尺寸/字号令牌 × ``--fs``，由 Qt 布局吃（本件只给出 fs 值，
     左/右栏宽取字面 px：365/384 ↔ 460/490，⛔ 不复刻演示稿 clamp 公式——Qt 无
     vw 单位，逻辑尺寸固定后三候选值恒定，取字面值即等价）；
  ② WebEngine 视口 **不参与 Qt 侧位图缩放**（否则 WebGL 被拉伸发虚）——视口内
     HTML 的 ``--fs`` 由壳层经 ``app/bridge.py:54`` 同一条 ``runJavaScript`` 通道
     直接写 CSS 变量（不是 bridge 消息、不占 dispatch type；推送在 app/shell.py）。

wide 档倍率读 ``app.theme.TOKENS["fs_wide"]``（T11 落令牌）；T11 未合并时回退
蓝图 §2 表的字面值，两版本 theme.py 均可运行。
"""

from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QRect, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget

from app.theme import TOKENS

WIDE_RATIO = 2.0            # 窗口宽高比 ≥2.0 选 wide 档（蓝图 §5 选用条件）
LETTERBOX = "#0b0d10"       # 舞台留边底色（演示稿 HTML:38）
MIN_W, MIN_H = 1366, 768    # 主窗最小尺寸（画面 12 口径：小屏等比可显、不裁切）
_LOGIN_PX = (1920, 1080)
_STD_PX = (1920, 1080)
_WIDE_PX = (2560, 1080)


def _fs_wide() -> float:
    """wide 档 ``--fs`` 倍率：优先读 T11 的 ``fs_wide`` 令牌，缺失/坏值回退 1.56。"""
    try:
        return float(TOKENS.get("fs_wide", "1.56"))
    except (TypeError, ValueError):
        return 1.56


@dataclass(frozen=True)
class StageSpec:
    """一档舞台：逻辑尺寸（px）、字号倍率 ``fs``、左右栏字面宽（px）。"""

    key: str
    w: int
    h: int
    fs: float
    left_px: int
    right_px: int

    def label(self) -> str:
        return {"login": "16:9 · 1920×1080（登录档）", "std": "16:9 · 1920×1080",
                "wide": "21:9 · 2560×1080"}[self.key]


SPECS: dict[str, StageSpec] = {
    "login": StageSpec("login", *_LOGIN_PX, 1.0, 365, 384),
    "std": StageSpec("std", *_STD_PX, 1.0, 365, 384),
    "wide": StageSpec("wide", *_WIDE_PX, _fs_wide(), 460, 490),
}


def resolve_stage(page: str, win_w: int, win_h: int, forced: str = "",
                  default: str = "auto") -> str:
    """当前应处的舞台档：登录页恒 login；主界面按强制参数 → ui 默认 → 宽高比。"""
    if page != "workbench":
        return "login"
    if forced in SPECS and forced != "login":
        return forced
    if default in ("std", "wide"):
        return default
    return "wide" if win_w / max(win_h, 1) >= WIDE_RATIO else "std"


class StageHost(QWidget):
    """中央舞台容器：两页（载入/登录＝手工几何等比缩放；主界面＝满幅 Qt 布局）。

    页切换与档位变化都发 ``stage_changed(kind)``，壳层据此重设左右栏宽并给视口
    推 ``--fs``。主界面页不做位图缩放（缩放分两层口径，见模块 docstring）。
    """

    stage_changed = Signal(str)

    def __init__(self, forced: str = "", default: str = "auto",
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._forced = forced
        self._default = default
        self._page = "splash"
        self._kind = "login"
        self._splash: QWidget | None = None
        self._workbench: QWidget | None = None
        self.setAutoFillBackground(False)

    # --- 页管理 -------------------------------------------------------------- #
    def set_splash(self, widget: QWidget) -> None:
        self._splash = widget
        widget.setParent(self)
        widget.show()

    def set_workbench(self, widget: QWidget) -> None:
        self._workbench = widget
        widget.setParent(self)
        widget.hide()

    def page(self) -> str:
        return self._page

    def show_splash(self) -> None:
        self._switch("splash")

    def show_workbench(self) -> None:
        self._switch("workbench")

    def _switch(self, page: str) -> None:
        self._page = page
        if self._workbench is not None:
            self._workbench.setVisible(page == "workbench")
        if self._splash is not None:
            self._splash.setVisible(page == "splash")
        self._relayout()

    # --- 档位与几何 ------------------------------------------------------------ #
    def kind(self) -> str:
        return self._kind

    def spec(self) -> StageSpec:
        return SPECS[self._kind]

    def scale(self) -> float:
        """登录页的等比缩放系数 ``min(w/W, h/H)``（主界面页恒 1.0，不做位图缩放）。"""
        spec = SPECS["login"]
        if self._page != "splash" or self._splash is None:
            return 1.0
        return min(self.width() / spec.w, self.height() / spec.h)

    def _relayout(self) -> None:
        kind = resolve_stage(self._page, self.width(), self.height(),
                             self._forced, self._default)
        if kind != self._kind:
            self._kind = kind
            self.stage_changed.emit(kind)
        if self._workbench is not None:
            self._workbench.setGeometry(QRect(0, 0, self.width(), self.height()))
        if self._splash is not None:
            spec = SPECS["login"]
            factor = self.scale()
            w, h = round(spec.w * factor), round(spec.h * factor)
            x, y = (self.width() - w) // 2, (self.height() - h) // 2
            self._splash.setGeometry(QRect(x, y, w, h))
            scaler = getattr(self._splash, "set_factor", None)
            if scaler is not None:
                scaler(factor)

    def resizeEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        self._relayout()

    def paintEvent(self, event) -> None:  # noqa: N802（Qt 命名）
        painter = QPainter(self)
        painter.fillRect(event.rect(), QColor(LETTERBOX))
        painter.end()
