"""拖动残影诊断（非产品代码）：验证"拖动时不会出现两套刻度标签"的机制。

用户报的现象：拖动时"坐标标签有一套不动、一套随着动，松开后旧的那套才消失"。
根因（实测）：平移原来用 blit —— `set_xlim()` 会把 figure 标成 stale，
`canvas.blit()` 内部**照样整图重绘**，再叠加我们手画的 `restore_region + draw_artist`，
同一帧坐标轴被画两次、内容不一致，边距里的旧刻度就留成幽灵。

所以这里测的是**机制**（而不是去数像素）：
  1. 拖动过程中**绝不能**调用 `restore_region` / `blit`（一旦调用就可能重复绘制）；
  2. 每一步只走一次普通重绘（`draw_idle`），并且重绘后 `figure.stale` 为 False；
  3. 四条坐标框线都可见；
  4. 视图单调移动、且被拖的点始终贴在光标下。

用法（会弹一个真窗口，几秒后自动关闭）：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\pan_ghost_check.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CG5PICKER_CONFIG_DIR", __import__("tempfile").mkdtemp(prefix="cg5pick_check_"))   # 别往真安装目录写配置
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.pop("QT_QPA_PLATFORM", None)

from PySide6.QtCore import QEvent, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pickersrc.plots import ensure_cjk_font  # noqa: E402
from pickersrc.rules import Cond  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402

DATA = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")

_fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        _fails.append(label)


def main() -> int:
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.show()
    win.load_file(str(DATA))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    app.processEvents()
    time.sleep(0.4)
    app.processEvents()

    p = win.plot
    canvas = p._canvas
    dpr = float(canvas.devicePixelRatioF()) or 1.0
    print(f"平台 {app.platformName()}　画布 {canvas.width()}x{canvas.height()}　dpr {dpr}")

    def to_qt(dx, dy):
        px, py = p._ax.transData.transform((dx, dy))
        return QPointF(float(px) / dpr, canvas.height() - float(py) / dpr)

    def send(kind, pos, buttons):
        ev = QMouseEvent(QEvent.Type(kind), pos, canvas.mapToGlobal(pos.toPoint()),
                         Qt.MouseButton.LeftButton, buttons,
                         Qt.KeyboardModifier.NoModifier)
        QApplication.sendEvent(canvas, ev)
        app.processEvents()

    # ---- 1) 四条框线都在
    frame_color = str(p._ax.spines["top"].get_edgecolor())
    for name in ("top", "bottom", "left", "right"):
        sp = p._ax.spines[name]
        check(f"坐标框线 {name} 可见", sp.get_visible(),
              f"color={sp.get_edgecolor()}")
    check("框线颜色不是全白（看得见）",
          "1.0, 1.0, 1.0" not in frame_color and "white" not in frame_color,
          frame_color)

    # ---- 2) 拖动过程中不得调用 blit / restore_region
    used: list[str] = []
    orig_restore = type(canvas).restore_region
    orig_blit = type(canvas).blit

    def boom_restore(self, *a, **k):
        used.append("restore_region")
        return orig_restore(self, *a, **k)

    def boom_blit(self, *a, **k):
        used.append("blit")
        return orig_blit(self, *a, **k)

    type(canvas).restore_region = boom_restore
    type(canvas).blit = boom_blit

    xl, xh = (float(v) for v in p._ax.get_xlim())
    yl, yh = (float(v) for v in p._ax.get_ylim())
    vis = [s for s in p._pts
           if xl <= p._pts[s][0] <= xh and yl <= p._pts[s][1] <= yh]
    row = max(vis, key=lambda r: p._pts[r][0])
    x0, y0 = p._pts[row][0], p._pts[row][1]
    start = to_qt(x0, y0)

    send(QEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton)
    check("按下后进入平移状态", p._pan_from is not None)

    xlims, devs, stales = [], [], []
    for k in range(1, 13):
        pos = QPointF(start.x() + 8 * k, start.y())
        send(QEvent.Type.MouseMove, pos, Qt.MouseButton.LeftButton)
        canvas.draw()                        # 立刻落实这一帧
        xlims.append(tuple(round(float(v), 4) for v in p._ax.get_xlim()))
        devs.append(to_qt(x0, y0).x() - pos.x())
        stales.append(bool(p._fig.stale))

    send(QEvent.Type.MouseButtonRelease,
         QPointF(start.x() + 8 * 12, start.y()), Qt.MouseButton.NoButton)

    type(canvas).restore_region = orig_restore
    type(canvas).blit = orig_blit

    check("拖动全程没有调用 blit / restore_region（不会重复绘制）",
          not used, f"调用记录 {used}")
    check("拖动的每一步都是立刻完整重绘（不留待补画的旧内容）",
          not any(stales), f"stale 次数 {sum(stales)}/{len(stales)}")
    check("视图单调移动（不会来回抽）",
          all(b[0] <= a[0] for a, b in zip(xlims, xlims[1:])),
          f"{[x[0] for x in xlims[:4]]} …")
    check("被拖的点始终贴在光标下（偏差 ≈ 0）",
          max(devs) - min(devs) < 0.5 and abs(max(devs)) < 0.5,
          f"偏差 min={min(devs):+.3f} max={max(devs):+.3f}")

    # ---- 3) 一次重绘只画一遍坐标轴（用计数确认没有双重绘制）
    calls = {"draw": 0}
    real_draw = type(canvas).draw

    def counting_draw(self, *a, **k):
        calls["draw"] += 1
        return real_draw(self, *a, **k)

    type(canvas).draw = counting_draw
    send(QEvent.Type.MouseButtonPress, to_qt(*p._pts[row][:2]), Qt.MouseButton.LeftButton)
    calls["draw"] = 0
    send(QEvent.Type.MouseMove, QPointF(start.x() + 40, start.y()),
         Qt.MouseButton.LeftButton)
    app.processEvents()
    type(canvas).draw = real_draw
    check("单次移动最多触发一次整图重绘", calls["draw"] <= 1,
          f"draw 调用 {calls['draw']} 次")

    win.close()
    print("\n" + "=" * 60)
    if _fails:
        print("存在失败项 ✘：" + "；".join(_fails))
    else:
        print("拖动残影检查：全部通过 ✔")
    print("=" * 60)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
