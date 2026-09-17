"""中部三维视口容器（02 设计方案 §1/§5：WebEngine 内嵌页，加载失败不白屏）。

T02 阶段视口只显示 index.html 渲染的“深色空场景卡”，不接任何几何：
  - 页面背景设为深色，避免加载瞬间白屏；
  - loadFinished(ok=False) → 切到 Qt 侧错误卡并发 load_failed 信号（由 shell 记日志），
    不进白屏死循环（02 §5）。
对外暴露 view()/page() 供 bridge 挂 QWebChannel。

**F4（T02 遗留，T10 派单 §4-雷(b) 点名）已在本件收口**：index.html 的定位不再用
`Path(__file__).parents[1]` 那种「按本文件位置数父目录」的写法，改为 `resource_root()`——
打包态取 PyInstaller 的解包目录、开发态取仓根（理由见该函数 docstring）。
⚠️ 本轮**只交了代码侧修复与模拟 onedir 目录树的用例级证明**；dist 实机启动证明挂在打包单
（本机无任何打包器，加装属 §5 禁改件范围，待授权）——⛔ 不得把用例级证明报成 dist 实测。
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QLabel, QStackedWidget, QVBoxLayout, QWidget

_BG = QColor("#16202a")


def resource_root() -> Path:
    """资源根目录：打包态＝PyInstaller 的解包目录（`sys._MEIPASS`），开发态＝仓根。

    为什么不能沿用 `Path(__file__).resolve().parents[1]`（＝F4）：onedir 打包后本模块被收进 PYZ
    归档，`__file__` 成了**归档内的虚拟路径**，对它数父目录得到的位置与 `--add-data` 实际落地的
    位置不再必然重合 ⇒ 视口加载不到 index.html，dist 起来就是一张错误卡。PyInstaller 的官方口径
    是「资源一律相对 `sys._MEIPASS` 取」，本函数照此实现；开发态没有该属性，回落仓根
    （本文件在 <root>/app/viewpane.py → parents[1] 即仓根，view/ 与 config/ 都在仓根下）。

    ⚠️ **调用期**求值，⛔ 不做模块级常量：常量在 import 期就定死，既没法在用例里换成模拟的 onedir
    目录树来验，也可能算在 PyInstaller 设好 `_MEIPASS` 之前。
    """
    override = getattr(sys, "_MEIPASS", None)
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[1]


def index_html() -> Path:
    """视口首页的绝对路径。

    打包态若该文件不在（`--add-data` 漏了 view/），**照样返回打包态路径**，⛔ 不偷偷回落到开发态
    仓根：回落会把「包没打全」伪装成能跑，且错误卡上印的是一个 dist 里根本不存在的开发路径，把
    打包缺陷指向错误方向（04 §5.5 附7 那一族：看着绿、实则掏空）。让缺失就地暴露。
    """
    return resource_root() / "view" / "index.html"


class ViewPane(QWidget):
    """WebEngine 视口；加载失败显示错误卡。"""

    load_failed = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._view = QWebEngineView()
        self._view.page().setBackgroundColor(_BG)
        self._view.loadFinished.connect(self._on_load_finished)
        self._error = self._make_error_card()
        self._stack = QStackedWidget()
        self._stack.addWidget(self._view)   # index 0 = 正常视口
        self._stack.addWidget(self._error)  # index 1 = 错误卡
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._stack)

    def start(self) -> None:
        """开始加载 index.html；须在 bridge.attach(page) 之后调用，确保 QWebChannel 先就位。"""
        self._view.load(QUrl.fromLocalFile(str(index_html())))

    def _make_error_card(self) -> QWidget:
        card = QFrame()
        card.setObjectName("PlaceholderCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(24, 24, 24, 24)
        title = QLabel("三维视口加载失败")
        title.setObjectName("PlaceholderTitle")
        self._error_body = QLabel("")
        self._error_body.setObjectName("PlaceholderBody")
        self._error_body.setWordWrap(True)
        box.addWidget(title)
        box.addWidget(self._error_body)
        box.addStretch(1)
        return card

    def _on_load_finished(self, ok: bool) -> None:
        if ok:
            self._stack.setCurrentIndex(0)
            return
        target = index_html()
        reason = f"无法加载视口页面：\n{target}"
        if not target.exists():
            frozen = getattr(sys, "_MEIPASS", None)
            reason += ("\n该文件不在包里：打包漏了 --add-data view/" if frozen
                       else "\n该文件不在仓里：view/ 未检出或已改名")
        self._error_body.setText(reason)
        self._stack.setCurrentIndex(1)
        self.load_failed.emit(reason)

    def view(self) -> QWebEngineView:
        return self._view

    def page(self):
        """返回 QWebEnginePage，供 bridge 挂 QWebChannel。"""
        return self._view.page()

    def index_path(self) -> Path:
        return index_html()
