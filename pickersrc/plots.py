"""图形 —— 四种视图，与大软件（GravProc 观测挑选台）一致。

  · 读数 vs 时间         —— 看漂移与跳变
  · 互差带（按测点居中） —— 相对各自测点中位数，叠加 ±5 / ±1 μGal 限差带
  · 倾斜 / 温度 vs 时间  —— 看仪器状态
  · 仪器潮汐 vs 理论潮汐 —— 看潮汐改正是否合理（理论值按规范公式现算）

三态着色：**保留**、**条件剔除**（被勾选条件剔除）、**人工剔除**（表格里手动改的）。
鼠标悬停 → 读数气泡；滚轮缩放 / 拖动平移用 matplotlib 导航工具条；
点击散点 → 回调**源文件行号**，用于在表格里定位该观测。
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np
from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg, NavigationToolbar2QT
from matplotlib.figure import Figure
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from .cg5 import CG5File
from .display import format_id_cell
from .grouping import cell_of as _cell
from .grouping import group_by_station, hms_to_hours as _hms_to_hours
from .rules import (C_DECTIME, C_DUR, C_LINE, C_RAW, C_SD, C_STATION, C_TEMP,
                    C_TIDE, C_TIME, C_TILTX, C_TILTY, numeric)

__all__ = ["VIEW_KINDS", "ObsPlot", "solid_earth_tide_uGal", "theory_tide_uGal"]

#: 视图 key → 中文标题
VIEW_KINDS: dict[str, str] = {
    "time": "读数 vs 时间",
    "band": "互差带（按测点居中）",
    "quality": "倾斜 / 温度 vs 时间",
    "tide": "仪器潮汐 vs 理论潮汐",
}

COL_ACCENT = "#1a5fb4"
COL_KEPT_BY_HAND = "#0f766e"      # 人工保留：从"条件剔除"里手工捞回来的
COL_OK = "#1a7f37"
COL_WARN = "#b45309"
COL_ERROR = "#b91c1c"
COL_MUTED = "#9aa3ad"
COL_DARK = "#24292f"
COL_FRAME = "#8a8f98"          # 坐标轴框线颜色
FIGURE_DPI = 100

#: 互差限差参考带（μGal）：(限差, 颜色, 图例文字)
#: 图例文字刻意保持短 —— 它要待在图左上角**坐标轴之外**那条窄带里（左边距只有 0.175），
#: 名字一长就会越过坐标轴左沿（自检里量着这一条）。
BANDS: tuple[tuple[float, str, str], ...] = (
    (5.0, COL_WARN, "±5 μGal"),
    (1.0, COL_OK, "±1 μGal"),
)


class _Canvas(FigureCanvasQTAgg):
    """接管滚轮缩放与左键拖动平移的 Qt 画布。

    为什么不挂 matplotlib 的 `scroll_event`：实测 Qt 后端下该回调收不到事件，
    滚轮完全没反应。这里在 Qt 事件层直接处理，行为可控且可测。
    """

    def __init__(self, figure, owner: "ObsPlot") -> None:
        super().__init__(figure)
        self._owner = owner

    def keyPressEvent(self, event) -> None:          # noqa: N802 (Qt 命名)
        """R / Home = 图形复位（回到全览）。

        挂在画布上是"自洽且可测"的一条路：`QTest.keyClick(canvas, R)` 直接命中，
        不依赖窗口是否 active。但滚轮缩放**不会**给画布焦点，焦点往往还停在刚
        点过的按钮上，所以窗口级还额外挂了一个 R 快捷键（见 `window.py`）。
        """
        if event.key() in (Qt.Key.Key_R, Qt.Key.Key_Home):
            try:
                self._owner.reset_view()
            except Exception:                        # noqa: BLE001 别让交互崩界面
                pass
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event) -> None:           # noqa: N802 (Qt 命名)
        super().resizeEvent(event)
        # ★ 关键：把 figure 的英寸尺寸**同步**成画布的像素尺寸。
        #   不同步的话 figure 会一直用它构造时的大小（实测画布 338x422 而
        #   figure 还是 507x633）：内容按错误比例绘制并被裁掉，命中换算全错，
        #   拖动时画面反复重排 —— 这就是"疯狂抖动"的根因。
        #   注意不要在这里清 `_home_xlim`：边距是比例值，尺寸变化不改变数据范围；
        #   清掉会让「复位」失去目标。需要重新全览的情形由 `_data_id` / `set_kind` 管。
        try:
            size = (self.width(), self.height())
            if self._owner._ax_px == size:
                return
            self._owner._ax_px = size
            _fit_figure(self, self.figure)
            _apply_margins(self.figure)
        except Exception:                            # noqa: BLE001
            pass

    def wheelEvent(self, event) -> None:            # noqa: N802 (Qt 命名)
        try:
            handled = self._owner.zoom_at(event)
        except Exception:                           # noqa: BLE001 别让交互崩界面
            handled = False
        if not handled:
            super().wheelEvent(event)
        else:
            event.accept()


# ==========================================================================
# 中文字体
# ==========================================================================
_CJK_CANDIDATES = (
    "Microsoft YaHei", "微软雅黑", "SimHei", "黑体", "Noto Sans CJK SC",
    "Source Han Sans SC", "SimSun", "宋体", "Arial Unicode MS",
)
_font_done = False


def _quiet_qt_fonts() -> None:
    """Qt6 不再自带字体，缺字体目录时会往 stderr 打一条警告 —— 与本工具无关，静音。"""
    import logging

    logging.getLogger("PySide6").setLevel(logging.ERROR)


def ensure_cjk_font() -> str:
    """让 matplotlib 能画中文（找不到就退回默认字体，不抛错）。"""
    global _font_done
    import matplotlib
    from matplotlib import font_manager

    _quiet_qt_fonts()
    if _font_done:
        return str(matplotlib.rcParams.get("font.sans-serif", [""])[0])
    have = {f.name for f in font_manager.fontManager.ttflist}
    for name in _CJK_CANDIDATES:
        if name in have:
            matplotlib.rcParams["font.sans-serif"] = [name, "DejaVu Sans"]
            break
    matplotlib.rcParams["axes.unicode_minus"] = False
    # ★ 图上的字也一起放大（刻度、轴标签都吃这些默认值）
    matplotlib.rcParams["font.size"] = PLOT_FONT_SIZE
    matplotlib.rcParams["xtick.labelsize"] = PLOT_FONT_SIZE - 1
    matplotlib.rcParams["ytick.labelsize"] = PLOT_FONT_SIZE - 1
    matplotlib.rcParams["axes.labelsize"] = PLOT_FONT_SIZE
    _font_done = True
    return str(matplotlib.rcParams.get("font.sans-serif", [""])[0])


# ==========================================================================
# 理论固体潮（规范公式，零潮汐系统）
# ==========================================================================
_D2R = math.pi / 180.0


def _julian_day(y: float, m: float, d: float) -> float:
    yy, mm = y - 1900.0, m - 1.0
    w = math.floor(yy / 4.0)
    dd = d + (-0.5 if (y % 4 == 0 and mm < 1) else 0.0)
    month_days = (0.0 if mm == 0 else
                  31.0 if mm == 1 else
                  math.floor(mm * 365.0 / 12.0) - math.floor(10.0 / (4.0 + mm)))
    return yy * 365.0 + w - 0.5 + month_days + dd + 2415020.0


def solid_earth_tide_uGal(year: int, month: int, day: int, hour: float,
                          lat_deg: float, lon_deg: float,
                          tide_factor: float = 1.16) -> float:
    """固体潮改正（μGal），规范公式（DZ/T 0082-2021 附录 H）。

    与 GravProc `kernel/tide.py` 同一套式子与符号约定：
    `δg_b = −(δth·G(t) − δfc)`。回归基准 50.664 μGal。
    """
    T = (_julian_day(year, month, day) - 2415020.0 + (hour - 8.0) / 24.0) / 36525.0
    lon_r, lat_r = lon_deg * _D2R, lat_deg * _D2R

    s = (270.43659 + 481267.89057 * T + 0.00198 * T ** 2 + 0.000002 * T ** 3) * _D2R
    h = (279.69668 + 36000.76892 * T + 0.0003 * T ** 2) * _D2R
    p = (334.32956 + 4069.03403 * T - 0.01032 * T ** 2 - 0.00001 * T ** 3) * _D2R
    N = (259.18328 - 1934.14201 * T + 0.00208 * T ** 2 + 0.000002 * T ** 3) * _D2R
    ps = (281.22083 + 1.71902 * T + 0.00045 * T ** 2 + 0.000003 * T ** 3) * _D2R
    eslon = (23.45229 - 0.01301 * T - 0.000002 * T ** 2) * _D2R

    c_r = (1 + 0.0545 * math.cos(s - p) + 0.0030 * math.cos(2 * (s - p))
           + 0.01 * math.cos(s - 2 * h + p) + 0.0082 * math.cos(2 * (s - h))
           + 0.0006 * math.cos(2 * s - 3 * h + ps) + 0.0009 * math.cos(3 * s - 2 * h - p))

    lamda = (s - 0.0032 * math.sin(h - ps) - 0.001 * math.sin(2 * h - 2 * p)
             + 0.001 * math.sin(s - 3 * h + p + ps) + 0.0222 * math.sin(s - 2 * h + p)
             + 0.0007 * math.sin(s - h - p + ps) - 0.0006 * math.sin(s - h)
             + 0.1098 * math.sin(s - p) - 0.0005 * math.sin(s + h - p - ps)
             + 0.0008 * math.sin(2 * s - 3 * h + ps) + 0.0115 * math.sin(2 * s - 2 * h)
             + 0.0037 * math.sin(2 * s - 2 * p) - 0.0020 * math.sin(2 * s - 2 * N)
             + 0.0009 * math.sin(3 * s - 2 * h - p))

    beta = (-0.0048 * math.sin(p - N) - 0.0008 * math.sin(2 * h - p - N)
            + 0.003 * math.sin(s - 2 * h + N) + 0.0895 * math.sin(s - N)
            + 0.001 * math.sin(2 * s - 2 * h + p - N) + 0.0049 * math.sin(2 * s - p - N)
            + 0.0006 * math.sin(3 * s - 2 * h - N))

    sin_delt = (math.sin(eslon) * math.sin(lamda) * math.cos(beta)
                + math.cos(eslon) * math.sin(beta))
    hexingshi = (hour - 8.0) * 15.0 * _D2R + h + lon_r - math.pi

    sph_r = (lat_deg - 0.193296 * math.sin(2 * lat_r)) * _D2R
    cos_delt_H = (math.cos(beta) * math.cos(lamda) * math.cos(hexingshi)
                  + math.sin(hexingshi) * (math.cos(eslon) * math.cos(beta) * math.sin(lamda)
                                           - math.sin(eslon) * math.sin(beta)))
    cos_Z = math.sin(sph_r) * sin_delt + math.cos(sph_r) * cos_delt_H

    cs_rs = 1 + 0.0168 * math.cos(h - ps) + 0.0003 * math.cos(2 * h - 2 * ps)
    lamda_s = h + 0.0335 * math.sin(h - ps) + 0.0004 * math.sin(2 * (h - ps))
    cos_zs = (math.sin(sph_r) * math.sin(eslon) * math.sin(lamda_s)
              + math.cos(sph_r) * (math.cos(lamda_s) * math.cos(hexingshi)
                                   + math.sin(hexingshi) * math.cos(eslon) * math.sin(lamda_s)))

    f_fai = 0.998327 + 0.00167 * math.cos(2 * lat_r)
    defc = -4.83 + 15.73 * math.sin(sph_r) ** 2 - 1.59 * math.sin(sph_r) ** 4
    gt = (-165.17 * f_fai * c_r ** 3 * (cos_Z ** 2 - 1.0 / 3.0)
          - 1.37 * f_fai ** 2 * c_r ** 4 * cos_Z * (5 * cos_Z ** 2 - 3.0)
          - 76.08 * f_fai * cs_rs ** 3 * (cos_zs ** 2 - 1.0 / 3.0))
    return -(tide_factor * gt - defc)


def theory_tide_uGal(f: CG5File, idx: Sequence[int], date: str = "",
                     lat: float | None = None, lon: float | None = None) -> list[float]:
    """按规范公式现算理论固体潮（μGal）；某行缺坐标或日期 → 该行 nan。

    ★ **逐行**取"这一行所属 Survey 的经纬度 + 这一行自己的日期"，原因是：
      · 同一文件里不同 Survey 的坐标可以完全不同 —— 实测 `914_20250701.txt`：
        `914` = 114.4000E / 30.5000N，而 `nx914` = 106.6000E / 37.4000N；
      · 范围跨天时，日期也逐行不同。
      早期实现只在"恰好只选中一个 Survey"时才去查坐标（`len(surveys) == 1`），
      而且 `set_data` 传进来的 `date` 是空串 —— 两者一叠加，理论固体潮**永远**
      是满屏 nan，界面上只能看到"理论潮汐（无经纬度算不了）"。
      所以这不是文件缺经纬度，是取值口径错了。
    `date / lat / lon` 仅在"该行自己取不到"时兜底。
    """
    out = [float("nan")] * len(idx)
    cache: dict[tuple[int, int, int, float, float], float] = {}
    for k, i in enumerate(idx):
        r = f.rows[i]
        sv = f.survey_info(r.survey) or {}
        la = sv.get("latitude")
        lo = sv.get("longitude")
        if la is None:
            la = lat
        if lo is None:
            lo = lon
        d = r.date or date
        if la is None or lo is None or not d:
            continue
        hh = _hms_to_hours(_cell(r, f.columns, C_TIME))
        if hh != hh:                                  # nan：时刻列取不到
            continue
        try:
            y, m, dd = (int(x) for x in str(d).split("-")[:3])
        except (ValueError, AttributeError):
            continue
        # ★ 小时**必须进缓存键**：固体潮全天都在变，只按 (日期, 经纬度) 缓存会把
        #   一天算成同一个常数（实测就是这么发现的：理论值 min == max）。
        key = (y, m, dd, round(hh, 6), round(float(la), 6), round(float(lo), 6))
        if key not in cache:
            try:
                cache[key] = solid_earth_tide_uGal(y, m, dd, hh,
                                                   float(la), float(lo))
            except (ValueError, OverflowError):
                cache[key] = float("nan")
        out[k] = cache[key]
    return out


# ==========================================================================
# 绘图部件
# ==========================================================================
#: 固定边距（左, 右, 下, 上）—— 留够刻度/轴标签/标题的位置。
#: 用固定值取代 constrained layout，交互时几何才不会抖。
#: ★ 左边距从 0.235 收到 **0.175**：用户要求"坐标轴加宽，即纵轴左移"。
#:   那条窄带里仍要放下"图例（坐标轴之外）+ y 刻度 + y 轴标签"，所以配合把图例文字
#:   改短（见 `_legend_top_left`）—— 自检里量着"图例右沿 ≤ 轴左沿"这条。
#: 下边距 0.17：字体调大后，左下角"悬停信息"（5 行）与右下角"按键说明"（3 行）都在这条里。
#: 上边距 0.895：只放一行标题（视图名）；按键说明**不**放这儿 ——
#: 标题块变高会把坐标轴比例挤变，见 `_apply_margins` 的说明。
_MARGINS = (0.175, 0.975, 0.17, 0.895)
#: matplotlib 里跟界面同步放大的字号（用户："所有字体都加大"）
PLOT_FONT_SIZE = 12.0        # 刻度/轴标签（rcParams["font.size"]）
TITLE_FONT_SIZE = 11.0       # 标题（只有视图名）
HINT_FONT_SIZE = 11.0        # 图下方右侧的按键说明（用户要求"字体加大"）
#: 图例 9.0：它要待在图左上角**坐标轴之外**那条窄带里（左边距 0.235），
#: 放到 10 会越过坐标轴左沿（自检里量过：右沿 0.238 > 轴左沿 0.225）。
LEGEND_FONT_SIZE = 9.0
INFO_FONT_SIZE = 10.0        # 左下角悬停信息
#: 画在图上的按键说明（原来塞在标题里，字体放大后放不下就被删了 ——
#: 用户反馈"图形里的按键说明消失了，要有 R 键说明"，所以挂回来；后来又要求"字体加大"）。
#: ★ 分**三行**而不是两行：11pt 下两行里最长那行约 310pt，比图还宽（实测左沿跑到 -80px），
#:   而且会压到左下角的悬停信息。拆成三行后最长约 195pt，右下角放得下。
HINT_LINES = ("单击=选中　Ctrl+单击=取反",
              "拖动=平移　滚轮=缩放　R=复位",
              "Shift+拖动=框选　Ctrl+拖动=框选取反")


def _canvas_dpr(canvas) -> float:
    """画布的设备像素比（Windows 显示缩放 125% → 1.25）。拿不到就当 1。"""
    try:
        r = float(canvas.devicePixelRatioF())
        return r if r > 0 else 1.0
    except Exception:                                # noqa: BLE001
        return 1.0


def _fit_figure(canvas, fig) -> None:
    """让 figure 的尺寸对应画布的**逻辑**尺寸。

    实测澄清（Windows / 150% 显示缩放）：
      · 画布 `width()/height()` 是**逻辑**像素（338×422），`devicePixelRatioF()` = 1.5；
      · 此 dpr 下 matplotlib 会把 `figure.dpi` 设成 150、figure 为 507×633 **物理**像素；
      · 两者是**同一块区域**：507 / 1.5 = 338 —— 尺寸本来就对，不该干预 dpi。
        （曾怀疑 dpi=150 让画面放大 1.5 倍，实测证明那是我的换算单位搞错，
         不是程序的毛病；强行钉 dpi=100 反而会让高分屏渲染变糊，故不做。）

    所以这里只做一件事：按**逻辑**像素 / 基准 dpi 设定英寸数。
    """
    dpi = 100.0                                      # 与 Figure 构造时的 dpi 一致
    w = max(int(canvas.width()), 1)
    h = max(int(canvas.height()), 1)
    fig.set_size_inches(max(w / dpi, 0.2), max(h / dpi, 0.2), forward=False)


def _apply_margins(fig) -> None:
    """四个边距都用**固定比例**。

    ★ 曾经"按标题块高度反算上边距"来过 —— 不行：那样坐标轴的**比例**会随图高变，
      自检立刻抓到"平移期间坐标轴几何变了"（`interact_e2e` 的那条）。
      所以标题只放一行视图名，按键说明改挂到**下方右侧**（见 `self._hint`）：
      图下方那条边距的高度只跟字号有关，任何图高都放得下，不必动几何。
    """
    fig.subplots_adjust(left=_MARGINS[0], right=_MARGINS[1],
                        bottom=_MARGINS[2], top=_MARGINS[3])


class ObsPlot(QWidget):
    """图形区：四种视图 + 左下角悬停信息 + 点击/框选/缩放/平移。

    交互（与"大软件"一致）：
      · **单击散点** = 只选中（在表格里定位）
      · **Ctrl + 单击** = 该观测取反（剔除 / 取消）
      · **左键拖动** = 平移；**滚轮** = 以光标为中心缩放；**R** = 复位回全览
      · **Shift + 拖动** = 框选；**Ctrl + 拖动** = 框选并整批取反
      · **悬停** = 左下角（图形框内、坐标轴外）显示该观测信息
    """

    #: 框选完成 → 选中的源行号（供表格同步）
    boxSelected = Signal(object)
    #: Ctrl+框选完成 → 这批源行号要**整体取反**（剔除/取消）
    boxToggled = Signal(object)
    #: 点击散点 → 源行号
    pointPicked = Signal(int)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        ensure_cjk_font()
        # ★ **不要用 layout="constrained"**：它会在每次重绘时按刻度文字宽度重新分配边距。
        #   拖动/缩放时坐标轴会被反复拉伸收缩，整个画面肉眼可见地抖动（实测一次拖动里
        #   坐标轴宽度出现 4 个不同取值）。改成固定边距，交互期间几何完全稳定。
        self._fig = Figure(figsize=(6, 4.2), dpi=FIGURE_DPI)
        self._canvas = _Canvas(self._fig, self)
        self._ax = self._fig.add_subplot(111)
        _apply_margins(self._fig)
        self._size_figure_to_canvas()
        # （按键说明已经**画在图上**了，所以不要再挂部件提示 ——
        #   用户要求"去掉鼠标放在符号上的按键提示信息"。）
        self._toolbar = NavigationToolbar2QT(self._canvas, self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self._toolbar)
        lay.addWidget(self._canvas, 1)

        self._f: CG5File | None = None
        self._idx: list[int] = []
        self._local = np.zeros(0, dtype=bool)     # 日期/Survey 圈定的行
        self._keep = np.zeros(0, dtype=bool)      # 条件判定 + 人工干预后保留的行
        self._manual = np.zeros(0, dtype=bool)    # 人工改过（与条件结果不同）的行
        self._manual_kept = np.zeros(0, dtype=bool)   # 其中"人工保留"的那些
        self._kind = "time"
        self._date = ""
        self._lat: float | None = None
        self._lon: float | None = None
        self._pts: dict[int, tuple[float, float, str]] = {}
        self._highlight: set[int] = set()
        #: 与表格的"显示全部数据 / 只看筛选结果"同步：只看筛选结果时，
        #: 图上把被剔除的点也藏掉（连 `_pts` 一起，藏起来的点不参与交互）。
        self._show_all = True
        self._click_cb = None
        # ★ 悬停信息**只**显示在左下角那一块（图形框内、坐标轴外）；
        #   不再额外挂右上角的浮动标签 —— 两处同时显示属于重复。
        #   figure 坐标系 → 不随缩放/平移移动，也不参与坐标轴布局。
        self._info = self._fig.text(
            0.012, 0.005, "", fontsize=INFO_FONT_SIZE, color=COL_DARK,
            ha="left", va="bottom", linespacing=1.3)
        self._info.set_visible(False)
        # ★ 按键说明：图形**下方右侧**（图形内、坐标轴外）。
        #   用户要求"图形里要有 R 键说明"。放下方而不是塞进标题，是因为标题块一变高
        #   就得动上边距，而坐标轴比例必须恒定（否则平移时几何会变 —— 自检抓到过）。
        self._hint = self._fig.text(
            0.988, 0.005, "\n".join(HINT_LINES), fontsize=HINT_FONT_SIZE,
            color=COL_MUTED, ha="right", va="bottom", linespacing=1.3)
        self._box_cb = None
        self._toggle_cb = None
        self._empty_cb = None
        self._box_toggle = False            # 本次框选是否为"取反"模式（Ctrl+拖动）
        self._box_pending = False           # 已按下、准备框选（还没移动够）
        self._box: tuple[float, float, float, float] | None = None   # 框选中的数据范围
        self._rect = None                                            # 橡皮筋
        self._drag_from: tuple[float, float] | None = None
        self._pan_from: tuple[float, float, tuple, tuple] | None = None
        self._zoom_rect = None                                       # 工具条 zoom 模式下的框
        self._home_xlim: tuple[float, float] | None = None   # 全览（「复位」的目标）
        self._home_ylim: tuple[float, float] | None = None
        self._view_xlim: tuple[float, float] | None = None   # 当前视野（重绘时恢复用）
        self._view_ylim: tuple[float, float] | None = None
        #: 当前所画数据的"身份"（文件 + 行集合 + 视图种类）。
        #: 只变勾选/选中时身份不变 → 保留用户的缩放/平移，不重置视野。
        self._data_id: tuple | None = None
        #: 上次应用边距时的坐标轴尺寸（宽, 高）。尺寸没变就不动视野 ——
        #: 否则每次 resize 事件都会把用户的缩放/平移清掉。
        self._ax_px: tuple[int, int] | None = None
        #: 自检钩子：非 None 时用它当修饰键状态（离屏下没有真键盘）
        self._forced_mods: tuple[bool, bool] | None = None

        self._canvas.mpl_connect("motion_notify_event", self._on_move)
        self._canvas.mpl_connect("axes_leave_event", self._on_leave)
        self._canvas.mpl_connect("button_press_event", self._on_press)
        self._canvas.mpl_connect("button_release_event", self._on_release)
        self._canvas.mpl_connect("scroll_event", self._on_scroll)
        self._canvas.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._label_toolbar()
        self._draw_empty()

    # ---------------------------------------------------------------- 外部
    def set_click_callback(self, fn) -> None:
        """点击散点 → 回调**源文件行号**（供表格定位）。"""
        self._click_cb = fn

    def set_empty_click_callback(self, fn) -> None:
        """点击**空白处**（没点到任何散点）→ 回调，用于取消当前选中。"""
        self._empty_cb = fn

    def set_box_callback(self, fn) -> None:
        """框选完成 → 回调**源行号列表**（供表格同步选中）。"""
        self._box_cb = fn

    def set_toggle_box_callback(self, fn) -> None:
        """Ctrl+框选完成 → 回调**源行号列表**（整批取反：剔除/取消）。"""
        self._toggle_cb = fn

    def _label_toolbar(self) -> None:
        """把工具条按钮改成中文名（图标保留）。

        ★ **不再设 tooltip**：按键说明已经画在图上，用户要求"去掉鼠标放在符号上的
        按键提示信息"。注意必须显式设空串 —— `QAction` 的 tooltip 默认就是它的
        text，不设的话悬停会弹出 "复位：回到全览（快捷键 R）" 这类文字。
        """
        cn = {
            "Home": "复位：回到全览（快捷键 R）",
            "Back": "上一个视图",
            "Forward": "下一个视图",
            "Pan": "平移：按住左键拖动",
            "Zoom": "缩放：按住左键框选放大",
            "Subplots": "子图边距",
            "Customize": "自定义",
            "Save": "保存图片",
        }
        for act in self._toolbar.actions():
            t = act.text().replace("&", "").strip()
            if t in cn:
                act.setText(cn[t])
                act.setToolTip("")
                if t == "Home":
                    # ★ 工具条自带的 Home 走 matplotlib 的导航栈：栈空时它先把
                    #   **当前**视野压成 "home" 再跳回去，等于什么都没做；就算跳了，
                    #   它也只改坐标轴范围、不更新我们的 `_view_*`，
                    #   下一次重绘（勾一下复选框就会触发）又会跳回旧视野。
                    #   所以整条改接 `_home_clicked`。
                    try:
                        act.triggered.disconnect()
                    except Exception:                # noqa: BLE001
                        pass
                    act.triggered.connect(self._home_clicked)
        # ★ 空 tooltip 必须设在**按钮**上：`QAction.toolTip()` 在 tooltip 为空时会
        #   回退成 action 的 text（Qt 的既定行为），所以只 setToolTip("") 没用 ——
        #   悬停照样弹出"复位：回到全览（快捷键 R）"。
        for act in self._toolbar.actions():
            w = self._toolbar.widgetForAction(act)
            if w is not None:
                w.setToolTip("")

    def _home_clicked(self) -> None:
        """工具条 ⌂ / 快捷键 R → 回到全览。"""
        try:
            mode = str(getattr(self._toolbar, "mode", "") or "")
            if mode == "zoom":
                self._toolbar.zoom()             # 再点一次 = 退出缩放模式
            elif mode == "pan":
                self._toolbar.pan()
        except Exception:                            # noqa: BLE001
            pass
        self.reset_view()

    def set_show_all(self, show_all: bool) -> None:
        """跟表格的"显示全部数据 / 只看筛选结果"同步。

        只看筛选结果时，图上把被剔除的点**也藏起来**（用户要求：表格那样切，图形跟着切）。
        """
        if bool(show_all) == self._show_all:
            return
        self._show_all = bool(show_all)
        self.redraw()

    def set_data(self, f: CG5File | None, idx: Sequence[int],
                 local: Sequence[bool], keep: Sequence[bool],
                 manual: Sequence[bool], date: str = "",
                 lat: float | None = None, lon: float | None = None,
                 manual_kept: Sequence[bool] | None = None) -> None:
        # ★ 判断"画的还是不是同一批点"：是 → 保留视野（勾选、选中不改缩放）
        new_id = None if f is None else (f.path, tuple(idx), self._kind)
        preserve = (new_id is not None and new_id == self._data_id)
        self._data_id = new_id
        self._keep_view = preserve
        if preserve:
            # 同一批点：记下"当前视野"供重绘恢复。
            # ★ 不能写进 `_home_xlim` —— 那是「复位」的目标，写进去就复位不回去了。
            self._view_xlim = tuple(self._ax.get_xlim())
            self._view_ylim = tuple(self._ax.get_ylim())
        self._f = f
        self._idx = list(idx)
        self._local = np.asarray(local, dtype=bool)
        self._keep = np.asarray(keep, dtype=bool)
        self._manual = np.asarray(manual, dtype=bool)
        self._manual_kept = (np.zeros(len(self._idx), dtype=bool)
                             if manual_kept is None
                             else np.asarray(manual_kept, dtype=bool))
        self._date, self._lat, self._lon = date, lat, lon
        self.redraw()

    def set_kind(self, kind: str) -> None:
        if kind in VIEW_KINDS and kind != self._kind:
            self._kind = kind
            self._home_xlim = self._home_ylim = None      # 换了视图，全览重新算
            self._view_xlim = self._view_ylim = None
            self._data_id = None                          # 强制重新全览
            self._keep_view = False
            self.redraw()

    def set_highlight(self, rows: set[int]) -> None:
        """表格选中行（源文件行号）→ 图上高亮。"""
        if set(rows) == self._highlight:
            return
        self._highlight = set(rows)
        self.redraw()

    # ---------------------------------------------------------------- 绘制
    def redraw(self) -> None:
        self._ax.clear()
        self._pts.clear()
        # `ax.clear()` 已经把橡皮筋从坐标轴上摘掉 → 引用作废，必须置空，
        # 否则下次框选会往一个野对象上 set_bounds（框看不见）。
        self._rect = None
        self._hide_tip()
        if self._f is None or not self._idx:
            self._draw_empty()
            return

        f, idx = self._f, self._idx
        rows = [f.rows[i] for i in idx]
        t = self._time_axis(rows)
        ax = self._ax

        if self._kind == "quality":
            self._plot_quality(ax, rows, t, idx)
        elif self._kind == "tide":
            self._plot_tide(ax, rows, t, idx)
        else:
            self._plot_series(ax, rows, t, idx)

        # ★ 高亮必须在 **_pts 填好之后**画 —— 它按源行号取点位，
        #   放在 fill 之前会一个点都取不到（这就是"选中没效果"的根因）。
        self._highlight_points(ax)
        self._legend_top_left()          # 图例统一画到图形左上角（坐标轴之外）

        # 标题只放视图名（按键说明在图形右下角，见 `self._hint`）
        ax.set_title(VIEW_KINDS[self._kind], fontsize=TITLE_FONT_SIZE,
                     color=COL_DARK)
        # ★ 四条框线都显示（用户要求"坐标轴框线要有"）；只把颜色调浅一点
        for name, spine in ax.spines.items():
            spine.set_visible(True)
            spine.set_color(COL_FRAME)
            spine.set_linewidth(0.8)
        ax.grid(True, ls=":", lw=0.5, alpha=0.5)
        self._canvas.draw_idle()
        # 同一批点、只是勾选/选中变了 → 恢复**当前视野**（缩放/平移结果保留）；
        # `_home_xlim`（全览）保持不动，这样「复位」仍回得到真正的全览。
        if (getattr(self, "_keep_view", False) and self._view_xlim is not None
                and self._view_ylim is not None):
            ax.set_xlim(*self._view_xlim)
            ax.set_ylim(*self._view_ylim)
            self._canvas.draw_idle()
            return
        # 新数据 / 新视图 → 重新全览，并把"全览"与"当前视野"都记下来
        self._canvas.draw()                           # 让 autoscale 定稿
        self._home_xlim = tuple(ax.get_xlim())
        self._home_ylim = tuple(ax.get_ylim())
        self._view_xlim = self._home_xlim
        self._view_ylim = self._home_ylim

    def _legend_top_left(self) -> None:
        """把当前坐标轴的图例画到**图形左上角、坐标轴之外**。

        用 figure 级图例：`ax.legend` 只会画在坐标轴内部。

        ★ 实测坑：`fig.legends` 是一个**普通 list**（存在 `fig.__dict__` 里），
        `Legend.remove()` **不会**把它从该列表里摘掉。只调 `remove()` 会一路累积
        （实测 3 → 4 → … → 26），而 `fig.legends[0]` 拿到的还是**最早那个陈旧图例**，
        于是量出来的位置是错的。必须手动清这个列表。
        """
        fig, ax = self._fig, self._ax

        # 1) 彻底清掉上一版图例（对象、fig.artists、以及那个普通的 fig.legends 列表）
        for leg in list(getattr(self, "_legends", [])):
            try:
                leg.remove()
            except Exception:                        # noqa: BLE001
                pass
            try:
                if leg in fig.artists:
                    fig.artists.remove(leg)
            except Exception:                        # noqa: BLE001
                pass
        self._legends = []
        try:
            fig.legends.clear()                      # ← 关键：它不是只读属性
        except Exception:                            # noqa: BLE001
            pass

        # 2) 收集当前轴上的图例条目（去重、跳过以下划线开头的内部标签）
        handles, labels, seen = [], [], set()
        for art in (list(ax.patches) + list(ax.lines) + list(ax.collections)):
            lab = art.get_label()
            if not lab or lab.startswith("_") or lab in seen:
                continue
            seen.add(lab)
            handles.append(art)
            labels.append(lab)
        if not handles:
            return

        # 3) 画到左上角（figure 坐标：坐标轴之外、图形之内）
        leg = fig.legend(handles, labels, loc="upper left",
                         bbox_to_anchor=(0.006, 0.972),
                         fontsize=LEGEND_FONT_SIZE, framealpha=0.85,
                         borderaxespad=0.0)
        leg.get_frame().set_linewidth(0.6)
        fig.add_artist(leg)
        self._legends = [leg]
        # y 轴标签上移并往外让一点：字放大后别和刻度数字/图例挤在一起
        try:
            ax.yaxis.set_label_coords(-0.125, 0.72)
        except Exception:                            # noqa: BLE001
            pass

    def _plot_series(self, ax, rows, t, idx) -> None:
        """读数 vs 时间 / 互差带 —— 保留·条件剔除·人工剔除三态着色。"""
        f = self._f
        y = np.asarray(numeric(rows, f.columns, C_RAW), dtype=float)
        if self._kind == "band":
            y = y * 1000.0
            st = np.asarray([_cell(r, f.columns, C_STATION) for r in rows], dtype=object)
            y = y - _group_median(y, st)
            for lim, color, label in BANDS:
                ax.axhspan(-lim, lim, color=color, alpha=0.06)
                for s in (lim, -lim):
                    ax.axhline(s, color=color, ls="--", lw=0.8, alpha=0.6)
                ax.plot([], [], color=color, ls="--", lw=0.8, label=label)
            ax.set_ylabel("相对测点中位数 (μGal)")
        else:
            ax.set_ylabel("读数 (mGal)")
        ax.set_xlabel("时间")

        local, keep, man = self._local, self._keep, self._manual
        kept_hand = self._manual_kept
        outside = ~local
        kept_auto = local & keep & (~kept_hand)
        kept_manual = local & keep & kept_hand
        auto = local & (~keep) & (~man)
        manual = local & (~keep) & man
        if not self._show_all:
            # ★ 表格切到"只看筛选结果" → 图上把剔除的点也藏掉（用户要求）。
            #   连 `_pts` 一起藏：看不见的点不该还能悬停/点中/框选。
            outside = np.zeros_like(outside)
            auto = np.zeros_like(auto)
            manual = np.zeros_like(manual)

        if outside.any():
            ax.scatter(t[outside], y[outside], s=18, c=COL_MUTED, alpha=0.3,
                       edgecolors="none", label="范围外", zorder=2)
        # ★ 保留的点要**显眼、在最上层、符号更大**（用户要求）：
        #   剔除的 × 画在下面（zorder 3），保留画在上面（6/7）且白描边更醒目。
        if auto.any():
            ax.scatter(t[auto], y[auto], s=42, c=COL_MUTED, marker="x",
                       lw=1.5, label="条件剔除", zorder=3)
        if manual.any():
            ax.scatter(t[manual], y[manual], s=48, c=COL_ERROR, marker="x",
                       lw=1.7, label="人工剔除", zorder=3)
        if kept_auto.any():
            ax.scatter(t[kept_auto], y[kept_auto], s=52, c=COL_ACCENT,
                       alpha=0.95, edgecolors="white", lw=0.6,
                       label="保留", zorder=6)          # 短标签：图例在窄带里
        if kept_manual.any():
            ax.scatter(t[kept_manual], y[kept_manual], s=74,
                       c=COL_KEPT_BY_HAND, marker="D", alpha=0.95,
                       edgecolors="white", lw=0.7,
                       label="人工保留", zorder=7)

        # 同点连线：一眼看出组内离散（按测点分组，与筛选口径一致）
        if self._kind == "band":
            for blk in group_by_station(rows, f.columns):
                if len(blk) > 1:
                    o = np.asarray(blk, dtype=int)
                    if not self._show_all:
                        o = o[keep[o]]
                    if len(o) < 2:
                        continue
                    o = o[np.argsort(t[o])]
                    ax.plot(t[o], y[o], "-", color="#c9ced6", lw=0.8, zorder=1)

        for k, i in enumerate(idx):
            if not self._show_all and not keep[k]:
                continue                      # 藏起来的点不参与悬停/点击/框选
            self._pts[int(i)] = (float(t[k]), float(y[k]), _tip(f, f.rows[i]))

    def _plot_quality(self, ax, rows, t, idx) -> None:
        """倾斜 / 温度 vs 时间 —— 三条状态曲线叠在同一时间轴上。"""
        f = self._f
        ax.set_xlabel("时间")
        ax.set_ylabel("倾斜 (arcsec) / 温度 (℃)")
        for col, color, label in ((C_TILTX, "#1a5fb4", "倾斜X"),
                                  (C_TILTY, "#8b5cf6", "倾斜Y"),
                                  (C_TEMP, COL_WARN, "温度")):
            if col not in f.columns:
                continue
            v = np.asarray(numeric(rows, f.columns, col), dtype=float)
            ok = self._local & self._keep & (~self._manual_kept)
            if ok.any():
                ax.scatter(t[ok], v[ok], s=20, c=color, alpha=0.75,
                           edgecolors="none", label=label)
            hand = self._local & self._keep & self._manual_kept
            if hand.any():
                ax.scatter(t[hand], v[hand], s=34, c=color, marker="D",
                           alpha=0.95, edgecolors="white", lw=0.4)
            bad = self._local & (~self._keep)
            if not self._show_all:
                bad = np.zeros_like(bad)          # 只看筛选结果 → 剔除的点也藏掉
            if bad.any():
                ax.scatter(t[bad], v[bad], s=46, c=color, marker="x", alpha=0.9)
        tilt = np.asarray(numeric(rows, f.columns, C_TILTX), dtype=float)
        for k, i in enumerate(idx):
            if not self._show_all and not self._keep[k]:
                continue
            self._pts[int(i)] = (float(t[k]), float(tilt[k]), _tip(f, f.rows[i]))
        # 图例不在这里画 —— 由 redraw 统一画到图形左上角（坐标轴之外）

    def _plot_tide(self, ax, rows, t, idx) -> None:
        """仪器潮汐 vs 理论潮汐（理论值按规范公式现算）。"""
        f = self._f
        ax.set_xlabel("时间")
        ax.set_ylabel("潮汐改正 (μGal)")
        ins = np.asarray(numeric(rows, f.columns, C_TIDE), dtype=float) * 1000.0
        mask = np.ones(len(idx), dtype=bool)
        if not self._show_all:
            mask = self._keep.copy()             # 只看筛选结果 → 剔除的点也藏掉
        ins = np.where(mask, ins, np.nan)
        ax.plot(t, ins, "o-", ms=3, lw=0.9, color=COL_OK, alpha=0.9,
                label="仪器潮汐")

        # 经纬度与日期都按**每一行自己的 Survey / 日期**取（见 theory_tide_uGal）：
        # 一个范围里混着多个 Survey 时也照样算得出来。窗口给的值只作兜底。
        theo = np.asarray(theory_tide_uGal(f, idx, self._date, self._lat, self._lon),
                          dtype=float)
        if np.isfinite(theo).any():
            ax.plot(t, np.where(mask, theo, np.nan), "-", lw=1.5,
                    color=COL_ERROR, alpha=0.9,
                    label="理论潮汐")          # 短标签：图例待在左边距 0.175 的窄带里
        else:
            ax.plot([], [], "-", color=COL_ERROR, label="理论潮汐")
        # 图例不在这里画 —— 由 redraw 统一画到图形左上角（坐标轴之外）
        for k, i in enumerate(idx):
            if not mask[k]:
                continue                      # 藏起来的点不参与悬停/点击/框选
            yv = float(theo[k]) if np.isfinite(theo[k]) else float("nan")
            self._pts[int(i)] = (float(t[k]), yv, _tip(f, f.rows[i]))

    def _highlight_points(self, ax) -> None:
        """把表格选中的观测在图上标出来（实心红点 + 白描边 + 红圈）。

        调用时机必须在 `self._pts` 填好**之后** —— 否则取不到点位。
        """
        if not self._highlight:
            return
        rows = [r for r in self._highlight if r in self._pts]
        if not rows:
            return
        xs = np.array([self._pts[r][0] for r in rows], dtype=float)
        ys = np.array([self._pts[r][1] for r in rows], dtype=float)
        fin = np.isfinite(xs) & np.isfinite(ys)
        if not fin.any():
            return
        xs, ys = xs[fin], ys[fin]
        # 实心红点（白描边先铺底，免得被背景吃掉）
        # zorder 要**高于保留点**（保留已经提到 6/7），否则表格选中会被盖住
        ax.scatter(xs, ys, s=110, c=COL_ERROR, edgecolors="white", lw=1.6,
                   zorder=10, label="选中")           # 短标签：图例待在窄带里
        # 再加一圈空心环，选中的点在密集区也一眼能认出来
        ax.scatter(xs, ys, s=300, facecolors="none", edgecolors=COL_ERROR,
                   lw=1.5, alpha=0.85, zorder=9)

    def _time_axis(self, rows) -> np.ndarray:
        """时间轴（小时）。优先用 `十进制时间`（含日期，跨天不会绕回）。"""
        f = self._f
        if C_DECTIME in f.columns:
            v = np.asarray(numeric(rows, f.columns, C_DECTIME), dtype=float)
            if len(v) and np.isfinite(v).all():
                return (v - np.floor(v[0])) * 24.0
        return np.asarray([_hms_to_hours(_cell(r, f.columns, C_TIME)) for r in rows],
                          dtype=float)

    def _draw_empty(self) -> None:
        ax = self._ax
        ax.clear()
        ax.text(0.5, 0.5, "尚未加载数据", ha="center", va="center",
                color=COL_MUTED, transform=ax.transAxes)
        ax.set_xticks([])
        ax.set_yticks([])
        for s in ax.spines.values():
            s.set_visible(False)
        self._canvas.draw_idle()

    # ---------------------------------------------------------------- 交互
    def reset_view(self) -> None:
        """恢复全览（撤销缩放/平移/聚焦）。"""
        if self._home_xlim and self._home_ylim:
            self._ax.set_xlim(*self._home_xlim)
            self._ax.set_ylim(*self._home_ylim)
        else:
            self._ax.relim()
            self._ax.autoscale_view()
            self._home_xlim = tuple(self._ax.get_xlim())
            self._home_ylim = tuple(self._ax.get_ylim())
        self._remember_view()
        self._canvas.draw_idle()

    def _remember_view(self) -> None:
        """把当前坐标轴范围记为"当前视野"（重绘时恢复用）。"""
        self._view_xlim = tuple(self._ax.get_xlim())
        self._view_ylim = tuple(self._ax.get_ylim())

    def focus_rows(self, sources: Sequence[int], *, pad: float = 0.08) -> None:
        """把坐标轴缩放到这些源行号对应的点（表格选中 → 图上聚焦）。

        只动 x 轴范围（时间），y 轴留给 matplotlib 自适应；若选中的点凑不出
        有效范围（只有一个点 / 全是 nan），就退化为在该点附近开个小窗。
        """
        xs = [self._pts[s][0] for s in sources
              if s in self._pts and self._pts[s][0] == self._pts[s][0]]
        if not xs:
            return
        lo, hi = min(xs), max(xs)
        if hi - lo < 1e-6:
            lo, hi = lo - 0.25, hi + 0.25          # 单点：±15 min
        else:
            m = (hi - lo) * pad
            lo, hi = lo - m, hi + m
        self._ax.set_xlim(lo, hi)
        self._remember_view()
        self._canvas.draw_idle()

    def _nearest(self, event) -> int:
        if event.inaxes is not self._ax or not self._pts:
            return -1
        x0, y0 = event.xdata, event.ydata
        if x0 is None or y0 is None:
            return -1
        xl, yl = self._ax.get_xlim(), self._ax.get_ylim()
        sx, sy = max(xl[1] - xl[0], 1e-9), max(yl[1] - yl[0], 1e-9)
        best, best_d = -1, float("inf")
        for row, (px, py, _txt) in self._pts.items():
            if py != py:                      # nan
                continue
            d = ((px - x0) / sx) ** 2 + ((py - y0) / sy) ** 2
            if d < best_d:
                best, best_d = row, d
        return best if best_d < 0.0025 else -1

    def _on_move(self, event) -> None:
        if self._box is not None or self._box_pending:
            self._update_box(event)
            return
        if self._pan_from is not None:
            self._apply_pan(event)
            return
        row = self._nearest(event)
        if row < 0:
            self._hide_tip()
            return
        _px, _py, txt = self._pts[row]
        self._show_tip(txt)

    def _on_leave(self, _event) -> None:
        self._hide_tip()

    # ---- 悬停信息：只有左下角这一块（图形框内、坐标轴外） ----
    def _show_tip(self, text: str) -> None:
        if self._info.get_text() == text and self._info.get_visible():
            return
        self._info.set_text(text)
        self._info.set_visible(bool(text))
        self._canvas.draw_idle()

    def _hide_tip(self) -> None:
        if self._info.get_visible():
            self._info.set_text("")
            self._info.set_visible(False)
            self._canvas.draw_idle()

    # ---- 滚轮缩放（以光标为中心） ----
    def zoom_at(self, qevent) -> bool:
        """按 Qt 滚轮事件缩放；返回是否已处理。"""
        dy = 0
        try:
            dy = qevent.angleDelta().y() or qevent.pixelDelta().y()
        except AttributeError:
            dy = 0
        if not dy:
            return False
        factor = 0.8 if dy > 0 else 1.25            # 上滚放大
        cx, cy = self._data_xy(qevent.position())
        if cx is None:
            return False
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        self._ax.set_xlim(cx + (x0 - cx) * factor, cx + (x1 - cx) * factor)
        self._ax.set_ylim(cy + (y0 - cy) * factor, cy + (y1 - cy) * factor)
        self._remember_view()
        self._canvas.draw_idle()
        return True

    def _size_figure_to_canvas(self) -> None:
        """把 figure 英寸尺寸同步为画布像素尺寸（dpi 不变）。"""
        try:
            _fit_figure(self._canvas, self._fig)
            _apply_margins(self._fig)
            self._ax_px = (max(self._canvas.width(), 1),
                           max(self._canvas.height(), 1))
        except Exception:                            # noqa: BLE001
            pass

    def _mods(self) -> tuple[bool, bool]:
        """当前修饰键 `(shift, ctrl)`。

        优先用测试钩子（自检注入），否则读 Qt 实时状态 —— 比依赖 matplotlib 的
        `event.key` 可靠（后者来自键盘事件，鼠标事件里的 modifier 位传不进去）。
        """
        forced = self._forced_mods
        if forced is not None:
            return forced
        try:
            from PySide6.QtWidgets import QApplication

            m = QApplication.keyboardModifiers()
            return (bool(m & Qt.KeyboardModifier.ShiftModifier),
                    bool(m & Qt.KeyboardModifier.ControlModifier))
        except Exception:                            # noqa: BLE001
            return False, False

    def _data_xy(self, pos):
        """Qt 部件坐标 → 数据坐标（拿不到就返回 (None, None)）。

        入参可以是 `QPointF`，也可以是 Qt 事件（滚轮事件）本身。

        ★ 必须借 matplotlib 自己的 `FigureCanvasQT.mouseEventCoords` 换算，
          不能拿 Qt 坐标直接喂 `transData`：
            · Qt 的 `event.position()` 是**逻辑**像素（本机 150% 缩放），
              而 `transData` 要的是**物理**像素（× `devicePixelRatioF()`）；
            · 而且 Qt 的 y 轴**向下**，`transData` 的 y 轴**向上**，要翻转。
          旧实现两样都没做 —— 于是"以光标为中心缩放"的锚点两轴都是错的，
          表现就是用户说的"滚轮放大不是以鼠标为中心的，很奇怪"。
        """
        try:
            px, py = self._canvas.mouseEventCoords(pos)   # 物理像素, y 向上
            x, y = self._ax.transData.inverted().transform((px, py))
            return float(x), float(y)
        except Exception:                            # noqa: BLE001
            return None, None

    def _on_scroll(self, event) -> None:
        """matplotlib 事件路径（部分后端会走到这里，与 zoom_at 等效）。"""
        if event.inaxes is not self._ax or event.xdata is None or event.ydata is None:
            return
        step = getattr(event, "step", 0) or (1 if event.button == "up" else -1)
        factor = 0.8 ** step
        x0, x1 = self._ax.get_xlim()
        y0, y1 = self._ax.get_ylim()
        cx, cy = float(event.xdata), float(event.ydata)
        self._ax.set_xlim(cx + (x0 - cx) * factor, cx + (x1 - cx) * factor)
        self._ax.set_ylim(cy + (y0 - cy) * factor, cy + (y1 - cy) * factor)
        self._canvas.draw_idle()

    # ---- 拖动平移 / 框选 / 点击 ----
    def _on_press(self, event) -> None:
        if event.inaxes is not self._ax or event.xdata is None:
            return
        self._hide_tip()                              # 开始拖动/框选就先收起标签
        toolbar_mode = str(getattr(self._toolbar, "mode", "") or "")
        # 工具条处于缩放模式：交给 matplotlib 自己拉橡皮筋，我们只记起点
        if toolbar_mode:
            return
        if event.button != 1:
            return
        shift, ctrl = self._mods()
        self._drag_from = (float(event.xdata), float(event.ydata))
        self._box = None
        self._box_toggle = False
        self._pan_from = None
        if shift or ctrl:
            # Shift/Ctrl + 左键 → 准备框选，但**先别画橡皮筋**：
            # 用户可能只是"Ctrl+单击"（取反），那不该被当成框选。
            # 真正的框选在 `_on_move` 里、确认移动了才开始。
            self._box_toggle = ctrl
            self._box_pending = True
            try:
                self._canvas.setCursor(Qt.CursorShape.CrossCursor)
            except Exception:                        # noqa: BLE001
                pass
        else:
            # 无 Shift / Ctrl 的左键拖动 = **平移**（不用先点工具条）
            # ★ 记的是**像素**起点：拖动中途鼠标移出坐标轴时 xdata 会变 None，
            #   用像素才连续（实测拖动"拖着拖着不动了"就是这个原因）
            _ex = getattr(event, "x", None)
            _ey = getattr(event, "y", None)
            self._pan_from = (float(_ex) if _ex is not None else 0.0,
                              float(_ey) if _ey is not None else 0.0,
                              tuple(self._ax.get_xlim()), tuple(self._ax.get_ylim()))
            try:
                self._canvas.setCursor(Qt.CursorShape.ClosedHandCursor)
            except Exception:                        # noqa: BLE001
                pass

    def _on_release(self, event) -> None:
        if self._drag_from is None:
            return
        x0, y0 = self._drag_from
        self._drag_from = None
        if self._pan_from is not None:
            self._pan_from = None
            self._canvas.draw_idle()                  # 收尾完整重画一次
            try:
                self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
            except Exception:                        # noqa: BLE001
                pass
        if event.xdata is None or event.ydata is None:
            self._box = None
            self._hide_rect()
            return
        x1, y1 = float(event.xdata), float(event.ydata)
        # 判定"是否真的拖动"：阈值取两个数据轴范围的万分之一，避免抖动误判
        xs = max(self._ax.get_xlim()[1] - self._ax.get_xlim()[0], 1e-12)
        ys = max(self._ax.get_ylim()[1] - self._ax.get_ylim()[0], 1e-12)
        dragged = (abs(x1 - x0) > xs * 1e-4) or (abs(y1 - y0) > ys * 1e-4)

        if dragged and (self._box is not None or self._box_pending):
            # 框选完成（Shift=选中，Ctrl=整批取反）
            box = (min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))
            # ★ 边界要**含容差**：矩形角点是由鼠标事件的数据坐标反算的，
            #   与点自身的坐标常差最后几位浮点，严格 `<=` 会把正好落在边上的点漏掉
            #   （实测：手算 88 个、实际只框到 87，就差那一条）。
            tolx = (box[2] - box[0]) * 1e-9 + 1e-12
            toly = (box[3] - box[1]) * 1e-9 + 1e-12
            picked = [r for r, (px, py, _t) in self._pts.items()
                      if px == px and py == py
                      and box[0] - tolx <= px <= box[2] + tolx
                      and box[1] - toly <= py <= box[3] + toly]
            # ★ 必须清掉 _box：它同时是"正在框选"的标记。
            #   留着它会让 _on_move 永远走框选分支 —— 悬停信息此后再也不出现
            #   （实测 bug：框选一次之后，鼠标移上去什么都不弹）。
            toggle = self._box_toggle
            self._box = None
            self._box_toggle = False
            self._box_pending = False
            self._hide_rect()
            self._restore_cursor()
            if toggle:
                if self._toggle_cb is not None:
                    self._toggle_cb(picked)
            elif self._box_cb is not None:
                self._box_cb(picked)
            return

        # 没拖动（或只是按了一下）→ 清掉待框选状态
        self._box = None
        self._box_toggle = False
        self._box_pending = False
        self._hide_rect()
        self._restore_cursor()

        if not dragged:
            row = self._nearest(event)
            if row < 0:
                # 点在空白处 → 取消当前选中
                if self._empty_cb is not None:
                    self._empty_cb()
                return
            if row >= 0:
                _shift, toggle = self._mods()
                # 信号只说明"点了哪一行"（单参数，别破坏 Signal(int) 的声明）
                self.pointPicked.emit(row)
                if self._click_cb is not None:
                    # 直接回调多带一个"是否取反"：Ctrl+单击 = 剔除/取消
                    self._click_cb(row, toggle)

    def _ensure_rect(self) -> None:
        """确保橡皮筋存在、且挂在**当前**坐标轴上。

        ★ 关键：`redraw()` 里 `ax.clear()` 会把所有 patch 摘掉，但**不会**把
        `self._rect` 置空 —— 旧对象变成"不属于任何坐标轴"的野引用。
        只看 `is None` 就会一直用那个野对象，`set_bounds()` 也没人画，
        表现就是"框用几次就看不见了"（实测）。
        所以要连 `rect.axes is self._ax` 一起判。
        """
        from matplotlib.patches import Rectangle

        if self._rect is None or getattr(self._rect, "axes", None) is not self._ax:
            self._rect = Rectangle((0, 0), 0, 0, fill=True, facecolor=COL_ACCENT,
                                   alpha=0.15, edgecolor=COL_ACCENT, lw=1.0,
                                   zorder=20)
            try:
                self._ax.add_patch(self._rect)        # add_patch 自带 remove，不会重复
            except Exception:                        # noqa: BLE001
                pass
        color = COL_ERROR if self._box_toggle else COL_ACCENT
        self._rect.set_facecolor(color)
        self._rect.set_edgecolor(color)
        self._rect.set_visible(True)

    def _hide_rect(self) -> None:
        if self._rect is not None:
            self._rect.set_visible(False)
            self._canvas.draw_idle()

    def _restore_cursor(self) -> None:
        try:
            self._canvas.setCursor(Qt.CursorShape.ArrowCursor)
        except Exception:                            # noqa: BLE001
            pass

    def _apply_pan(self, event) -> None:
        """按住左键拖动 → 平移视图（保持拖动点跟着手走）。

        ★ 用**像素**位移驱动，不用 `event.xdata/ydata`。
          实测：鼠标一拖出坐标轴范围，matplotlib 就把 `xdata/ydata` 置为 None，
          原来的实现直接 return —— 表现是"拖着拖着就不动了、抖动"。
          像素位移在不在坐标轴内都有值，拖动因此连续。
        """
        if self._pan_from is None:
            return
        dx_px, dy_px, xlim, ylim = self._pan_from
        ex, ey = getattr(event, "x", None), getattr(event, "y", None)
        if ex is None or ey is None:
            return
        # matplotlib 像素 = Qt 逻辑像素 × dpr，这里统一到"图形像素"再换算数据位移
        bbox = self._ax.bbox
        spanx = bbox.width if bbox.width else 1.0
        spany = bbox.height if bbox.height else 1.0
        sx = (xlim[1] - xlim[0]) / spanx               # 数据单位 / 图形像素
        sy = (ylim[1] - ylim[0]) / spany
        ddx = (ex - dx_px) * sx
        ddy = (ey - dy_px) * sy
        # 鼠标往右拖 → 视图左移（数据增大方向）
        self._ax.set_xlim(xlim[0] - ddx, xlim[1] - ddx)
        self._ax.set_ylim(ylim[0] - ddy, ylim[1] - ddy)
        self._remember_view()
        # ★ 不用 blit。`set_xlim()` 会把 figure 标成 stale，`canvas.blit()` 内部
        #   照样整图重绘；再叠加我先画的 restore_region + draw_artist，
        #   同一帧坐标轴被画两次且内容不一致 —— 边距里的旧刻度标签就成了
        #   用户看到的"一套不动的幽灵标签"。既然 blit 省不了时间，就别用它。
        self._canvas.draw_idle()

    def _update_box(self, event) -> None:
        """拖动过程中实时画橡皮筋。

        首次移动才真正开始框选（按下时只记了待框选状态）——
        这样"Ctrl+单击"才不会被误当成框选。
        """
        if self._drag_from is None:
            return
        if event.xdata is None or event.ydata is None:
            return
        x0, y0 = self._drag_from
        x1, y1 = float(event.xdata), float(event.ydata)
        if self._box is None:
            if not self._box_pending:
                return
            # 还没开始画：确认真的移动了才开始（阈值 = 轴范围的万分之一）
            xs = max(self._ax.get_xlim()[1] - self._ax.get_xlim()[0], 1e-12)
            ys = max(self._ax.get_ylim()[1] - self._ax.get_ylim()[0], 1e-12)
            if abs(x1 - x0) <= xs * 1e-4 and abs(y1 - y0) <= ys * 1e-4:
                return
            self._box = (x0, y0, x1, y1)
            self._ensure_rect()
        self._rect.set_bounds(min(x0, x1), min(y0, y1), abs(x1 - x0), abs(y1 - y0))
        self._canvas.draw_idle()


# ==========================================================================
# 小工具
# ==========================================================================
def _group_median(values: np.ndarray, keys: np.ndarray) -> np.ndarray:
    out = np.full(len(values), np.nan)
    for k in np.unique(keys):
        m = keys == k
        v = values[m]
        v = v[np.isfinite(v)]
        if v.size:
            out[m] = float(np.median(v))
    return out


def _tip(f: CG5File, r) -> str:
    """悬停信息文本（显示在图形框内左下角、坐标轴之外）。

    · 线号 / 点号走 `display.format_id_cell` —— 与**表格里显示的规范一致**；
    · 不含温度、不含源行号（用户明确不需要）。
    """
    def g(col):
        return _cell(r, f.columns, col) or "—"

    def gid(col):
        return format_id_cell(_cell(r, f.columns, col)) or "—"

    return (f"点号 {gid(C_STATION)}　线号 {gid(C_LINE)}\n"
            f"读数 {g(C_RAW)} mGal　标准差 {g(C_SD)}\n"
            f"观测时长 {g(C_DUR)} s　时刻 {g(C_TIME)}\n"
            f"倾斜X {g(C_TILTX)}″　倾斜Y {g(C_TILTY)}″\n"
            f"Survey {r.survey}")
