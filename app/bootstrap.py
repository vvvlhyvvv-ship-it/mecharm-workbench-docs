"""入口引导：在导入 PySide6 之前修正 Windows DLL 搜索顺序。

为什么需要它（T01 实测，非推测）：
  Qt6Core.dll 的**静态**导入表里有 icuuc.dll（延迟导入表为空），而 PySide6 的
  wheel 不自带 ICU —— 它按设计吃 Windows 系统自带的 C:\\Windows\\System32\\icuuc.dll。
  但本项目的 conda 环境里 `icu 78.3` 在 %PREFIX%\\Library\\bin 也放了一份 icuuc.dll，
  且 conda 的 python 启动时会自动把该目录加入 DLL 搜索路径，于是 Qt6Core 先命中它，
  因符号集与系统 ICU 不一致而报 WinError 127（ERROR_PROC_NOT_FOUND，
  中文系统文案「找不到指定的程序」），表现为 `from PySide6 import QtCore` 直接失败。
  icu 是 libxml2／libxml2-16 的硬依赖（OCCT 的 XML 支持链），**不能移除**。

处置：装载器按模块名缓存已载入模块，故先按名把系统 ICU 载进来，Qt6Core 后续的
同名请求即命中它。实测预载后 QtCore／QtWebEngineWidgets／QApplication 全部正常。

用法：任何要 import PySide6 的入口，**第一行**先调 preload_windows_icu()。
`app/__init__.py` 已调用，故 `import app.*` 的路径自动生效；tools/smoke.py 显式调用。
"""

from __future__ import annotations

import ctypes
import os
import sys


def preload_windows_icu() -> str | None:
    """预载 Windows 系统 ICU，返回实际载入的路径；非 Windows 或无该 DLL 时返回 None。

    返回 None 不代表成功：若系统缺 icuuc.dll（Windows 10 1703 以前），Qt6Core
    本来也无法工作，此时应由调用方的导入报错暴露真因，本函数不吞也不伪装。
    """
    if sys.platform != "win32":
        return None
    root = os.environ.get("SystemRoot", r"C:\Windows")
    path = os.path.join(root, "System32", "icuuc.dll")
    if not os.path.exists(path):
        return None
    ctypes.WinDLL(path)
    return path
