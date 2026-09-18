"""打包与开发共用的**唯一入口**（T10 卡片步骤⑥；T12 接上载入→登录→主界面启动序列）。

⛔ ICU 红线不变：必须先从 `app.bootstrap` 取 `preload_windows_icu` 并立刻调用，再 import
任何 PySide6（原因与实测证据见 `app/bootstrap.py` docstring）。⛔ 禁在本件里复制粘贴自写
一份 shim。ICU 段耗时就地实测（含 app 包导入——首次预载正发生在那次导入里），经
`icu_ms` 下传给 `app.shell.main()` 回填进载入页日志（蓝图 §3.1「里程碑取真时刻」，⛔ 不编造）。

冻结态追加 `--single-process`（T10 实测：QtWebEngineProcess 子进程在 onedir bundle 内必死
0xC0000139，根因未定位已如实记，见 evidence/T10/dist_launch.txt）；开发态与 e2e 不受影响。

T12 新增两个命令行参数并在此解析下传（派单卡步骤 4）：
  --stage std|wide        舞台档位强制（默认 auto＝按窗口宽高比 ≥2.0 选 wide）
  --ui-profile evidence   取证档（界面身份文案换中性占位；凡入 evidence/ 的截图一律用此档）
启动逻辑一律复用 `app.shell.main()`（⛔ 不另抄一份 QApplication 装配，两处会走偏）。
"""

import time  # 纯 stdlib，先于一切 PySide6 导入无害；ICU 段计时需要（见模块 docstring）

_t0 = time.perf_counter()
from app.bootstrap import preload_windows_icu  # noqa: E402  app 包 __init__ 在此完成首次 ICU 预载
preload_windows_icu()                          # noqa: E402  显式补调一次（幂等；防未来 __init__ 不再代劳）
ICU_MS = (time.perf_counter() - _t0) * 1000.0

import argparse  # noqa: E402  必须在 ICU 预载之后
import os        # noqa: E402
import sys       # noqa: E402

if getattr(sys, "frozen", False):
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--single-process")

from app.shell import main  # noqa: E402


def _parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="机械臂三维示教工作台（RoboPath HMI）")
    parser.add_argument("--stage", choices=("auto", "std", "wide"), default="auto",
                        help="舞台档位强制（默认按 ui.yaml 的 stage_default／窗口宽高比）")
    parser.add_argument("--ui-profile", choices=("default", "evidence"), default="default",
                        dest="ui_profile", help="界面文案档：evidence＝取证占位（截图入库用）")
    return parser.parse_args(argv)


if __name__ == "__main__":
    args = _parse_args()
    sys.exit(main(stage=args.stage, ui_profile=args.ui_profile, icu_ms=ICU_MS))
