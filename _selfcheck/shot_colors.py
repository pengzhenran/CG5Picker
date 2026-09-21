"""自检用脚本（非产品代码）：离屏渲染"黄底 + 选中行"的样子，出一张 PNG 供肉眼核对。

用法：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\shot_colors.py [输出.png]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QAbstractItemView  # noqa: E402

from pickersrc.plots import VIEW_KINDS, ensure_cjk_font  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402

DATA = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")


def _pump(app, sec: float = 0.35) -> None:
    """把布局/绘制跑完再抓图 —— 只 processEvents 一次的话，
    离屏窗口的分栏还停在 sizeHint 宽度，抓出来的排版不是真实的样子。"""
    app.processEvents()
    time.sleep(sec)
    app.processEvents()


def main() -> int:
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "CG5Picker" / "_selfcheck" / "colors.png")
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.resize(1680, 980)
    win.show()
    _pump(app)
    win.load_file(str(DATA))
    win.show_all_data()
    _pump(app)

    want_tide = "--tide" in sys.argv
    if want_tide:
        win.cmb_view.setCurrentIndex(list(VIEW_KINDS).index("tide"))
        _pump(app)

    tv, model, proxy = win.table, win.model, win.proxy

    def is_kept(v: int) -> bool:
        idx = proxy.index(v, 0)
        mr = proxy.mapToSource(idx).row() if idx.isValid() else -1
        return (0 <= mr < len(model._keep) and model._in_scope[mr]
                and model._keep[mr])

    v = next((v for v in range(proxy.rowCount()) if is_kept(v)), -1)
    if v >= 0:
        tv.scrollTo(proxy.index(v, 0), QAbstractItemView.ScrollHint.PositionAtTop)
        app.processEvents()
        tv.selectRow(v + 1 if is_kept(v + 1) else v)     # 选中一行，看亮黄
        app.processEvents()
    win.grab().save(str(out))
    print(f"已保存：{out}  ({out.stat().st_size} 字节)　选中视图行 {v}")
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
