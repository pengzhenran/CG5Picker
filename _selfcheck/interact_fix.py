"""本轮三处修改的回归（非产品代码，会弹一个真窗口，几秒后自动关闭）。

  1) **滚轮缩放必须以光标为中心**
     根因：`_data_xy` 把 Qt 的**逻辑**像素直接喂给 `transData` —— 既没乘
     `devicePixelRatioF()`（本机 1.5），也没翻转 y 轴（Qt 向下、mpl 向上）。
     这里既量"修复后锚点漂移"，也把"旧算法会漂多少"算出来做对照。

  2) **按 R 复位**
     量三件事：R 之后回到全览、`_view_*` 同步、**之后任何一次重绘都不回跳**
     （历史上"复位完勾一下复选框又跳回去"就是这么来的）。

  3) **黄色高亮**
     真窗口抓像素：打勾行 = 淡黄（且两个黄交替，测点分组信息不丢）；
     选中行 = 亮黄。另外用 WCAG 公式算文字/底色对比度。

用法：
    ..\\GravProc\\.venv\\Scripts\\python.exe _selfcheck\\interact_fix.py
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ.setdefault("CG5PICKER_CONFIG_DIR", __import__("tempfile").mkdtemp(prefix="cg5pick_check_"))   # 别往真安装目录写配置
sys.path.insert(0, str(ROOT / "CG5Picker"))
os.environ.pop("QT_QPA_PLATFORM", None)              # ★ 真窗口：dpr / 抓像素都要它

import math  # noqa: E402

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QWheelEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import (QAbstractItemView, QApplication,  # noqa: E402
                               QLineEdit)

from pickersrc import table_model as TM  # noqa: E402
from pickersrc.plots import ensure_cjk_font  # noqa: E402
from pickersrc.window import MainWindow, _create_app  # noqa: E402

DATA = (ROOT / "GravProc" / "examples" / "示例数据" / "宁夏"
        / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")

_fails: list[str] = []
_notes: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> bool:
    print(f"  [{'OK' if cond else 'FAIL'}] {label}" + (f"　{detail}" if detail else ""))
    if not cond:
        _fails.append(label)
    return cond


def note(text: str) -> None:
    print(f"  ··  {text}")
    _notes.append(text)


def _pump(app, sec: float = 0.25) -> None:
    app.processEvents()
    time.sleep(sec)
    app.processEvents()


def _rgb(color) -> tuple[int, int, int]:
    return (color.red(), color.green(), color.blue())


def _close(a, b, tol: int = 8) -> int:
    """两个 RGB 的最大通道差。"""
    if isinstance(a, tuple) and len(a) == 3 and isinstance(a[0], int):
        return max(abs(x - y) for x, y in zip(a, b))
    return max(abs(x - y) for x, y in zip(_rgb(a), _rgb(b)))


# ---------------------------------------------------------------- 对比度
def _lum(c: tuple[int, int, int]) -> float:
    def f(v: int) -> float:
        v /= 255.0
        return v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _contrast(a: tuple[int, int, int], b: tuple[int, int, int]) -> float:
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


# ---------------------------------------------------------------- 1) 缩放锚点
def check_zoom(plot, app) -> None:
    print("\n【1】滚轮缩放：必须以光标下的那一点为中心")
    ax, canvas, fig = plot._ax, plot._canvas, plot._fig
    pts = [(x, y) for (x, y, _t) in plot._pts.values() if x == x and y == y]
    if not check("图上有可用的点", len(pts) > 5, f"{len(pts)} 个"):
        return

    xl, yl = ax.get_xlim(), ax.get_ylim()
    cx, cy = (xl[0] + xl[1]) / 2, (yl[0] + yl[1]) / 2
    sx, sy = xl[1] - xl[0], yl[1] - yl[0]
    anchor = max(pts, key=lambda p: abs((p[0] - cx) / sx) + abs((p[1] - cy) / sy))
    off = (abs((anchor[0] - cx) / sx), abs((anchor[1] - cy) / sy))
    check("锚点明显偏离轴心（否则测不出问题）", min(off) > 0.15,
          f"离轴心 ({off[0]:.0%}, {off[1]:.0%})")

    dpr = float(canvas.devicePixelRatioF() or 1.0)
    phys = ax.transData.transform(anchor)                     # 物理像素, y 向上
    logic = QPointF(phys[0] / dpr, (fig.bbox.height - phys[1]) / dpr)
    # 旧实现会用的"锚点"：直接拿 Qt 逻辑坐标当显示坐标
    old_anchor = ax.transData.inverted().transform((logic.x(), logic.y()))
    note(f"devicePixelRatio={dpr}　画布 {canvas.width()}x{canvas.height()} 逻辑像素")
    note(f"光标处 Qt 逻辑坐标 ({logic.x():.1f}, {logic.y():.1f})；"
         f"物理像素 ({phys[0]:.1f}, {phys[1]:.1f})")

    # —— 旧算法的漂移（对照）：用错误锚点做同一套 0.8 缩放，量真锚点跑了多远
    f = 0.8
    ax.set_xlim(old_anchor[0] + (xl[0] - old_anchor[0]) * f,
                old_anchor[0] + (xl[1] - old_anchor[0]) * f)
    ax.set_ylim(old_anchor[1] + (yl[0] - old_anchor[1]) * f,
                old_anchor[1] + (yl[1] - old_anchor[1]) * f)
    old_phys = ax.transData.transform(anchor)
    drift_old = math.hypot(old_phys[0] - phys[0], old_phys[1] - phys[1])
    ax.set_xlim(*xl)
    ax.set_ylim(*yl)

    # —— 真实路径：造一个真滚轮事件，落在锚点上
    ev = QWheelEvent(logic, canvas.mapToGlobal(logic.toPoint()).toPointF(),
                     QPoint(0, 0), QPoint(0, 120), Qt.MouseButton.NoButton,
                     Qt.KeyboardModifier.NoModifier,
                     Qt.ScrollPhase.NoScrollPhase, False)
    handled = plot.zoom_at(ev)
    check("滚轮事件被我们的处理器接管", bool(handled))
    changed = (ax.get_xlim() != xl) and (ax.get_ylim() != yl)
    check("确实缩放了（范围变了）", changed,
          f"x {xl[0]:.3f}~{xl[1]:.3f} → {ax.get_xlim()[0]:.3f}~{ax.get_xlim()[1]:.3f}")

    new_phys = ax.transData.transform(anchor)
    drift_new = math.hypot(new_phys[0] - phys[0], new_phys[1] - phys[1])
    note(f"旧算法：光标下的点在缩放后跑掉 {drift_old:.1f} 物理像素")
    note(f"现算法：漂移 {drift_new:.2f} 物理像素（阈值 1.5）")
    check("缩放后光标下的点不动", drift_new <= 1.5, f"漂移 {drift_new:.2f} px")
    check("旧算法确实是错的（对照）", drift_old > 20.0, f"旧漂移 {drift_old:.1f} px")

    # 顺手验一次"轮子往下 = 缩小"，以及回到全览后锚点仍然正确
    ev2 = QWheelEvent(logic, canvas.mapToGlobal(logic.toPoint()).toPointF(),
                      QPoint(0, 0), QPoint(0, -120), Qt.MouseButton.NoButton,
                      Qt.KeyboardModifier.NoModifier,
                      Qt.ScrollPhase.NoScrollPhase, False)
    before = ax.get_xlim()
    plot.zoom_at(ev2)
    check("下滚 = 视野变大", (ax.get_xlim()[1] - ax.get_xlim()[0])
          > (before[1] - before[0]) * 1.05)
    plot.reset_view()
    _pump(app, 0.1)


# ---------------------------------------------------------------- 2) R 复位
def check_reset(plot, win, app) -> None:
    print("\n【2】按 R 复位回全览")
    ax, canvas = plot._ax, plot._canvas
    check("窗口级 R 快捷键已安装",
          getattr(win, "_sc_reset", None) is not None
          and win._sc_reset.key().toString().upper() == "R")
    check("R 是窗口级上下文（焦点不在画布上也管用）",
          win._sc_reset.context() == Qt.ShortcutContext.WindowShortcut)

    # 先缩进去，制造"非全览"
    home_x = tuple(plot._home_xlim)
    home_y = tuple(plot._home_ylim)
    ax.set_xlim(home_x[0] + (home_x[1] - home_x[0]) * 0.3,
                home_x[0] + (home_x[1] - home_x[0]) * 0.6)
    ax.set_ylim(home_y[0] + (home_y[1] - home_y[0]) * 0.3,
                home_y[0] + (home_y[1] - home_y[0]) * 0.6)
    plot._remember_view()
    canvas.draw_idle()
    _pump(app, 0.1)
    check("已缩进（为复位做前置条件）",
          abs(ax.get_xlim()[1] - ax.get_xlim()[0])
          < (home_x[1] - home_x[0]) * 0.5)

    QTest.keyClick(canvas, Qt.Key.Key_R)          # ★ 真按键事件，走 keyPressEvent
    _pump(app, 0.2)
    ok_x = abs(ax.get_xlim()[0] - home_x[0]) < 1e-9 and \
        abs(ax.get_xlim()[1] - home_x[1]) < 1e-9
    check("R → x 轴回到全览", ok_x, f"{ax.get_xlim()} vs {home_x}")
    check("R → _view_* 同步（复位结果被记住）",
          plot._view_xlim is not None
          and abs(plot._view_xlim[1] - plot._view_xlim[0]
                  - (home_x[1] - home_x[0])) < 1e-9)

    plot.redraw()                                  # 模拟"复位后又勾了一下复选框"
    _pump(app, 0.2)
    check("复位后再重绘不回跳",
          abs(ax.get_xlim()[0] - home_x[0]) < 1e-9
          and abs(ax.get_xlim()[1] - home_x[1]) < 1e-9, f"{ax.get_xlim()}")

    # 输入框里按 R 不该被抢（动态开关）
    # ★ 本机实测：`le.setFocus()` 之后 `app.focusChanged` 不一定马上发（窗口没被激活
    #   时焦点事件会丢），原来直接断言会 2/3 概率假红。这里先激活窗口 + 轮询等焦点，
    #   真拿不到焦点就**手动触发一次** `_on_focus_changed` 走同一条代码路径。
    le = QLineEdit(win)
    le.show()
    win.activateWindow()
    win.raise_()
    le.setFocus()
    _focused = False
    for _ in range(30):
        _pump(app, 0.05)
        if le.hasFocus():
            _focused = True
            break
    if not _focused:                              # 无头/未激活：手动走一遍槽函数
        win._on_focus_changed(None, le)
        _pump(app, 0.05)
    check("焦点在文本框时 R 让开", not win._sc_reset.isEnabled(),
          "焦点事件路径" if _focused else "手动触发槽函数（本机焦点事件没来）")
    le.deleteLater()
    win._on_focus_changed(None, None)
    _pump(app, 0.1)
    check("离开文本框后 R 恢复", win._sc_reset.isEnabled())


# ---------------------------------------------------------------- 3) 黄色高亮
def _band_hist(img, tv, row: int) -> dict[tuple[int, int, int], int]:
    scale = img.width() / max(tv.viewport().width(), 1)
    y0 = tv.rowViewportPosition(row)
    h = tv.rowHeight(row)
    hist: dict[tuple[int, int, int], int] = {}
    for yy in range(int(max(y0, 0) * scale) + 2, int((y0 + h) * scale) - 2):
        for xx in range(2, img.width(), 3):
            c = img.pixelColor(xx, yy)
            k = (c.red(), c.green(), c.blue())
            hist[k] = hist.get(k, 0) + 1
    return hist


def _dominant(hist: dict[tuple[int, int, int], int]) -> tuple[tuple[int, int, int], int]:
    if not hist:
        return (0, 0, 0), 0
    k = max(hist, key=lambda kk: hist[kk])
    return k, hist[k]


def check_colors(win, app) -> None:
    print("\n【3】黄色高亮：打勾行淡黄（两色交替）、选中行亮黄")
    tv, model, proxy = win.table, win.model, win.proxy
    tv.clearSelection()
    tv.scrollToTop()
    _pump(app, 0.25)

    def model_row_of(view_row: int) -> int:
        idx = proxy.index(view_row, 0)
        return proxy.mapToSource(idx).row() if idx.isValid() else -1

    def is_kept(view_row: int) -> bool:
        mr = model_row_of(view_row)
        return (0 <= mr < len(model._keep) and model._in_scope[mr]
                and model._keep[mr])

    def visible_kept() -> list[int]:
        vh = tv.viewport().height()
        out = []
        for v in range(proxy.rowCount()):
            y0 = tv.rowViewportPosition(v)
            if y0 < 0 or y0 + tv.rowHeight(v) > vh:
                continue
            if is_kept(v):
                out.append(v)
        return out

    all_kept = [v for v in range(proxy.rowCount()) if is_kept(v)]
    note(f"全表 {proxy.rowCount()} 行，其中「范围内且打勾」{len(all_kept)} 行；"
         f"第一条在第 {all_kept[0] if all_kept else -1} 个视图行")
    kept = visible_kept()
    if not kept and all_kept:
        # 「显示全部数据」模式下打勾行不一定在最上面 —— 滚到第一条再取
        tv.scrollTo(proxy.index(all_kept[0], 0),
                    QAbstractItemView.ScrollHint.PositionAtTop)
        _pump(app, 0.3)
        kept = visible_kept()
    # 只要能看到 1 行打勾行就够做像素判定了（默认条件变了以后，打勾行在一屏里更稀）
    if not check("找得到「打勾且在范围内」的可见行", len(kept) >= 1, f"{len(kept)} 行"):
        return
    kept = kept[:8]

    img = tv.viewport().grab().toImage()
    note(f"抓图 {img.width()}x{img.height()}（视口 {tv.viewport().width()}"
         f"x{tv.viewport().height()}）")
    shades: dict[str, int] = {"A": 0, "B": 0}
    bad: list[str] = []
    for v in kept:
        col, cnt = _dominant(_band_hist(img, tv, v))
        da, db = _close(col, _rgb(TM.C_KEEP_BG_A)), _close(col, _rgb(TM.C_KEEP_BG_B))
        if min(da, db) <= 8:
            shades["A" if da <= db else "B"] += 1
        else:
            bad.append(f"行{v}={col}")
    check("打勾行的底色是淡黄", not bad,
          f"取到 {shades['A'] + shades['B']}/{len(kept)} 行" + ("｜异常 " + ",".join(bad) if bad else ""))
    # 字体放大后一屏装不下几行打勾行；两色交替这件事 verify_all 在模型层逐行核过，
    # 这里只在取样够多时再确认一次像素层
    if len(kept) >= 3:
        check("淡黄仍是两个色交替（测点分组信息没丢）",
              shades["A"] > 0 and shades["B"] > 0,
              f"A={shades['A']} 行, B={shades['B']} 行")
    else:
        note(f"本屏只有 {len(kept)} 行打勾行，两色交替改由 verify_all 在模型层核对")
    note(f"淡黄 A={_rgb(TM.C_KEEP_BG_A)} B={_rgb(TM.C_KEEP_BG_B)}")

    # 选中一行 → 亮黄
    target = kept[0]
    tv.selectRow(target)
    _pump(app, 0.25)
    img2 = tv.viewport().grab().toImage()
    col, cnt = _dominant(_band_hist(img2, tv, target))
    check("选中行是亮黄", _close(col, _rgb(TM.C_SEL_BG)) <= 8,
          f"实测 {col}（期望 {_rgb(TM.C_SEL_BG)}），占该行 {cnt} 像素")
    other = next((v for v in kept if v != target), None)
    if other is None:
        note("本屏只有 1 行打勾行，「未选中仍是淡黄」改由 verify_all 在模型层核对")
    else:
        col2, _c2 = _dominant(_band_hist(img2, tv, other))
        check("没被选中的打勾行仍是淡黄",
              min(_close(col2, _rgb(TM.C_KEEP_BG_A)),
                  _close(col2, _rgb(TM.C_KEEP_BG_B))) <= 8,
              f"行{other}={col2}")

    # 对比度（WCAG）：文字要压得住底色
    c_keep = _contrast(_rgb(TM.C_CHECKED_TEXT), _rgb(TM.C_KEEP_BG_A))
    c_keep_b = _contrast(_rgb(TM.C_CHECKED_TEXT), _rgb(TM.C_KEEP_BG_B))
    c_sel = _contrast(_rgb(TM.C_CHECKED_TEXT), _rgb(TM.C_SEL_BG))
    c_sel_txt = _contrast(_rgb(TM.C_SEL_TEXT), _rgb(TM.C_SEL_BG))
    note(f"对比度：打勾字/淡黄A {c_keep:.2f}:1、/淡黄B {c_keep_b:.2f}:1、"
         f"选中字 {c_sel:.2f}:1、选中近黑字 {c_sel_txt:.2f}:1")
    check("打勾行文字对比度 ≥ 4.5", min(c_keep, c_keep_b) >= 4.5)
    check("选中行文字对比度 ≥ 4.5", max(c_sel, c_sel_txt) >= 4.5)

    tv.clearSelection()
    _pump(app, 0.1)


def main() -> int:
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()
    win = MainWindow()
    win.resize(1500, 950)
    win.show()
    win.raise_()
    win.activateWindow()
    active = QTest.qWaitForWindowActive(win, 3000)
    win.load_file(str(DATA))
    win.show_all_data()
    _pump(app, 0.5)
    print(f"窗口 active = {bool(active)}（选中行无论激活与否都该是亮黄）")

    if win.f is None or not win.plot._pts:
        print("数据没载入成功，后面都测不了")
        return 1

    check_zoom(win.plot, app)
    check_reset(win.plot, win, app)
    check_colors(win, app)

    _pump(app, 0.3)
    win.close()
    print("\n" + "=" * 68)
    if _fails:
        print(f"失败 {len(_fails)} 项：")
        for f in _fails:
            print("  -", f)
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
