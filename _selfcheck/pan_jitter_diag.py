"""拖动手感诊断（非产品代码）：在**真实窗口**里量拖动是否顺滑。

★ 前几版这个脚本自己算错了单位，得出了"程序有抖动"的错误结论，教训记在这里：

  画布 `width()/height()` 是**逻辑**像素，而 `ax.transData.transform()` 与
  `figure.bbox` 都在**物理**像素（dpi = 100 × devicePixelRatio）。
  Windows 150% 缩放下两者差 1.5 倍；混用就会出现
  "本应在画布内的点算出来 y=-141" 这种假象。

正确换算（dpr = canvas.devicePixelRatioF()）：
    数据 → Qt 部件坐标:  qt_x = px_phys / dpr
                        qt_y = 画布高 - py_phys / dpr

用法（会弹一个真窗口，几秒后自动关闭并打印结果）：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\pan_jitter.py [手簿]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.pop("QT_QPA_PLATFORM", None)          # ★ 用真实平台，不要 offscreen

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pickersrc.plots import ensure_cjk_font  # noqa: E402
from pickersrc.rules import Cond  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402

DATA = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据")


def main() -> int:
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else (
        DATA / "0711" / "914" / "914_20250711.txt")
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.show()
    win.load_file(str(src))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    if len(sys.argv) <= 1:
        # ★ 两条线现在是"且"（求交集）：全清空 = 0 条。要"全部观测"就两条都全选。
        win.scope_widget.dates.set_all(True)
        win.scope_widget.surveys.set_all(True)    # 全部观测，压力大
    win._render()
    win.show_all_data()
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    p = win.plot
    canvas = p._canvas
    dpr = float(canvas.devicePixelRatioF()) or 1.0
    print(f"平台 {app.platformName()}　画布(逻辑) {canvas.width()}x{canvas.height()}"
          f"　dpr {dpr}　figure(物理) {p._fig.bbox.width:.0f}x{p._fig.bbox.height:.0f}"
          f"　点数 {len(p._pts)}")
    print(f"物理/逻辑吻合（同一块区域）: "
          f"{abs(p._fig.bbox.width / dpr - canvas.width()) <= 1.5}")

    def to_qt(dx, dy):
        """数据坐标 → Qt 部件坐标（先物理像素，再除 dpr）。"""
        px, py = p._ax.transData.transform((dx, dy))
        return QPointF(float(px) / dpr, canvas.height() - float(py) / dpr)

    def send(kind, pos, buttons):
        ev = QMouseEvent(QEvent.Type(kind), pos, canvas.mapToGlobal(pos.toPoint()),
                         Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(canvas, ev)
        app.processEvents()

    # 只挑**当前视野之内**的点：按下点落在坐标轴外会被判 inaxes=False，拖动无从开始
    xl, xh = (float(v) for v in p._ax.get_xlim())
    yl, yh = (float(v) for v in p._ax.get_ylim())
    vis = [s for s in p._pts
           if xl <= p._pts[s][0] <= xh and yl <= p._pts[s][1] <= yh]
    if not vis:
        print("当前视野内没有点，无法诊断")
        win.close()
        return 1
    row = max(vis, key=lambda r: p._pts[r][0])
    x0, y0 = p._pts[row][0], p._pts[row][1]
    start = to_qt(x0, y0)
    inside = (0 <= start.x() <= canvas.width()) and (0 <= start.y() <= canvas.height())
    print(f"\n按住点（源行 {row}）数据 ({x0:.3f}, {y0:.3f}) → Qt "
          f"({start.x():.1f}, {start.y():.1f})　在画布内: {inside}")
    if not inside:
        print("★ 取样点仍在画布外，换算公式有问题")
        win.close()
        return 1

    send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    print(f"按下后: _pan_from={'有' if p._pan_from else '无'}"
          f"  _bg 快照={'成功' if p._bg is not None else '失败(退化普通重绘)'}"
          f"  xlim 左端 {p._ax.get_xlim()[0]:.4f}")
    if p._pan_from is None:
        print("★ 拖动没有启动 —— 诊断无法继续")
        win.close()
        return 1

    print("\n步   鼠标x     xlim左端     点Qt_x    偏差(点-鼠标)  本步耗时ms")
    devs, reversals, times = [], 0, []
    prev_left = float(p._ax.get_xlim()[0])
    for k in range(1, 26):
        pos = QPointF(start.x() + 6 * k, start.y())      # 每步 6 逻辑像素
        t0 = time.perf_counter()
        send(QEvent.Type.MouseMove, pos, Qt.MouseButton.LeftButton)
        dt = (time.perf_counter() - t0) * 1000
        times.append(dt)
        left = float(p._ax.get_xlim()[0])
        cur = to_qt(x0, y0).x()
        dev = cur - pos.x()
        devs.append(dev)
        if left - prev_left > 1e-12:                     # 往右拖，左端应单调变小
            reversals += 1
        prev_left = left
        if k <= 6 or k % 5 == 0:
            print(f"{k:>3}  {pos.x():>7.1f}  {left:>10.4f}  {cur:>9.1f}  "
                  f"{dev:>+10.2f}  {dt:>8.1f}")

    send(QEvent.Type.MouseButtonRelease,
         QPointF(start.x() + 6 * 25, start.y()), Qt.MouseButton.NoButton)

    spread = max(devs) - min(devs)
    avg = sum(times) / len(times)
    print(f"\n点相对鼠标偏差：min={min(devs):+.3f} max={max(devs):+.3f} 波动={spread:.3f}px")
    print(f"xlim 左端反向次数 = {reversals}（0 = 单调，不会来回抽）")
    print(f"每次移动耗时：中位 {sorted(times)[len(times) // 2]:.1f} ms，最大 {max(times):.1f} ms"
          f"  → 约 {1000 / max(avg, 1e-6):.0f} fps")
    ok = spread < 0.5 and reversals == 0
    print("\n结论：" + ("拖动顺滑（点始终贴在鼠标下、范围单调、帧率够）" if ok else
                      "★ 仍有抖动 —— 见上面的偏差波动 / 反向次数 / 耗时"))

    win.close()
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
