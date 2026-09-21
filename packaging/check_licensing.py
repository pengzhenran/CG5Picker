# -*- coding: utf-8 -*-
"""发行前许可合规自查（打包脚本会调用；也能单独跑）。

    python packaging/check_licensing.py

查四件事：
  1. 代码里**不能**出现 GPL-only / 高危 Qt 模块名（QtCharts / DataVisualization /
     Graphs / VirtualKeyboard / WebEngine…）；
  2. 只 import 了 LGPLv3 覆盖的 QtCore / QtGui / QtWidgets；
  3. 许可文件齐：`LICENSE.txt`（MIT 全文 + 版权行）、`licenses/NOTICE.txt`
     （逐条第三方声明）、`licenses/LGPL-3.0.txt` + `licenses/GPL-3.0.txt`（FSF 原文）；
  4. PyInstaller spec 里排除了 GPL-only 模块、且把 `docs/` `licenses/` 打进了包，
     并用 onedir（LGPLv3 要求用户可替换 Qt 动态库）。

退出码 0 = 通过；1 = 有问题（打印到 stderr）。
"""
from __future__ import annotations

import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

BAD_MODULES = ("QtCharts", "QtChartsQml", "QtDataVisualization", "QtGraphs",
               "QtVirtualKeyboard", "QtWebEngine", "QtWebEngineWidgets",
               "QtWebEngineQuick", "QtQuick3D")
OK_QT = {"QtCore", "QtGui", "QtWidgets"}

_problems: list[str] = []


def _ok(cond: bool, label: str, detail: str = "") -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        _problems.append(label)


def main() -> int:
    print("CG5Picker —— 许可合规自查")
    src = os.path.join(ROOT, "pickersrc")
    code = "\n".join(
        open(os.path.join(src, f), encoding="utf-8", errors="replace").read()
        for f in os.listdir(src) if f.endswith(".py"))
    for name in BAD_MODULES:
        _ok(name not in code, f"代码里没有 GPL-only / 高危模块 {name}")
    used = set(re.findall(r"from PySide6\.(Qt\w+)", code))
    _ok(used <= OK_QT, "只用 QtCore / QtGui / QtWidgets（LGPLv3）",
        "、".join(sorted(used)))

    from pickersrc import appinfo

    lic = appinfo.license_path()
    _ok(lic is not None, "LICENSE.txt 随包（MIT 全文）", str(lic))
    if lic:
        t = lic.read_text(encoding="utf-8")
        _ok("MIT License" in t and "WITHOUT WARRANTY" in t, "LICENSE.txt 是 MIT 全文")
        _ok(appinfo.copyright_line() in t.replace("（", "(").replace("）", ")")
            or f"Copyright (c) {appinfo.LICENSE_YEAR}" in t,
            "LICENSE.txt 带版权行", appinfo.copyright_line())
    notice = appinfo.notice_path()
    _ok(notice is not None, "licenses/NOTICE.txt 随包", str(notice))
    if notice:
        n = notice.read_text(encoding="utf-8")
        for key in ("PySide6", "LGPL", "matplotlib", "NumPy", "openpyxl"):
            _ok(key in n, f"NOTICE 里声明了 {key}")
        _ok(("动态链接" in n or "dynamically linked" in n)
            and ("替换" in n), "NOTICE 写明动态链接与用户替换权（LGPLv3 义务）")
    extra = {p.name for p in appinfo.notice_extra_paths()}
    _ok({"LGPL-3.0.txt", "GPL-3.0.txt"} <= extra, "LGPLv3 / GPLv3 全文随包",
        "；".join(sorted(extra)))
    lgpl = next((p for p in appinfo.notice_extra_paths()
                 if p.name == "LGPL-3.0.txt"), None)
    if lgpl:
        t = lgpl.read_text(encoding="utf-8")
        _ok("GNU LESSER GENERAL PUBLIC LICENSE" in t, "LGPL-3.0.txt 是 FSF 原文")

    spec = os.path.join(ROOT, "packaging", "cg5picker.spec")
    if os.path.exists(spec):
        with open(spec, encoding="utf-8") as fh:
            s = fh.read()
        _ok("GPL_ONLY" in s and "excludes=ALWAYS_EXCLUDE + GPL_ONLY" in s,
            "spec 里排除了 GPL-only 的 Qt 模块")
        _ok('"docs"' in s and '"licenses"' in s, "spec 把 docs/ 与 licenses/ 打进包")
        _ok("COLLECT(" in s and "exclude_binaries=True" in s,
            "spec 用 onedir（COLLECT），不是 onefile",
            "LGPLv3 要求用户可替换 Qt 动态库")
    else:
        _ok(False, "找到 packaging/cg5picker.spec")

    print()
    if _problems:
        print(f"存在失败项 ✘（{len(_problems)}）：", file=sys.stderr)
        for p in _problems:
            print(f"  · {p}", file=sys.stderr)
        return 1
    print("许可合规自查：全部通过 ✔")
    return 0


if __name__ == "__main__":
    sys.exit(main())
