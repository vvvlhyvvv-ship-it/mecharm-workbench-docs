"""中部三维视口容器（02 设计方案 §1/§5：WebEngine 内嵌页，加载失败不白屏）。

T02 阶段视口只显示 index.html 渲染的“深色空场景卡”，不接任何几何：
  - 页面背景设为深色，避免加载瞬间白屏；
  - loadFinished(ok=False) → 切到 Qt 侧错误卡并发 load_failed 信号（由 shell 记日志），
    不进白屏死循环（02 §5）。
对外暴露 view()/page() 供 bridge 挂 QWebChannel。
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtGui import QColor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QFrame, QLabel, QStackedWidget, QVBoxLayout, QWidget

# view/ 在仓根；本文件在 <root>/app/viewpane.py → parents[1] 即仓根。
_INDEX_HTML = Path(__file__).resolve().parents[1] / "view" / "index.html"
_BG = QColor("#16202a")


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
        self._view.load(QUrl.fromLocalFile(str(_INDEX_HTML)))

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
        reason = f"无法加载视口页面：\n{_INDEX_HTML}"
        self._error_body.setText(reason)
        self._stack.setCurrentIndex(1)
        self.load_failed.emit(reason)

    def view(self) -> QWebEngineView:
        return self._view

    def page(self):
        """返回 QWebEnginePage，供 bridge 挂 QWebChannel。"""
        return self._view.page()

    def index_path(self) -> Path:
        return _INDEX_HTML
