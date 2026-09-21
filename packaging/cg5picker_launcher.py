# -*- coding: utf-8 -*-
"""CG5Picker 打包入口（PyInstaller 用）。

为什么要单独一个入口文件
------------------------
PyInstaller 会把**入口脚本**当顶层脚本执行（没有父包），若直接拿
`pickersrc/window.py` 当入口，里面的相对导入（`from . import ...`）会炸：
`ImportError: attempted relative import with no known parent package`。
所以入口放在包外，先 `import pickersrc.*`（包被正常导入，相对导入全部成立）再调用。

支持的命令行
------------
    CG5Picker.exe                      打开界面
    CG5Picker.exe <CG5手簿.txt>        打开界面并直接载入该文件
    CG5Picker.exe --about              打开「作者信息 / 关于」窗口（开始菜单那个快捷方式用它）
    CG5Picker.exe --guide              打开随包 HTML 使用说明（窗口内预览）
    CG5Picker.exe --version            打印版本与作者信息（无控制台时改为开「关于」窗口）
    CG5Picker.exe --licenses           打印许可与第三方声明（无控制台时改为开「关于」窗口）
    CG5Picker.exe --selftest <手簿> [--out 目录]
                                       无界面自检（打包脚本用它做冒烟测试）

★ 为什么要判"有没有控制台"：冻结版是 **GUI 子系统**程序（PyInstaller console=False）。
  从 cmd / PowerShell 里跑，它继承父进程的控制台，`print` 有地方去；但**双击开始菜单
  里的快捷方式**时没有控制台，PyInstaller 塞的是一个黑洞 writer —— `print` 一点动静都
  没有，用户点了「作者信息（关于）」只会觉得"这东西坏了"（v1.0.0 实测：退出码 0、
  屏幕上什么都没出现）。所以凡是"打印给人看"的子命令，都要能退回开窗口。
"""
from __future__ import annotations

import os
import sys
import tempfile

__all__ = ["main"]

_HELP = """\
CG5Picker —— CG5 数据挑选

用法:
  CG5Picker.exe                      打开图形界面
  CG5Picker.exe <CG5手簿.txt>         打开界面并直接载入该手簿
  CG5Picker.exe --about              打开「作者信息 / 关于」窗口
  CG5Picker.exe --guide              打开使用说明（HTML，窗口内预览）
  CG5Picker.exe --version            显示版本与作者（无控制台时开「关于」窗口）
  CG5Picker.exe --licenses           显示许可与第三方组件声明
  CG5Picker.exe --selftest <手簿>     无界面自检（可加 --out <目录>）
  CG5Picker.exe --smoke              冒烟：把界面装配一遍再退出（打包脚本用）
"""


def _isolate_matplotlib_config() -> None:
    """把 matplotlib 配置目录指到临时目录（在被导入之前设置）。

    冻结版若去写 `%USERPROFILE%\\.matplotlib`，在只读或受管环境里会报错，
    而本软件并不需要保存 matplotlib 配置。
    """
    tmp = os.path.join(tempfile.gettempdir(), "cg5picker-mplconfig")
    try:
        os.makedirs(tmp, exist_ok=True)
    except OSError:
        return
    os.environ.setdefault("MPLCONFIGDIR", tmp)


def _ensure_importable() -> None:
    """源码运行时把项目根加进 sys.path；冻结后这一步无害（只是兜底）。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (here, os.path.dirname(here)):
        if cand not in sys.path and os.path.isdir(os.path.join(cand, "pickersrc")):
            sys.path.insert(0, cand)
            break


def _force_utf8_stdout() -> None:
    """把 stdout/stderr 切成 UTF-8。

    冻结版从 Windows 管道（PowerShell 抓输出）里出来时，默认按**控制台码页（GBK）**
    编码，中文就成了乱码 —— 打包脚本的冒烟测试、以及用户在 cmd 里跑 `--version`
    都会撞上。这里显式 reconfigure，`PYTHONIOENCODING` 管不到的情况也能对。
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError, OSError):
            pass


def _stdout_is_real() -> bool:
    """stdout 到底有没有地方可写？

    不猜 Python 那边的桩对象（不同 PyInstaller 版本给的不一样），直接问 Windows：
    STD_OUTPUT_HANDLE 是控制台(CHAR)、还是重定向到管道(PIPE)/文件(DISK)都算"真的"；
    没有控制台又没有重定向时句柄是 NULL / INVALID，`GetFileType` 回 0（UNKNOWN）——
    那就是"打印了也没人看得见"，此时应该开窗口。
    """
    if sys.stdout is None:
        return False
    if os.name != "nt":
        try:
            return int(sys.stdout.fileno()) >= 0
        except Exception:
            return False
    try:
        import ctypes

        k32 = ctypes.windll.kernel32
        k32.GetStdHandle.restype = ctypes.c_void_p
        k32.GetFileType.argtypes = [ctypes.c_void_p]
        handle = k32.GetStdHandle(-11)          # STD_OUTPUT_HANDLE
        if not handle:
            return False
        return int(k32.GetFileType(handle)) != 0   # 0 = FILE_TYPE_UNKNOWN
    except Exception:
        return False


def _open_about() -> int:
    """打开「作者信息 / 关于」窗口（与界面里 Shift+F1 同一个对话框）。"""
    from PySide6.QtWidgets import QApplication

    from pickersrc.about_dialog import AboutDialog
    from pickersrc.window import _apply_app_identity, _apply_ui_font
    app = QApplication.instance() or QApplication(sys.argv)
    _apply_ui_font(app)
    _apply_app_identity(app)
    AboutDialog(None, None).exec()
    return 0


def main(argv=None) -> int:
    _isolate_matplotlib_config()
    _ensure_importable()
    _force_utf8_stdout()

    argv = list(sys.argv[1:] if argv is None else argv)
    # 「打印给人看」的子命令在没有控制台时改用窗口，否则用户什么都看不到
    can_print = _stdout_is_real()

    if argv and argv[0] in ("-h", "--help", "/?"):
        if not can_print:
            return _open_about()
        print(_HELP)
        return 0
    if argv and argv[0] in ("-V", "--version"):
        if not can_print:
            return _open_about()
        from pickersrc import appinfo
        print(appinfo.about_text())
        return 0
    if argv and argv[0] == "--licenses":
        if not can_print:
            return _open_about()
        from pickersrc import appinfo
        print(appinfo.copyright_line())
        print()
        p = appinfo.notice_path()
        if p is None:
            print("未找到 licenses/NOTICE.txt")
            return 1
        print(p.read_text(encoding="utf-8"))
        return 0
    if argv and argv[0] == "--about":
        # 开始菜单「作者信息（关于）」快捷方式走这里：开窗口，不靠控制台
        return _open_about()
    if argv and argv[0] == "--guide":
        # 在**窗口里**看说明书（与「📖 使用说明」同一个窗口），不丢给浏览器
        from PySide6.QtWidgets import QApplication

        from pickersrc.docs_window import open_guide
        from pickersrc.window import _apply_app_identity, _apply_ui_font
        app = QApplication.instance() or QApplication(sys.argv)
        _apply_ui_font(app)
        _apply_app_identity(app)
        return 0 if open_guide() else 1
    if argv and argv[0] == "--selftest":
        rest = argv[1:]
        from pickersrc.selftest import run_selftest
        return int(run_selftest(rest))
    if argv and argv[0] == "--smoke":
        # 冻结版冒烟：**把界面真的装配出来**再退出（Qt 平台插件、matplotlib 画布
        # 都走一遍）。打包脚本用它验证"包里的 Qt / matplotlib 是全的"；
        # 用 offscreen 平台，所以不弹窗。
        # ★ 配置写到临时目录：冒烟窗口不是最大化、几何也是离屏的，写进发行包的
        #   config\ 会让用户**一打开就不最大化**（实测踩过）。
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        # ★ 每次用**全新**临时目录：复用上一次的配置会把"上次没最大化"记下来，
        #   于是这一次 want_max 也成 False —— 冒烟自己把自己带偏（实测踩过）。
        os.environ["CG5PICKER_CONFIG_DIR"] = tempfile.mkdtemp(
            prefix="cg5picker-smoke-")
        from PySide6.QtWidgets import QApplication

        from pickersrc.window import MainWindow, _create_app
        app = _create_app() or QApplication.instance()
        win = MainWindow()
        win.show()
        for _ in range(4):
            app.processEvents()
        # 注意：这里**不**判 can_print —— smoke 由打包脚本管道抓输出，能抓到就说明
        # 句柄是通的；判错了会把整条打包流程卡死，得不偿失。
        print(f"smoke OK: {win.size().width()}x{win.size().height()} "
              f"conds={len(win.conds)} maximized={win.isMaximized()} "
              f"want_max={win._want_maximized}")
        win.close()
        return 0

    # 默认：图形界面（可带一个手簿文件直接载入）
    from pickersrc.window import run
    return int(run(argv))


if __name__ == "__main__":
    sys.exit(main())
