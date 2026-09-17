# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller **onedir** 打包脚本（T10 卡片步骤⑥）。

跑法（仓根；⛔ 用 mecharm 环境的 python，PyInstaller 是本单经指挥方授权增补的打包工具）：

    /d/Miniforge3/envs/mecharm/python.exe -m PyInstaller mecharm.spec --noconfirm

产物 `dist/mecharm/mecharm.exe` ＋同目录 `_internal/`（PyInstaller 6 的 onedir 布局：exe 之外的一切
都在 `_internal/`）。`build/` 与 `dist/` 已在 .gitignore 内 ⇒ ⛔ 不入库。

**为什么是 onedir 而不是 onefile**：onefile 每次启动都要把整个 bundle 解到临时目录（本包带
QtWebEngine ＋ OCCT，实测体积大），工控机上「双击到出图」的等待不可接受；onedir 直接跑。

三处资源定位口径（⛔ 改任一处都要同步改）：
  - `view/`   → `_internal/view/`：`app/viewpane.py::resource_root()` 打包态取 `sys._MEIPASS`（F4 收口）。
  - `config/` → `_internal/config/`：`core/config/schema.py::REPO_ROOT` 是 `__file__` 的 parents[2]，
                打包后 `__file__`＝`_internal/core/config/schema.pyc` ⇒ parents[2] 正好是 `_internal`。
                ⚠️ 该件是 T03 已验收件、对本单禁改 ⇒ 靠 `datas` 的落地位置去对齐它，⛔ 不改它。
  - OCCT 运行库（`TK*.dll`）：conda 把它们放在 `%PREFIX%\\Library\\bin`、**不在** `OCC` 包内，
                故 PyInstaller 的依赖分析默认找不到 ⇒ 本 spec 自己把该目录加进 `PATH` 再分析，
                让它按需收（⛔ 不整目录 53 MB 全塞，也不手写清单——手写清单换台机器就漏）。
  - Qt 插件与 WebEngine 资产：**手动收**（见 `_qt_datas()`）。PyInstaller 的 PySide6 钩子靠
    QtLibraryInfo 起**子进程** import `PySide6.QtCore` 问路径，而本 conda 环境不预载 ICU 就
    import 不了（WinError 127，即 `app/bootstrap.py` 要解的那个陷阱；Python 3.8+ 的扩展模块
    ⛔ 不走 PATH 找 dll，给子进程补 PATH 也无效）⇒ 钩子静默退化成「只收 .pyd／.dll，不收插件」，
    打出的包启动即报 "no Qt platform plugin could be initialized"（dist 实测抓到的原话）。
    落地位置照抄 PyInstaller 自己的口径（`utils/hooks/qt/__init__.py`）：插件 →
    `PySide6/plugins/<类>/`（冻结态 `QT_PLUGIN_PATH` 由 rthook 指到 `_internal/PySide6/plugins`）、
    WebEngine 的 resources／locales → `PySide6/` 下同名目录、`QtWebEngineProcess.exe` → `PySide6/`
    （rthook 的内嵌 qt.conf 把 LibraryExecutables 指到那儿）。主进程的前缀由 rthook 内嵌 qt.conf
    解决；**helper 子进程不跑 rthook** ⇒ 另给它落一份物理 `PySide6/qt.conf`（Prefix=.）。
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_dynamic_libs

ROOT = Path(SPECPATH)                       # 本 spec 所在目录＝仓根（PyInstaller 注入的变量）
_LIBBIN = Path(sys.prefix) / "Library" / "bin"
if _LIBBIN.is_dir():                        # conda 才有；纯 pip 环境没有这个目录，跳过即可
    os.environ["PATH"] = f"{_LIBBIN}{os.pathsep}{os.environ.get('PATH', '')}"

datas = [(str(ROOT / "view"), "view"), (str(ROOT / "config"), "config")]
binaries = collect_dynamic_libs("OCC")      # OCC 包内自带的 dll（.pyd 由分析自动收）

# 本应用真用得到的插件类（平台／样式／图标／图像／TLS／输入法／兜底）。⛔ 不收 designer、qmltooling、
# sceneparsers 之类别的应用不碰的类——每类都是白拿的体积与攻击面。
_QT_PLUGIN_CATS = ("platforms", "styles", "iconengines", "imageformats", "tls",
                   "platforminputcontexts", "generic")
# WebEngine 运行必需；⛔ 不收 *.debug.pak 与 devtools 的 pak（合计约 88 MB，只在开 DevTools 调试时用）。
_QT_RESOURCES = ("icudtl.dat", "v8_context_snapshot.bin", "qtwebengine_resources.pak",
                 "qtwebengine_resources_100p.pak", "qtwebengine_resources_200p.pak")
_QT_LOCALES = ("qtbase_zh_CN.qm", "qt_zh_CN.qm")     # 界面是中文 ⇒ 只带中文，53 国全带是白拿体积


def _qt_datas():
    """照 PyInstaller 钩子的落地口径手收 Qt 插件与 WebEngine 资产（理由见模块 docstring 第四条）。"""
    qt = Path(sys.prefix) / "Lib" / "site-packages" / "PySide6"
    if not qt.is_dir():                      # 非 conda 的 wheel 布局另说；本环境是 conda，缺了就该响
        raise SystemExit(f"mecharm.spec：找不到 PySide6 包目录 {qt}，Qt 资产无从收齐")
    extra_datas, extra_bins = [], []
    for cat in _QT_PLUGIN_CATS:
        extra_datas.append((str(qt / "plugins" / cat), f"PySide6/plugins/{cat}"))
    extra_datas.append((str(qt / "translations" / "qtwebengine_locales"),
                        "PySide6/translations/qtwebengine_locales"))
    for name in _QT_LOCALES:
        extra_datas.append((str(qt / "translations" / name), "PySide6/translations"))
    res = qt / "resources"
    for name in _QT_RESOURCES:
        extra_datas.append((str(res / name), "PySide6/resources"))
    for entry in sorted((res / "locales").glob("*.pak")):
        extra_datas.append((str(entry), "PySide6/resources/locales"))
    extra_bins.append((str(qt / "QtWebEngineProcess.exe"), "PySide6"))
    # 软件 GL 兜底：本 conda 环境没有 ANGLE 的 libEGL／libGLESv2，Qt 只能走 opengl32sw；缺了它 WebEngine
    # 会退去加载系统 opengl32.dll（只有 GL1.1 导出）⇒ 渲染进程 STATUS_ENTRYPOINT_NOT_FOUND 直接死，
    # 界面上表现为「三维视口加载失败」（dist 实测抓到的链路，见 evidence/T10/dist_launch.txt）。
    extra_datas.append((str(qt / "opengl32sw.dll"), "PySide6"))
    conf = ROOT / "build" / "qtconf" / "qt.conf"      # build/ 已 gitignore ⇒ 不落仓
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text("[Paths]\nPrefix = .\nLibraryExecutables = .\n", encoding="utf-8")
    extra_datas.append((str(conf), "PySide6"))        # 只给 helper 子进程读（它不跑 rthook）
    return extra_datas, extra_bins


_qt_d, _qt_b = _qt_datas()
datas += _qt_d
binaries += _qt_b

a = Analysis(
    [str(ROOT / "run.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["pytest", "IPython", "matplotlib", "tkinter"],
    noarchive=False,
    optimize=0,
)
# 去重：PySide6 自带的 VC 运行时（14.44）与 conda 主环境的（14.51）在 Windows 下大小写不敏感
# 地冲突 ⇒ 只留主环境那份（版本更高、与其他 dll 匹配）。
_VC_RT = frozenset({
    "msvcp140.dll", "msvcp140_1.dll", "msvcp140_2.dll",
    "msvcp140_atomic_wait.dll", "msvcp140_codecvt_ids.dll",
    "vcruntime140.dll", "vcruntime140_1.dll",
})
a.binaries = [
    entry for entry in a.binaries
    if not (entry[0].replace("/", "\\").lower().startswith("pyside6\\")
            and Path(entry[0]).name.lower() in _VC_RT)
]

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="mecharm",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,              # GUI 交付：不留控制台窗。启动期未捕获异常由 bootloader 弹窗给出
    disable_windowed_traceback=False,
    argv_emulation=False,
    icon=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="mecharm",
)
