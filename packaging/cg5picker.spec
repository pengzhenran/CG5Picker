# -*- mode: python ; coding: utf-8 -*-
"""packaging/cg5picker.spec —— PyInstaller 打包配置（闭源分发合规版）。

    pyinstaller --noconfirm --clean packaging/cg5picker.spec

刻意做的几个选择（与同课题组的 SHKit / SHSynth 一致）：

* **onedir，绝不用 onefile。** Qt for Python 是 LGPLv3：许可要求终端用户
  能替换该库。`--onedir` 下 Qt 的 DLL 作为独立文件躺在 exe 旁边，可以替换；
  `--onefile` 把它们压进归档再解到临时目录，属于社区公认的 relinking 风险。
* **主动排除 GPL-only 的 Qt 模块**：即使打包环境里误装了完整 PySide6
  （会带上 PySide6-Addons → Qt Charts / Qt Data Visualization / Qt Graphs），
  也不会漏进发行包。`packaging/check_licensing.py` 会复核这件事。
* **`licenses/` 与 `docs/` 必须随包**：LGPLv3 要求随附许可全文与显著声明；
  `docs/` 里还有界面运行时读的 `使用说明.html` 与配图（丢了"使用说明"就是空的）。
* 入口是 `packaging/cg5picker_launcher.py`，**不是** `main.py` ——
  PyInstaller 把入口当顶层脚本执行，`pickersrc.*` 里的相对导入需要包被正常导入。
* **`config/` 不打进包**：那是运行期生成的用户配置（跟着安装目录走），
  由程序自己创建；打进包里反而会出现"安装后带着开发者的设置"。

需要看启动期报错时：先 `set CG5PICKER_CONSOLE=1` 再打包 → 出带控制台窗口的 exe。
"""

import os

PROJECT = os.path.abspath(os.path.join(SPECPATH, os.pardir))

CONSOLE = os.environ.get("CG5PICKER_CONSOLE", "") not in ("", "0", "false")

# --- 绝不进包的模块 ---------------------------------------------------------
ALWAYS_EXCLUDE = [
    # 其它 Qt 绑定：PyInstaller 一旦同时发现 PySide6 与 PyQt5/PyQt6 会直接中止
    "PyQt5", "PyQt5.sip", "PyQt6", "PyQt6.sip", "qtpy", "PySide2",
    # 用不上的重型/无关依赖：包小一点、启动快一点
    "IPython", "jupyter", "notebook", "nbformat", "nbconvert",
    "pytest", "_pytest", "sphinx", "docutils",
    "tkinter", "_tkinter", "matplotlib.backends._tkagg",
    "matplotlib.tests", "numpy.tests", "scipy.tests", "pandas.tests",
    "h5py", "pyarrow", "dask", "numba", "sqlalchemy",
    # matplotlib 的 PyInstaller 钩子会把 pandas / scipy 一起拖进来（可选依赖），
    # 本工具一个都不用 —— 排掉能省 ~100 MB（排除后必须重跑 --smoke 验证）
    "pandas", "scipy", "PIL.ImageQt",
    # 本工具用不到的重型 Qt 模块（同时省体积）
    "PySide6.QtQml", "PySide6.QtQuick", "PySide6.QtQuickWidgets",
    "PySide6.QtNetwork", "PySide6.QtSql", "PySide6.QtXml",
]

# --- GPL-only 的 Qt 模块：任何情况下都不发行 --------------------------------
GPL_ONLY = [
    "PySide6.QtCharts", "PySide6.QtChartsQml",
    "PySide6.QtDataVisualization",
    "PySide6.QtGraphs", "PySide6.QtGraphsWidgets",
    "PySide6.QtVirtualKeyboard",
    "PySide6.QtQuick3D", "PySide6.QtQuick3DUtils",
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput",
    "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtWebEngineCore", "PySide6.QtWebEngineWidgets",
    "PySide6.QtWebEngineQuick", "PySide6.QtWebChannel", "PySide6.QtWebSockets",
    "PySide6.QtMultimedia", "PySide6.QtMultimediaWidgets",
    "PySide6.QtPdf", "PySide6.QtPdfWidgets", "PySide6.QtSpatialAudio",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtRemoteObjects",
    "PySide6.QtScxml", "PySide6.QtSensors", "PySide6.QtSerialPort",
    "PySide6.QtTest", "PySide6.QtDesigner", "PySide6.QtHelp",
]

# --- 随包数据 ---------------------------------------------------------------
# (源路径, 包内目标目录)
datas = [
    (os.path.join(PROJECT, "docs"), "docs"),          # 使用说明.html + 配图 + 二维码
    (os.path.join(PROJECT, "licenses"), "licenses"),  # NOTICE + LGPL-3.0 + GPL-3.0
    (os.path.join(PROJECT, "resources"), "resources"),  # 图标 + 公众号二维码
]
for extra in ("README.md", "LICENSE.txt"):
    p = os.path.join(PROJECT, extra)
    if os.path.exists(p):
        datas.append((p, "."))

# --- 图标与版本资源 ---------------------------------------------------------
icon = os.path.join(PROJECT, "resources", "cg5picker.ico")
if not os.path.exists(icon):
    icon = None

version_file = os.path.join(SPECPATH, "version_info.txt")
if not os.path.exists(version_file):
    version_file = None

a = Analysis(
    [os.path.join(SPECPATH, "cg5picker_launcher.py")],
    pathex=[PROJECT],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "pickersrc", "pickersrc.window", "pickersrc.selftest",
        "pickersrc.docs_window", "pickersrc.about_dialog", "pickersrc.appinfo",
        "pickersrc.settings", "pickersrc.presets", "pickersrc.plots",
        "pickersrc.exporter", "pickersrc.source_view", "pickersrc.table_model",
        "pickersrc.table_proxy", "pickersrc.scope_widget",
        "pickersrc.colorder_dialog", "pickersrc.cond_dialog",
        "openpyxl", "openpyxl.styles",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=ALWAYS_EXCLUDE + GPL_ONLY,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="CG5Picker",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                      # UPX 会改 DLL、杀软误报多
    console=CONSOLE,                # 默认无控制台；排错时 set CG5PICKER_CONSOLE=1
    disable_windowed_traceback=False,
    icon=icon,
    version=version_file,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="CG5Picker",
)
