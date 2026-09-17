"""打包与开发共用的**唯一入口**（T10 卡片步骤⑥）。

⛔ 第一行必须是从 `app.bootstrap` 取 `preload_windows_icu` 并立刻调用：conda 的 `icu` 包会让
Qt6Core.dll 命中符号不兼容的 `icuuc.dll`（WinError 127），**任何要 import PySide6 的入口都必须
先走该引导**（原因与实测证据见 `app/bootstrap.py` docstring）。打包态尤其如此——PyInstaller
把 conda 环境里那份 `icuuc.dll` 一并收进 bundle，没有引导就是「双击没反应、日志里一行
WinError 127」。⛔ 禁在本件里复制粘贴自写一份 shim（派单卡 §5）。

冻结态追加 `--single-process`：本 conda-Qt 构建的 QtWebEngineProcess 子进程在 onedir bundle 内
必死于 STATUS_ENTRYPOINT_NOT_FOUND（0xC0000139），穷举排查了 ICU／VC 运行时／OpenGL／sandbox／
GPU 进程均未定位根因（详见 evidence/T10/dist_launch.txt）；`--single-process` 模式下视口渲染与
QWebChannel 桥 echo 均已实测通过。开发态与 e2e 冒烟不受影响（不 frozen）。

开发态直接 `python run.py`；打包态由 `mecharm.spec` 以本件为 entry。启动逻辑一律复用
`app.shell.main()`（⛔ 不另抄一份 QApplication 装配，两处会走偏）。
"""

from app.bootstrap import preload_windows_icu

preload_windows_icu()

import os   # noqa: E402  必须在 ICU 预载之后（见模块 docstring）
import sys  # noqa: E402

if getattr(sys, "frozen", False):
    os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--single-process")

from app.shell import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
