"""evidence/T07/_spy_playback_clock.py — 播放时钟节拍取证（`_drive_shell_path.py` 的加测挂片）。

跑法（worktree 根，须有显示环境；会弹出工作台窗体约 30 秒）：
  PYTHONPATH=. python evidence/T07/_spy_playback_clock.py > evidence/T07/playback_clock_log.txt

干什么：给 `app.pathctl.PathController._tick` 套一层计数探针（**只记录、不改行为**，原方法照旧
调用），跑完打印 tick 总数与间隔分布。这是「播放流畅」判据的**壳侧一半**：视口角标的 fps 只
证明 rAF 在转，tick 间隔才证明壳侧 16 ms 软件时钟真按 60 Hz 发 `pose.update`（角标掉到 1~3 fps
时靠它区分「时钟饿死」还是「渲染被节流」——实测踩过：窗体非活动时 Chromium 掐 rAF，
tick 却仍稳在 16.5 ms）。

⛔ 不是交付件、不改任何 app/ view/ core/ 源文件；探针只在本脚本进程内生效。
"""

from __future__ import annotations

import atexit
import pathlib
import statistics
import sys
import time

OUT = pathlib.Path(__file__).resolve().parent
ROOT = OUT.parent.parent
for entry in (str(ROOT), str(OUT)):
    if entry not in sys.path:
        sys.path.insert(0, entry)

import _drive_shell_path as drive          # noqa: E402  复用其窗体驱动与全部判据
from app.pathctl import PathController     # noqa: E402

STAMPS: list[float] = []
_ORIGINAL = PathController._tick


def _spy(self) -> None:
    STAMPS.append(time.perf_counter())
    _ORIGINAL(self)


PathController._tick = _spy


def report() -> None:
    """退出前汇总：tick 总数、时长、间隔中位／均值／极值、以及 >200 ms 的卡顿次数。"""
    print("\n=== tick 探针（壳侧播放时钟）===")
    if len(STAMPS) < 2:
        print("tick 总数:", len(STAMPS), "——不足两次，无法算间隔（本次没进播放？）")
        return
    gaps = [round((b - a) * 1000, 1) for a, b in zip(STAMPS, STAMPS[1:])]
    print("tick 总数:", len(STAMPS), "| 首末跨度 s:", round(STAMPS[-1] - STAMPS[0], 2))
    print("间隔 ms  中位:", statistics.median(gaps), "| 均值:", round(statistics.fmean(gaps), 1),
          "| 最小:", min(gaps), "| 最大:", max(gaps))
    print("间隔 >200 ms 的次数:", sum(1 for g in gaps if g > 200), "/", len(gaps),
          "（0 ⇒ 时钟没被饿死，发帧连续）")
    print("前 20 个间隔:", gaps[:20])


atexit.register(report)
sys.exit(drive.main())
