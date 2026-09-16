"""evidence/T07/_pixels.py — 取证辅助：视口截图落盘与语义色像素统计（⛔ 非交付件）。

从 `_drive_shell_path.py` 拆出，只为守住卡片的两条粒度硬约束（单文件 ≤300 行、单函数 ≤50 行）；
判定口径与拆出前逐字一致，⛔ 未因拆分改任何阈值。

⚠️ 像素数**只作辅证**：工件本体色 `0x8a97a3` 与 `text_dim 0x9fb0bd` 在 ±26 容差内互相污染、
pick.js 标号牌边框就是 accent 蓝、工具标记是受光照着色后的绿（按 token 色匹配恒为 0）。
硬结论一律以 `_probe.mjs` 报的场景图数值为准（见 selftest_path_animation.md 局限 3）。
"""

from __future__ import annotations

import pathlib
from collections import Counter

import app  # noqa: F401  ICU 预载须在任何 PySide6／app.theme 之前
from PySide6.QtGui import QImage

from app.theme import TOKENS

OUT = pathlib.Path(__file__).resolve().parent
COLORS = {"idle_seg": TOKENS["text_dim"], "current_seg": TOKENS["accent"],
          "blocked_seg": TOKENS["deny"], "tool_marker": TOKENS["ok"],
          "model_body": "#8a97a3"}           # 末项＝loader.js 的零件常态色（列出以显式暴露干扰）


def hex_to_rgb(text: str) -> tuple[int, int, int]:
    return tuple(int(text[index:index + 2], 16) for index in (1, 3, 5))


def save(pixmap, name: str) -> pathlib.Path:
    """截图落到本目录（文件名固定，便于复测逐张对）。"""
    path = OUT / name
    pixmap.save(str(path))
    return path


def pixel_counts(pixmap, tol: int = 26) -> tuple[dict, int, int]:
    """视口截图里各语义色的像素数（±tol 容差把抗锯齿边缘算进来；干扰源见模块 docstring）。

    工具标记另给 `green_dominant` 判据：它是被光照着色后的绿（MeshStandardMaterial 受 loader 的
    半球光＋平行光），成品像素色与 token 色相差远超容差，按 token 色匹配恒为 0（实测踩过）。
    """
    image = pixmap.toImage().convertToFormat(QImage.Format.Format_RGB32)
    buffer = bytes(image.constBits())
    histogram = Counter(zip(buffer[2::4], buffer[1::4], buffer[0::4]))   # RGB32 小端＝B,G,R,A
    counts = {}
    for name, text in COLORS.items():
        want = hex_to_rgb(text)
        counts[name] = sum(total for (r, g, b), total in histogram.items()
                           if abs(r - want[0]) <= tol and abs(g - want[1]) <= tol
                           and abs(b - want[2]) <= tol)
    counts["green_dominant"] = sum(total for (r, g, b), total in histogram.items()
                                   if g > r + 30 and g > b + 30)
    return counts, image.width(), image.height()
