"""自检用脚本（非产品代码）：离屏渲染主窗口，出一张 PNG 供肉眼核对排版。

用法（在项目根目录）：
    GravProc\\.venv\\Scripts\\python.exe CG5Picker\\_selftest_out\shot.py <CG5手簿> <输出.png>
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pickersrc.plots import ensure_cjk_font  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据" / "0711" / "914" / "914_20250711.txt")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        ROOT / "CG5Picker" / "_selftest_out" / "shot.png")

    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.resize(1680, 980)
    win.show()
    win.load_file(str(src))
    app.processEvents()

    win.grab().save(str(out))
    print(f"已保存截图：{out}  ({out.stat().st_size} 字节)")
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
