"""T01 环境冒烟：核对运行时依赖可导入并打印版本，另核 STEP 读取器可用。

跑法（仓根，二选一，均实测退出码 0）：
    conda activate mecharm && python tools/smoke.py
    conda run --no-capture-output -n mecharm python tools/smoke.py
⚠️ 不要省掉 --no-capture-output：conda run 捕获子进程输出后用控制台编码（本机
   GBK）转码，遇本脚本的 UTF-8 中文会自身抛 UnicodeEncodeError，看着像脚本坏了。
退出码：0＝全部通过；1＝有项失败（失败项原文打印，不吞异常）。
"""

from __future__ import annotations

import importlib
import importlib.metadata
import os
import sys

# `python tools/smoke.py` 的 sys.path[0] 是 tools/ 而非仓根，故先补仓根才能 import app.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.bootstrap import preload_windows_icu  # noqa: E402  须在 PySide6 之前执行

REQUIRED = ("OCC", "PySide6", "asyncua", "numpy")
EXTRA = ("yaml", "pytest")
STEP_IMPORT = "OCC.Core.STEPControl"
STEP_SYMBOL = "STEPControl_Reader"


def _force_utf8_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def _module_version(module_name: str) -> str:
    mod = importlib.import_module(module_name)
    for attr in ("__version__", "VERSION", "version"):
        value = getattr(mod, attr, None)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, tuple):
            return ".".join(str(part) for part in value)
    dist = {"OCC": "pythonocc-core", "yaml": "pyyaml"}.get(module_name, module_name)
    try:
        return importlib.metadata.version(dist)
    except importlib.metadata.PackageNotFoundError:
        return "版本未知（模块可导入，但无 __version__ 也无包元数据）"


def _report(module_names: tuple[str, ...]) -> list[str]:
    failures = []
    for name in module_names:
        try:
            print(f"  {name:<10} {_module_version(name)}")
        except Exception as exc:
            failures.append(f"{name}: {type(exc).__name__}: {exc}")
            print(f"  {name:<10} 失败 -> {type(exc).__name__}: {exc}")
    return failures


def _check_step_reader() -> list[str]:
    try:
        mod = importlib.import_module(STEP_IMPORT)
        symbol = getattr(mod, STEP_SYMBOL)
    except Exception as exc:
        print(f"  {STEP_IMPORT}.{STEP_SYMBOL} 失败 -> {type(exc).__name__}: {exc}")
        return [f"{STEP_IMPORT}.{STEP_SYMBOL}: {type(exc).__name__}: {exc}"]
    print(f"  from {STEP_IMPORT} import {STEP_SYMBOL} OK -> {symbol}")
    return []


def main() -> int:
    _force_utf8_stdout()
    print(f"python     {sys.version.split()[0]}  ({sys.executable})")
    print(f"ICU 预载   {preload_windows_icu() or '未执行（非 Windows 或系统无 icuuc.dll）'}")
    print("必核四包：")
    failures = _report(REQUIRED)
    print("同批装入的环境依赖：")
    failures += _report(EXTRA)
    print("STEP 读取器：")
    failures += _check_step_reader()
    print("结论：" + ("全部通过" if not failures else f"{len(failures)} 项失败"))
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
