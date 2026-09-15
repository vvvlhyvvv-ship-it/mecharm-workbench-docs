"""底部状态栏（02 设计方案 §1/§3：人话日志一行滚动 │ 数据频率角标 │ 版本）。

只暴露：
  log(msg)            人话日志，单行滚动只显示最新一条（带 HH:MM:SS 前缀）
  set_freq(hz, fps)   频率角标（T02 阶段为占位，传 None 显示 “--”）
高度固定 32px（02 §1 骨架）。颜色/字号走 app.theme 全局 QSS。
"""

from __future__ import annotations

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QLabel, QWidget

VERSION = "v0.1 · 工作台外壳（T02）"
BAR_HEIGHT = 32


class StatusBar(QWidget):
    """底部状态栏：日志一行 + 频率角标 + 版本号。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("StatusBar")
        self.setFixedHeight(BAR_HEIGHT)
        self._log = QLabel("就绪")
        self._log.setObjectName("LogLine")
        self._freq = QLabel()
        self._freq.setObjectName("FreqBadge")
        self._version = QLabel(VERSION)
        self._version.setObjectName("VersionLabel")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(16)
        layout.addWidget(self._log, 1)
        layout.addWidget(self._freq)
        layout.addWidget(self._version)
        self.set_freq(None, None)

    def log(self, msg: str) -> None:
        """显示一条人话日志（单行滚动，只保留最新一条）。"""
        stamp = datetime.now().strftime("%H:%M:%S")
        self._log.setText(f"[{stamp}] {msg}")
        self._log.setToolTip(msg)

    def set_freq(self, data_hz: float | None, fps: float | None) -> None:
        """频率角标；None 显示占位 “--”。<10Hz 变黄的人话提示由后续业务单接线。"""
        hz = "--" if data_hz is None else f"{data_hz:.1f}"
        frame = "--" if fps is None else f"{fps:.0f}"
        self._freq.setText(f"数据 {hz}Hz · 画面 {frame}fps")
