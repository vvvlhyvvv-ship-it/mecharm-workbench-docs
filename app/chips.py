"""顶栏数据芯片、判定灯与使能钮（01 蓝图 §3.3-4/5/6；T13）。

  StatChips    三枚等宽数字芯片：渲染 fps（桥 ``perf.fps``）｜状态同步 Hz（回读帧率）｜
               碰撞检测 ms（``CollisionResult.elapsed_ms``）。**未测得一律「—」**（Δ-6：58/10/2.4
               都是演示数字 ⛔ 禁上屏）；数值列走等宽（theme 的 ``[mono="true"]``）。
  HzMeter      只读观察器：数 ``link.frames`` 到达率得实测 Hz，驱芯片与链路灯（蓝图 §3.3-6 的
               「实时 N Hz」）；停流超窗自动回落 None（⛔ 不拿旧值假装在测）。
  VerdictLamp  本次轨迹判定灯：通过绿／预警黄／不通过红＋命中处数（由校核结论迁移，蓝图 §3.3-6-②）。
  EnableButton 使能按钮：**渲染两态外形但一律禁用**＋tooltip「待契约回执」（Δ-11：点表故意未收
               ``enable_mask``，⛔ 不得拿 status 位推导使能——使能≠就绪，语义未裁）。
颜色/字号一律走 app.theme 全局 QSS（tone/mono 动态属性），本模块不写内联样式。
"""

from __future__ import annotations

import time

from PySide6.QtCore import QObject, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QWidget

DASH = "—"
ENABLE_TIP = "待契约回执"          # Δ-11：enable_mask 未入点表（契约 V1.3 悬置，CR-2026-03 §三-5）
_HZ_WINDOW_S = 3.0                 # 实测频率的滑窗跨度（与 livectl 报角标同量级）


class StatChips(QWidget):
    """三芯片；set_* 传 None 即「—」（离线／未测得，§1-1 无数据禁造值）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._fps = _Chip("渲染", "fps")
        self._hz = _Chip("状态同步", "Hz")
        self._ms = _Chip("碰撞检测", "ms")
        row = QHBoxLayout(self)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)
        for chip in (self._fps, self._hz, self._ms):
            row.addWidget(chip)
        self.set_fps(None)
        self.set_hz(None)
        self.set_ms(None)

    def set_fps(self, fps: float | None) -> None:
        self._fps.set_value(f"{fps:.0f}" if fps is not None else DASH)

    def set_hz(self, hz: float | None) -> None:
        self._hz.set_value(f"{hz:.1f}" if hz is not None else DASH)

    def set_ms(self, ms: float | None) -> None:
        self._ms.set_value(f"{ms:.1f}" if ms is not None else DASH)


class _Chip(QLabel):
    """一枚芯片＝键名（暗）＋数值（等宽、青）＋单位（暗）；一整条按等宽渲染（数值列口径）。"""

    def __init__(self, key: str, unit: str) -> None:
        super().__init__()
        self.setProperty("mono", "true")
        self._key, self._unit = key, unit

    def set_value(self, text: str) -> None:
        self.setText(f"{self._key} {text} {self._unit}")


class HzMeter(QObject):
    """回读帧率计：只数 ``frames`` 信号到达次数（⛔ 不碰 livectl 的任何状态）。

    每秒结算滑窗内到达率：≥2 帧报实测、不足回落 None；停流超窗也回落——离线后芯片与灯
    都回「—／离线」，不留旧值假装在线。
    """

    def __init__(self, on_hz, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._stamps: list[float] = []
        self._on_hz = on_hz
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(1000)

    def on_frames(self, batch: object) -> None:
        if isinstance(batch, list) and batch:
            self._stamps.extend([time.monotonic()] * len(batch))

    def _tick(self) -> None:
        now = time.monotonic()
        self._stamps = [t for t in self._stamps if now - t <= _HZ_WINDOW_S]
        hz = None
        if len(self._stamps) >= 2 and now - self._stamps[0] > 0.0:
            hz = (len(self._stamps) - 1) / (now - self._stamps[0])
        self._on_hz(hz)


class VerdictLamp(QLabel):
    """本次轨迹判定灯：无结论灰「—」／通过绿／预警黄·N 处／不通过红·N 处（文字＋着色双通道）。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.set_result(None)

    def set_result(self, res: object) -> None:
        verdict = getattr(res, "verdict", None)
        cases = len(getattr(res, "cases", ()) or ())
        tone, text = {
            None: ("dim", "本次轨迹 —"),
            "pass": ("ok", "本次轨迹 通过"),
            "warn": ("warn", f"预警 · {cases} 处"),
            "interfere": ("deny", f"不通过 · {cases} 处"),
        }.get(verdict, ("dim", "本次轨迹 —"))
        self.setProperty("tone", tone)
        self.setText(text)
        self.style().unpolish(self)
        self.style().polish(self)


class EnableButton(QPushButton):
    """使能钮（Δ-11）：两态外形按「未使能」档渲染，恒禁用；⛔ 不接任何数据源。"""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("未使能", parent)
        self.setToolTip(ENABLE_TIP)
        self.setEnabled(False)
