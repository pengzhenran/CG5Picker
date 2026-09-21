"""交互端到端自检（非产品代码）：用**真实 Qt 事件**驱动图形，不直接调内部方法。

为什么单独做这个：之前几轮自检都是直接调 `_on_press` / `_on_move` / `_on_scroll`，
那会绕过 Qt → matplotlib 的事件派发。实测就漏过两个真 bug：
  · 滚轮挂在 matplotlib `scroll_event` 上，Qt 事件根本到不了（滚轮没反应）
  · 框选后没清内部状态，悬停信息此后再也不出现

所以这里一律用 `QApplication.sendEvent` 发真事件，验证：
  滚轮缩放 / 左键拖动平移 / Shift+拖动框选 / Ctrl+拖动取反 /
  单击选中 / Ctrl+单击取反 / 悬停信息 / 复位 / 交互期间坐标轴几何不变

用法（在项目根目录）：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\interact_e2e.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CG5PICKER_CONFIG_DIR", __import__("tempfile").mkdtemp(prefix="cg5pick_check_"))   # 别往真安装目录写配置
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pickersrc.plots import ensure_cjk_font  # noqa: E402
from pickersrc.rules import Cond  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402

SRC = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
       / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")

_fails: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        _fails.append(label)
    return bool(cond)


def main() -> int:
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.resize(1400, 900)
    win.show()
    win.load_file(str(SRC))
    win.conds = [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})]
    win._refresh_cond_table()
    win._render()
    win.show_all_data()
    app.processEvents()

    p = win.plot
    canvas = p._canvas
    # 把画布撑到接近真实面板尺寸，这样像素↔数据换算才有意义
    canvas.resize(760, 520)
    app.processEvents()
    p.reset_view()
    app.processEvents()
    print(f"画布 {canvas.width()}x{canvas.height()}　点数 {len(p._pts)}")

    def to_px(data_x, data_y):
        """数据坐标 → **Qt 画布像素**坐标。

        ★ y 轴方向：matplotlib 显示坐标原点在**左下**，Qt 部件坐标原点在**左上**，
          两者相差一次高度翻转（实测 e.y = 画布高 − qt_y）。直接拿 transData 的
          结果去构造 QMouseEvent，点会整体偏掉，于是"点击/悬停都对不上" ——
          这是测试脚手架自己的坑，不是程序的问题。
        """
        x, y = p._ax.transData.transform((data_x, data_y))
        return QPointF(float(x), float(canvas.height()) - float(y))

    def send_mouse(kind, px, buttons=Qt.MouseButton.LeftButton,
                   mods=Qt.KeyboardModifier.NoModifier):
        ev = QMouseEvent(QEvent.Type(kind), px, canvas.mapToGlobal(px.toPoint()),
                         Qt.MouseButton.LeftButton, buttons, mods)
        QApplication.sendEvent(canvas, ev)
        app.processEvents()

    def set_mods(*, shift=False, ctrl=False):
        """注入修饰键状态（离屏下没有真键盘，只能用程序提供的自检钩子）。"""
        p._forced_mods = (bool(shift), bool(ctrl))

    def clear_mods():
        p._forced_mods = None

    def send_wheel(px, delta):
        ev = QWheelEvent(px, canvas.mapToGlobal(px.toPoint()),
                         QPoint(0, 0), QPoint(0, delta),
                         Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
                         Qt.ScrollPhase.NoScrollPhase, False)
        QApplication.sendEvent(canvas, ev)
        app.processEvents()

    def geom():
        return tuple(round(float(v), 6) for v in p._ax.get_position().bounds)

    def lims():
        return tuple(float(v) for v in p._ax.get_xlim())

    far = max(p._pts, key=lambda r: p._pts[r][0])
    near = min(p._pts, key=lambda r: p._pts[r][0])

    # ---------------------------------------------------------------- 滚轮
    print("\n[滚轮缩放]")
    x0 = lims()
    send_wheel(to_px(*p._pts[far][:2]), 120)
    x1 = lims()
    check("滚轮放大生效（真实事件）", (x1[1] - x1[0]) < (x0[1] - x0[0]),
          f"跨度 {x0[1] - x0[0]:.3f} → {x1[1] - x1[0]:.3f}")
    send_wheel(to_px(*p._pts[far][:2]), -120)
    x2 = lims()
    check("反向滚轮缩小生效", (x2[1] - x2[0]) > (x1[1] - x1[0]),
          f"跨度 {x1[1] - x1[0]:.3f} → {x2[1] - x2[0]:.3f}")

    # ---------------------------------------------------------------- 复位
    print("\n[复位]")
    p.reset_view()
    app.processEvents()
    xr = lims()
    check("复位回到全览", abs((xr[1] - xr[0]) - (x0[1] - x0[0])) < 1e-6,
          f"跨度 {xr[1] - xr[0]:.3f}（全览 {x0[1] - x0[0]:.3f}）")

    # ---------------------------------------------------------------- 平移
    print("\n[左键拖动平移]")
    p.reset_view()
    app.processEvents()
    g0, xa = geom(), lims()
    pa = to_px(*p._pts[far][:2])
    pb = QPointF(pa.x() - 90, pa.y())          # 往左拖 90px
    send_mouse(QEvent.Type.MouseButtonPress, pa)
    send_mouse(QEvent.Type.MouseMove, pb, buttons=Qt.MouseButton.LeftButton)
    send_mouse(QEvent.Type.MouseButtonRelease, pb, buttons=Qt.MouseButton.NoButton)
    xb = lims()
    check("拖动改变了视图范围（平移）", xb != xa,
          f"左端 {xa[0]:.3f} → {xb[0]:.3f}")
    # 往左拖 90px = 视图向数据增大方向移动 → xlim 左端变大
    check("平移方向正确（往左拖，视图右移）", xb[0] > xa[0],
          f"Δ={xb[0] - xa[0]:+.3f}（往左拖 90px）")
    check("平移期间坐标轴几何不动", geom() == g0, f"{geom()}")
    check("抬起后可以继续悬停（状态已清理）",
          p._pan_from is None and p._drag_from is None)

    # ---------------------------------------------------------------- 悬停信息
    print("\n[悬停信息（左下角）]")
    send_mouse(QEvent.Type.MouseMove, to_px(*p._pts[far][:2]),
               buttons=Qt.MouseButton.NoButton)
    check("悬停后左下角信息区有内容", p._info.get_visible() and bool(p._info.get_text()),
          repr(p._info.get_text().splitlines()[0] if p._info.get_text() else ""))
    check("信息不含温度/源行",
          "温度" not in p._info.get_text() and "源行" not in p._info.get_text())
    ax_p, ip = p._ax.get_position(), p._info.get_position()
    check("信息区在坐标轴外左下角", ip[0] < ax_p.x0 and ip[1] < ax_p.y0,
          f"信息 {tuple(round(float(v), 3) for v in ip)}　轴 {round(float(ax_p.x0), 3)},{round(float(ax_p.y0), 3)}")

    # ---------------------------------------------------------------- 单击 / Ctrl+单击
    print("\n[单击 = 选中；Ctrl+单击 = 取反]")
    # ★ 先把视野复位：前面的平移测试把视图挪走了，被点的那个点可能已经不在坐标轴内，
    #   那样 to_px 换算出来的位置落在轴外，press 会被直接忽略（"点了没反应"）。
    p.reset_view()
    app.processEvents()
    kept = next(iter(win._keep_rows))
    n_keep = len(win._keep_rows)
    send_mouse(QEvent.Type.MouseButtonPress, to_px(*p._pts[kept][:2]))
    send_mouse(QEvent.Type.MouseButtonRelease, to_px(*p._pts[kept][:2]),
               buttons=Qt.MouseButton.NoButton)
    check("单击只选中、不剔除",
          len(win._keep_rows) == n_keep and kept in win._selected_source_rows(),
          f"保留 {n_keep}，选中 {win._selected_source_rows()}")
    set_mods(ctrl=True)
    send_mouse(QEvent.Type.MouseButtonPress, to_px(*p._pts[kept][:2]),
               mods=Qt.KeyboardModifier.ControlModifier)
    send_mouse(QEvent.Type.MouseButtonRelease, to_px(*p._pts[kept][:2]),
               buttons=Qt.MouseButton.NoButton, mods=Qt.KeyboardModifier.ControlModifier)
    check("Ctrl+单击 → 取反（剔除）",
          len(win._keep_rows) == n_keep - 1 and kept in win.manual_drop,
          f"{n_keep} → {len(win._keep_rows)}")
    send_mouse(QEvent.Type.MouseButtonPress, to_px(*p._pts[kept][:2]),
               mods=Qt.KeyboardModifier.ControlModifier)
    send_mouse(QEvent.Type.MouseButtonRelease, to_px(*p._pts[kept][:2]),
               buttons=Qt.MouseButton.NoButton, mods=Qt.KeyboardModifier.ControlModifier)
    check("再 Ctrl+单击 → 取消（恢复）", len(win._keep_rows) == n_keep)
    clear_mods()
    win._reset_manual()

    # 回归：Ctrl+单击**不能**被当成框选（修复前它只进入框选、点击不生效）
    set_mods(ctrl=True)
    _row = next(iter(win._keep_rows))
    _n = len(win._keep_rows)
    send_mouse(QEvent.Type.MouseButtonPress, to_px(*p._pts[_row][:2]),
               mods=Qt.KeyboardModifier.ControlModifier)
    send_mouse(QEvent.Type.MouseButtonRelease, to_px(*p._pts[_row][:2]),
               buttons=Qt.MouseButton.NoButton, mods=Qt.KeyboardModifier.ControlModifier)
    check("Ctrl+单击不被误判为框选（取反生效）",
          len(win._keep_rows) == _n - 1, f"{_n} → {len(win._keep_rows)}")
    clear_mods()
    win._reset_manual()

    # ---------------------------------------------------------------- 框选
    print("\n[Shift+拖动 = 框选]")
    xs = [p._pts[s][0] for s in p._pts]
    ys = [p._pts[s][1] for s in p._pts]
    mid_x, mid_y = (min(xs) + max(xs)) / 2, (min(ys) + max(ys)) / 2
    q0, q1 = to_px(mid_x, mid_y), to_px(max(xs), max(ys))
    set_mods(shift=True)
    send_mouse(QEvent.Type.MouseButtonPress, q0, mods=Qt.KeyboardModifier.ShiftModifier)
    check("Shift+按下只进入待框选（还不画橡皮筋）",
          p._box is None and (p._rect is None or not p._rect.get_visible()))
    send_mouse(QEvent.Type.MouseMove, q1, buttons=Qt.MouseButton.LeftButton,
               mods=Qt.KeyboardModifier.ShiftModifier)
    check("Shift+移动后出现橡皮筋",
          p._box is not None and p._rect is not None and p._rect.get_visible())
    send_mouse(QEvent.Type.MouseButtonRelease, q1, buttons=Qt.MouseButton.NoButton,
               mods=Qt.KeyboardModifier.ShiftModifier)
    want = {s for s in p._pts if p._pts[s][0] >= mid_x and p._pts[s][1] >= mid_y}
    got = set(win._selected_source_rows())
    check("框选结果与几何一致并同步表格", got == want,
          f"框到 {len(got)}，应 {len(want)}")
    check("框选后内部状态已清（悬停仍可用）", p._box is None)
    clear_mods()
    send_mouse(QEvent.Type.MouseMove, to_px(*p._pts[far][:2]),
               buttons=Qt.MouseButton.NoButton)
    check("框选后悬停信息仍能出现", p._info.get_visible())

    # ---------------------------------------------------------------- Ctrl+框选取反
    print("\n[Ctrl+拖动 = 框选并整批取反]")
    # 前面几段改过视野，这里只取**当前可见范围内**的点来构造框选矩形：
    # 若按下点落在坐标轴之外，matplotlib 会判定 inaxes=False，交互根本不会开始
    # （这是测试取样的问题，不是程序的问题）。
    p._canvas.draw()
    app.processEvents()
    xl_d, xh_d = (float(v) for v in p._ax.get_xlim())
    yl_d, yh_d = (float(v) for v in p._ax.get_ylim())
    vis = [s for s in p._pts
           if xl_d <= p._pts[s][0] <= xh_d and yl_d <= p._pts[s][1] <= yh_d]
    check("当前视野内有可见点可供框选", len(vis) >= 4, f"{len(vis)} 个")
    vx = [p._pts[s][0] for s in vis]
    vy = [p._pts[s][1] for s in vis]
    mid_x = min(vx) + (max(vx) - min(vx)) * 0.5
    mid_y = min(vy) + (max(vy) - min(vy)) * 0.5
    # 只比**当前范围内**的点：范围外的观测本来就不参与保留状态
    scope_set = set(win.scope)
    some = [s for s in vis
            if s in scope_set and p._pts[s][0] <= mid_x and p._pts[s][1] <= mid_y]
    print(f"      可见 {len(vis)} 个；矩形内 {len(some)} 条")
    if some:
        r0, r1 = to_px(min(vx), min(vy)), to_px(mid_x, mid_y)
        before = {s: (s in set(win._keep_rows)) for s in some}
        # 取样前不该残留人工干预（前面几段都调过 _reset_manual）
        stray = [s for s in some if s in win.manual_keep or s in win.manual_drop]
        check("取样前无残留人工干预", not stray, f"残留 {stray[:5]}")
        # 保留状态应与"自动条件判定"一致（留 = 没有处理理由）
        odd = [s for s in some if before[s] == (s in win.auto_reason)]
        check("取样状态与自动判定一致", not odd,
              f"不一致 {odd[:5]}")
        set_mods(ctrl=True)
        check("Ctrl 修饰键已注入", p._mods() == (False, True), f"{p._mods()}")
        send_mouse(QEvent.Type.MouseButtonPress, r0,
                   mods=Qt.KeyboardModifier.ControlModifier)
        check("Ctrl+按下进入待框选状态", p._box_pending,
              f"pending={p._box_pending} toggle={p._box_toggle} "
              f"drag_from={p._drag_from is not None}")
        send_mouse(QEvent.Type.MouseMove, r1, buttons=Qt.MouseButton.LeftButton,
                   mods=Qt.KeyboardModifier.ControlModifier)
        check("Ctrl+移动后橡皮筋出现",
              p._box is not None and p._rect is not None and p._rect.get_visible(),
              f"box={p._box is not None} rect={None if p._rect is None else p._rect.get_visible()}")
        send_mouse(QEvent.Type.MouseButtonRelease, r1,
                   buttons=Qt.MouseButton.NoButton,
                   mods=Qt.KeyboardModifier.ControlModifier)
        after = {s: (s in set(win._keep_rows)) for s in some}
        flipped = sum(1 for s in some if after[s] != before[s])
        not_flipped = [s for s in some if after[s] == before[s]]
        check("Ctrl+框选整批取反", flipped == len(some),
              f"{flipped}/{len(some)} 条状态翻转"
              + (f"；未翻转 {not_flipped[:5]}" if not_flipped else ""))
        clear_mods()
        win._reset_manual()
    else:
        check("Ctrl+框选样本非空", False, "没取到样本")

    # ---------------------------------------------------------------- 几何稳定
    print("\n[交互期间几何稳定]")
    g = geom()
    seq = []
    a = to_px(*p._pts[near][:2])
    send_mouse(QEvent.Type.MouseButtonPress, a)
    for k in range(1, 8):
        send_mouse(QEvent.Type.MouseMove, QPointF(a.x() + k * 12, a.y()),
                   buttons=Qt.MouseButton.LeftButton)
        seq.append(geom())
    send_mouse(QEvent.Type.MouseButtonRelease, QPointF(a.x() + 84, a.y()),
               buttons=Qt.MouseButton.NoButton)
    check("拖动全过程坐标轴几何只有一个取值（不抖）",
          len(set(seq)) == 1 and seq[0] == g, f"{len(set(seq))} 个取值")

    win.close()
    print("\n" + "=" * 68)
    if _fails:
        print(f"存在失败项 ✘（{len(_fails)}）：")
        for f in _fails:
            print(f"  · {f}")
    else:
        print("交互端到端：全部通过 ✔")
    print("=" * 68)
    return 1 if _fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
