"""自检用脚本（非产品代码）：把四种视图各渲染一张，核对固定边距没有裁掉字。

用法（在项目根目录）：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\views.py [CG5手簿] [输出目录]
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pickersrc.plots import VIEW_KINDS  # noqa: E402
from pickersrc.rules import Cond  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else (
        ROOT / "CG5Picker" / "_selfcheck")
    out.mkdir(parents=True, exist_ok=True)

    app = _create_app()
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    win.load_file(str(src))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    # 离屏平台不铺开布局（画布始终很小），所以让 matplotlib 直接按真实面板尺寸出图，
    # 这样才看得出固定边距有没有裁掉刻度/轴标签/标题。
    for kind, label in VIEW_KINDS.items():
        win.plot.set_kind(kind)
        win.plot._canvas.draw()
        app.processEvents()
        p = out / f"view_{kind}.png"
        win.plot._fig.set_size_inches(8.2, 5.6)
        win.plot._fig.savefig(str(p), dpi=100)
        ax = win.plot._ax
        print(f"{label:22s} → {p.name}　坐标轴 "
              f"{tuple(round(float(v), 3) for v in ax.get_position().bounds)}")
    win.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
