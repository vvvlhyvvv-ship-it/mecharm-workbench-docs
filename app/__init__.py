"""app/ — PySide6 桌面外壳层。

导入本包即完成入口引导（见 app/bootstrap.py 的 docstring）：任何 `import app.xxx`
都会先把 Windows 系统 ICU 预载好，使随后的 PySide6 导入不会命中 conda icu 包
那份符号不兼容的 icuuc.dll（WinError 127）。
"""

from app.bootstrap import preload_windows_icu

preload_windows_icu()
