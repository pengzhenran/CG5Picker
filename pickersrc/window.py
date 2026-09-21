"""CG5Picker 主窗口。

界面分区（自上而下）：
  ① 文件条 —— 打开 CG-5 手簿 / 重新载入
  ② 范围   —— **两条平行的筛选线：日期 / Survey**，都可多选，各自带全选/清空，
              组间可"带入"；组内并集、两组交集（见 `cg5.filter_scope`）
  ③/④/⑤   —— 左：条件栈（含"筛选条件"参数组合的存储与切换）；中：结果表；
              右：图形
  ⑥ 结果条 —— 保留/剔除统计、导出 xlsx、复制到剪贴板、列设置

条件栈自带"添加条件 / 改参数 / 删除"，不再另设按钮条。
"筛选条件"下拉是**存储的参数组合**：切换后整条栈被替换并**全部勾选**，立即生效。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PySide6.QtCore import QEvent, QSortFilterProxyModel, Qt
from PySide6.QtGui import QBrush, QGuiApplication, QIcon, QPalette
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QCheckBox, QComboBox, QDialog,
    QDialogButtonBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QSplitter, QSizePolicy, QStyle, QStyledItemDelegate, QStyleOptionViewItem,
    QTableView, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout,
    QWidget,
)

from . import appinfo, cg5, exporter
from .about_dialog import AboutDialog
from .cg5 import CG5File
from .colorder import REASON_COL, ColOrder, default_visible
from .colorder_dialog import ColumnDialog
from .cond_dialog import CondDialog
from .docs_window import GuideDialog
from .plots import VIEW_KINDS, ObsPlot
from .presets import PresetStore
from .rules import (COND_KINDS, C_STATION, LINKS, LINK_CN, Cond,
                    apply_conditions, default_conditions, logic_text,
                    migrate_conds)
from .scope_widget import ScopeWidget
from .settings import Settings
from .source_view import SourceViewDialog
from .table_model import CHK_COL, C_SEL_BG, C_SEL_TEXT, ObsTableModel
from .table_proxy import ObsSortProxy

APP_TITLE = "CG5 数据挑选 — 独立小工具"
COND_COLS = ("勾选", "连接", "条件", "参数", "命中")


class ExportDialog(QDialog):
    """导出选项：原始格式 / 自定义列序 + 是否附理由列 + 是否附 Survey 文件头。

    ★ 选项**有记忆**（存在本地 `settings.json`）：下次打开就是上次的选择；
      其中「附 Survey 文件头」**出厂默认就勾上**（用户口径：
      "导出时默认勾选包含 survey"）。
    """

    def __init__(self, n_scope: int, n_keep: int, parent=None,
                 options: dict | None = None) -> None:
        super().__init__(parent)
        opts = dict(options or {})
        self.setWindowTitle("导出 xlsx")
        lay = QVBoxLayout(self)

        info = QLabel(f"当前范围共 <b>{n_scope}</b> 条观测，其中保留 <b>{n_keep}</b> 条。")
        lay.addWidget(info)

        form = QFormLayout()
        self.cmb_fmt = QComboBox()
        self.cmb_fmt.addItem("原始数据格式（原列序、原文内容，推荐）", "verbatim")
        self.cmb_fmt.addItem("自定义列序（按当前列设置）", "parsed")
        _mode = str(opts.get("mode", "verbatim"))
        self.cmb_fmt.setCurrentIndex(1 if _mode == "parsed" else 0)
        form.addRow("导出格式", self.cmb_fmt)

        self.cmb_which = QComboBox()
        self.cmb_which.addItem("仅保留的观测（默认）", "keep")
        self.cmb_which.addItem("范围内的全部观测（含被剔除的）", "scope")
        self.cmb_which.setCurrentIndex(1 if str(opts.get("which", "keep")) == "scope"
                                       else 0)
        form.addRow("导出内容", self.cmb_which)

        self.chk_reason = QCheckBox("附「处理理由」列")
        self.chk_reason.setChecked(bool(opts.get("reason", False)))
        form.addRow("", self.chk_reason)
        self.chk_survey = QCheckBox("附 Survey 文件头（写在表格最上面）")
        # ★ 默认**勾上**（用户口径）；之后跟着记忆走
        self.chk_survey.setChecked(bool(opts.get("survey_header", True)))
        self.chk_survey.setToolTip(
            "把这些观测所属 Survey 的文件头字段（Survey name / Instrument S/N /\n"
            "Client / Operator / Date / Time / LONG / LAT / ZONE / GMT DIFF.）\n"
            "按原文写在数据表头**上面**，空一行再接数据\n（默认勾选，选择会被记住）")
        form.addRow("", self.chk_survey)
        lay.addLayout(form)

        note = QLabel("<span style='color:#6b7280'>两种格式都写「表头 + 数据」，"
                      "去掉每行开头的空格；"
                      "数值列写成数值（Excel 里能直接算），"
                      "线号 / 点号是纯数字时也写数值、并保留原文的小数位数"
                      "（<code>15.0000000</code> → <code>15</code>），"
                      "时刻 / 日期写成<b>真时间 / 真日期</b>"
                      "（显示还是 <code>07:42:01</code> / <code>2025/07/02</code>，"
                      "但 Excel/WPS 认它们，不再提示「未识别为日期」）。</span>")
        note.setWordWrap(True)
        lay.addWidget(note)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText("导出")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def mode(self) -> str:
        return str(self.cmb_fmt.currentData())

    def which(self) -> str:
        return str(self.cmb_which.currentData())

    def with_reason(self) -> bool:
        return self.chk_reason.isChecked()

    def with_survey_header(self) -> bool:
        return self.chk_survey.isChecked()


class FloatPanel(QMainWindow):
    """把 ④ 结果表 + ⑤ 图形**一起**拎到**独立窗口并最大化**（两者绑定）。

    用户口径（两轮）：
      · "再加一个结果表和图形的独立窗口最大化的按钮。加在结果表上。"
      · "是同时最大化，表格和图形，两者绑定。按钮放在只看筛选结果的下面"
        —— 所以是**一个**按钮、**一个**窗口，表格在左、图形在右，中间可拖动。

    ★ 做法是 **reparent 同一批 QGroupBox**，不是复制一份界面：
      表格还是那张表、图形还是那个画布 —— 勾选状态、行选中、图形缩放平移
      全部原样保留（复制一份反而会出现"两边状态不一致"）。
      关掉本窗口（或点「放回主窗口」）= 把两块面板塞回主窗口原来的栏位。
    """

    def __init__(self, title: str, boxes, on_close) -> None:
        super().__init__(boxes[0].window())
        self.setWindowTitle(title)
        self._boxes = list(boxes)
        self._on_close = on_close
        self._closing = False
        body = QWidget()
        lay = QVBoxLayout(body)
        lay.setContentsMargins(2, 2, 2, 2)
        if len(self._boxes) > 1:
            # 表格在左、图形在右；中间的拖动条可以再分配（复核时想给图形多点宽度）
            self.split = QSplitter(Qt.Orientation.Horizontal)
            for b in self._boxes:
                self.split.addWidget(b)
            self.split.setSizes([600, 700])
            self.split.setStretchFactor(0, 1)
            self.split.setStretchFactor(1, 2)
            lay.addWidget(self.split)
        else:
            self.split = None
            lay.addWidget(self._boxes[0])
        self.setCentralWidget(body)
        tb = self.addToolBar("面板")
        tb.setMovable(False)
        act = tb.addAction("⤡ 放回主窗口")
        act.setToolTip("把表格与图形放回主窗口原来的栏位（关掉本窗口也一样）")
        act.triggered.connect(self.close)
        self.resize(1400, 900)

    def closeEvent(self, ev) -> None:                     # noqa: N802（Qt 命名）
        if self._closing:
            super().closeEvent(ev)
            return
        self._closing = True
        try:
            self._on_close()                              # 先放回面板，再关窗口
        finally:
            self._closing = False
        super().closeEvent(ev)


class RowHighlightDelegate(QStyledItemDelegate):
    """把**被选中**的行画成亮黄（默认的蓝底会把深蓝加粗的"打勾"字压得看不清）。

    为什么不写样式表 `QTableView::item:selected{background-color:...}`：
      样式表会让 QStyleSheetStyle 接管整张表的绘制，把模型里按测点分组铺的
      白 / 浅蓝 / 淡黄底纹一起顶掉。
    为什么只设调色板 Highlight 也不够：
      实测本机 Windows 11 样式在窗口**非激活**时，把选中行画成几乎看不出来的
      浅灰（抓像素得 `(245,236,186)`，而调色板里明明是 `#ffc400`）。
      所以干脆自己铺底：激活与否都是同一个亮黄，文字统一压成近黑。
    """

    def paint(self, painter, option, index) -> None:      # noqa: N802 (Qt 命名)
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)      # 含模型的底纹/前景色/勾选指示
        if opt.state & QStyle.StateFlag.State_Selected:
            opt.backgroundBrush = QBrush(C_SEL_BG)              # 自己铺亮黄
            opt.state &= ~QStyle.StateFlag.State_Selected       # 别再叠一层系统高亮
            opt.palette.setColor(QPalette.ColorRole.Text, C_SEL_TEXT)
        style = (opt.widget.style() if opt.widget is not None
                 else QApplication.style())
        painter.save()
        try:
            style.drawControl(QStyle.ControlElement.CE_ItemViewItem,
                              opt, painter, opt.widget)
        finally:
            painter.restore()


class MainWindow(QMainWindow):

    def __init__(self, settings_path=None) -> None:
        super().__init__()
        # ★ 全局字号调大（字体大一号 → 最小窗口相应放宽，免得控件被挤扁）
        _app = QApplication.instance()
        if _app is not None:
            _apply_ui_font(_app)
        self.setWindowTitle(APP_TITLE)
        self.setMinimumSize(1240, 760)
        # 屏幕小于这个尺寸时才用固定初始大小，否则直接铺满（默认全屏启动）
        _scr = QApplication.primaryScreen()
        _avail = _scr.availableGeometry() if _scr is not None else None
        if _avail is not None and (_avail.width() < 1400 or _avail.height() < 900):
            self.resize(min(1400, max(1240, _avail.width() - 40)),
                        min(900, max(760, _avail.height() - 40)))
        else:
            self.resize(1680, 980)
        self._want_maximized = True

        # ---- 状态 ----
        self.f: CG5File | None = None
        self.scope: list[int] = []          # 当前日期/Survey 两条线圈定的源行号
        self.auto_reason: dict[int, str] = {}
        self.cond_hits: dict[str, int] = {}
        self.manual_keep: set[int] = set()
        self.manual_drop: set[int] = set()
        self._keep_rows: list[int] = []     # 供导出/复制使用
        self.colorder = ColOrder(order=[], reason=True)
        self._loading = False
        self.store = PresetStore()          # 筛选条件参数组合（落盘）
        self._current_preset = ""
        self._source_dlg: SourceViewDialog | None = None
        self._float_wins: dict[str, FloatPanel] = {}   # "table" / "plot" 的独立窗口
        self._split_sizes_before_float: list[int] = []
        # ★ 本地配置（参数设置的记忆）：%APPDATA%\CG5Picker\settings.json
        #   （`settings_path` 只是给自检用的 —— 测试里指到临时文件，别污染真配置）
        self.settings = Settings(settings_path)

        self._build_ui()
        self._reload_preset_combo()
        self._set_conditions(default_conditions(), preset_name="")
        self._refresh_scope_labels()
        self._restore_settings()            # 恢复上次的窗口/视图/导出选项等**

    # ================================================================== 本地配置
    def _restore_settings(self) -> None:
        """把上次的界面习惯恢复回来（窗口几何、视图、列序、导出选项…）。"""
        st = self.settings
        geo = st.get("window/geometry") or ""
        state = st.get("window/state") or ""
        if geo:
            try:
                from PySide6.QtCore import QByteArray
                self.restoreGeometry(QByteArray.fromBase64(str(geo).encode()))
                self._want_maximized = bool(st.get("window/maximized", True))
                if state:
                    self.restoreState(QByteArray.fromBase64(str(state).encode()))
                # ★ 卫生检查：旧几何可能来自"很小的那一屏"或另一台显示器 ——
                #   恢复出来比最小尺寸还小就丢掉，回到默认大小（否则控件被挤扁）。
                if (not self.isMaximized()
                        and (self.width() < self.minimumWidth()
                             or self.height() < self.minimumHeight())):
                    self.resize(1680, 980)
            except Exception:                              # noqa: BLE001
                pass
        split = st.get("window/split") or []            # 分栏宽度已在 _build_ui 里用上
        if isinstance(split, list) and len(split) == 3:
            self._split_sizes_saved = list(split)
        kind = str(st.get("plot/kind") or "")
        if kind in VIEW_KINDS:
            i = self.cmb_view.findData(kind)
            if i >= 0:
                self.cmb_view.setCurrentIndex(i)
        order = st.get("columns/order") or []
        if isinstance(order, list) and order and self.f is None:
            self.colorder.order = [str(c) for c in order]
        self.show_all = bool(st.get("view/show_all", True))
        self.chk_only_manual.setChecked(bool(st.get("view/only_manual", False)))
        self._status_view_mode()
        self._apply_icon()
        self._restore_conditions()

    def _restore_conditions(self) -> None:
        """条件栈也记忆：上次改过的那一栈，下次启动原样回来。

        （"这些参数设置都要有记忆功能" —— 条件栈是最要紧的那组参数；
          想回出厂值就在「筛选条件」下拉里选第一个内置组合。）
        """
        saved = self.settings.get("conds/last") or []
        if not isinstance(saved, list) or not saved:
            return
        conds: list[Cond] = []
        for d in saved:
            if not isinstance(d, dict):
                continue
            try:
                conds.append(Cond.from_dict(d))
            except (KeyError, TypeError):
                continue                           # 版本变化导致的未知条件 → 跳过
        conds = migrate_conds(conds)
        if not conds:
            return
        for c in conds:
            c.enabled = bool(getattr(c, "enabled", True))
        self._set_conditions(conds, preset_name=str(self.settings.get("preset/last")
                                                    or ""))

    def _apply_icon(self) -> None:
        """窗口/任务栏图标（图标文件在包外 resources/ 里，找不到就跳过）。"""
        p = appinfo.icon_path()
        if p is None:
            return
        try:
            ic = QIcon(str(p))
            if not ic.isNull():
                self.setWindowIcon(ic)
                app = QApplication.instance()
                if app is not None:
                    app.setWindowIcon(ic)
        except Exception:                                  # noqa: BLE001
            pass

    def _save_settings(self) -> None:
        """关窗口时把界面习惯记下来（窗口几何 + 分栏 + 视图 + 列序）。"""
        st = self.settings
        try:
            st.set("window/geometry",
                   bytes(self.saveGeometry().toBase64()).decode("ascii"))
            st.set("window/state", bytes(self.saveState().toBase64()).decode("ascii"))
            st.set("window/maximized", bool(self.isMaximized()))
            st.set("window/split", [int(x) for x in self.split.sizes()])
            st.set("view/show_all", bool(self.show_all))
            st.set("view/only_manual", bool(self.chk_only_manual.isChecked()))
            st.set("plot/kind", str(self.cmb_view.currentData() or ""))
            st.set("columns/order", list(self.colorder.order))
            st.set("conds/last", [c.to_dict() for c in (self.conds or [])])
            if getattr(self, "_source_dlg", None) is not None:
                st.set("source/follow", bool(self._source_dlg.chk_follow.isChecked()))
            st.set("preset/last", str(self._current_preset or ""))
        except Exception:                                  # noqa: BLE001
            pass
        st.flush()

    def closeEvent(self, ev) -> None:                     # noqa: N802（Qt 命名）
        """关窗口前把参数设置与界面习惯落到本地配置（记忆功能）。"""
        self._save_settings()
        super().closeEvent(ev)

    # ================================================================== 界面
    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        v = QVBoxLayout(root)
        v.setContentsMargins(8, 8, 8, 8)
        v.setSpacing(6)

        v.addLayout(self._build_file_bar())

        self.scope_widget = ScopeWidget()
        self.scope_widget.set_lookup(self._surveys_on, self._dates_of)
        self.scope_widget.changed.connect(self._on_scope_changed)
        v.addWidget(self.scope_widget)

        # ② 条件面板：加了「连接」列之后更挤了 —— 用户要求**再拓宽**，
        #   宽度从 ⑤ 图形那边挪（⑤ 仍是最宽的一栏）。
        #   图形那边被挤掉的绘图宽度，靠 `plots._MARGINS`（左边距收窄、纵轴左移）补回来。
        split = QSplitter(Qt.Orientation.Horizontal)
        split.addWidget(self._build_cond_panel())
        split.addWidget(self._build_table_panel())
        split.addWidget(self._build_plot_panel())
        # 上次的分栏宽度（本地配置里有、而且**看着正常**才用）
        #   ★ 下限保护：换屏幕/换分辨率后旧尺寸可能来自"很小的一屏"，
        #     直接套用会把三栏挤成细条（自检里就踩过 257px 那种）。
        _saved = [int(x) for x in (self.settings.get("window/split") or [])
                  if isinstance(x, (int, float))]
        if not (len(_saved) == 3 and all(x >= 200 for x in _saved)
                and sum(_saved) >= 900):
            _saved = [500, 500, 680]
        split.setSizes(_saved)
        split.setStretchFactor(0, 0)      # ② 条件：不随窗口变大而变宽
        split.setStretchFactor(1, 1)      # ④ 结果表：适度伸缩
        split.setStretchFactor(2, 2)      # ⑤ 图形：优先变宽
        for i, w in ((0, 470), (1, 430), (2, 380)):
            split.widget(i).setMinimumWidth(w)
        self.split = split
        split.splitterMoved.connect(lambda *_a: self._resize_cond_cols())
        v.addWidget(split, 1)
        v.addLayout(self._build_result_bar())

        self._install_shortcuts()
        self.statusBar().showMessage("请先「打开 CG-5 手簿」")

    def resizeEvent(self, ev) -> None:                 # noqa: N802（Qt 命名）
        """窗口尺寸变了就重算条件表的固定列宽 —— 保证**始终铺满、不出横向滚动条**。"""
        super().resizeEvent(ev)
        self._resize_cond_cols()

    def eventFilter(self, obj, ev) -> bool:             # noqa: N802（Qt 命名）
        """条件表**视口**一变宽（拖分隔条 / 布局重排）就重算列宽。

        只挂窗口的 `resizeEvent` 不够：拖分隔条、或布局把表压窄时窗口尺寸没变，
        列宽会停在旧值上，于是又冒出一条横向滚动条（用户报的现象）。
        """
        if (obj is getattr(self, "_cond_viewport", None)
                and ev.type() == QEvent.Type.Resize):
            self._resize_cond_cols()
        return super().eventFilter(obj, ev)

    def _install_shortcuts(self) -> None:
        from PySide6.QtGui import QKeySequence, QShortcut

        QShortcut(QKeySequence.StandardKey.Save, self, self._save_preset)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, self._save_preset)
        QShortcut(QKeySequence("F3"), self, self.show_source_view)
        QShortcut(QKeySequence("F1"), self, self.show_guide)          # 使用说明
        QShortcut(QKeySequence("Shift+F1"), self, self.show_about)    # 关于 / 作者信息
        # ★ Ctrl+C = 复制**整行**（不是只复制点到的那一格）。只挂在表格上：
        #   别处（比如输入框）按 Ctrl+C 仍然是正常的复制文字。
        self._sc_copy = QShortcut(QKeySequence.StandardKey.Copy, self.table)
        self._sc_copy.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self._sc_copy.activated.connect(self.copy_to_clipboard)
        # ★ R = 图形复位。挂在**窗口**上而不是只挂画布：滚轮缩放不会让画布拿到
        #   焦点（焦点还在刚点过的按钮上），只挂画布就会出现"按 R 没反应"。
        #   代价是它会跟文本框抢字母，所以按焦点动态开关（见 `_on_focus_changed`）。
        self._sc_reset = QShortcut(QKeySequence(Qt.Key.Key_R), self)
        self._sc_reset.setContext(Qt.ShortcutContext.WindowShortcut)
        self._sc_reset.activated.connect(self._reset_plot)
        app = QApplication.instance()
        if app is not None:
            app.focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, _old, now) -> None:
        """焦点落进文本输入框时，暂时关掉 R 快捷键（否则在输入框里打不出字母 r）。"""
        from PySide6.QtWidgets import (QAbstractSpinBox, QLineEdit,
                                       QPlainTextEdit, QTextEdit)

        typing = isinstance(now, (QLineEdit, QTextEdit, QPlainTextEdit,
                                  QAbstractSpinBox))
        self._sc_reset.setEnabled(not typing)

    def _reset_plot(self) -> None:
        """R / 工具条 ⌂ → 图形复位回全览。"""
        self.plot.reset_view()
        self.statusBar().showMessage("图形已复位（回到全览）", 3000)

    def _build_file_bar(self):
        bar = QHBoxLayout()
        self.btn_open = QPushButton("打开 CG-5 手簿…")
        self.btn_open.setProperty("accent", True)
        self.btn_open.clicked.connect(self.open_file)
        bar.addWidget(self.btn_open)

        self.btn_reload = QPushButton("重新载入")
        self.btn_reload.clicked.connect(self.reload)
        bar.addWidget(self.btn_reload)

        self.btn_source = QPushButton("查看原数据…")
        self.btn_source.setToolTip("用独立窗口预览原始手簿全文（F3），并跟随表格选中高亮源行")
        self.btn_source.clicked.connect(self.show_source_view)
        bar.addWidget(self.btn_source)

        self.lbl_file = QLabel("尚未载入文件")
        self.lbl_file.setWordWrap(True)
        bar.addWidget(self.lbl_file, 1)

        # 使用说明（F1）+ 关于 / 作者信息（Shift+F1）—— 版式与课题组的 SHKit / SHSynth 一致
        self.btn_guide = QPushButton("📖 使用说明")
        self.btn_guide.setToolTip(
            "打开使用说明（HTML，在窗口里预览、可调字号 / 用浏览器打开）（F1）")
        self.btn_guide.clicked.connect(self.show_guide)
        bar.addWidget(self.btn_guide)

        self.btn_about = QPushButton("ⓘ 关于")
        self.btn_about.setToolTip(
            "关于本工具 / 作者信息 / 公众号二维码 / 快速上手（Shift+F1）\n"
            "里面也写着配置文件（参数设置记忆）放在哪儿")
        self.btn_about.clicked.connect(self.show_about)
        bar.addWidget(self.btn_about)
        return bar

    # ================================================================== 帮助
    def show_guide(self) -> None:
        """打开使用说明（HTML）——窗口内预览（F1）。"""
        dlg = GuideDialog(self)
        if dlg.toc.count() == 0 and appinfo.guide_html_path() is None:
            QMessageBox.information(
                self, "使用说明",
                "没有找到使用说明文件（docs\\使用说明.html）。\n"
                "安装版应随安装包一起装上；请重新安装一次。")
            return
        dlg.exec()

    def show_about(self) -> None:
        """弹出「关于 / 作者信息」对话框（Shift+F1、右上角按钮都走这里）。"""
        dlg = AboutDialog(self, self.settings)
        dlg.exec()

    def _build_cond_panel(self):
        # ★ 标题只留短名：QGroupBox 的 **minimumSizeHint 含标题文字宽度**，
        #   原来那串长括号说明（字体放大后 432px）会把 ② 面板的最小宽度顶死，
        #   "② 尽量窄"就做不到了。说明挪进 tooltip。
        box = QGroupBox("② 筛选条件")
        box.setToolTip("切换「筛选条件」组合 = 整条条件栈被替换并全部勾选、立即生效；\n"
                       "条件可增删改（或用「条件 ▾」菜单 / 右键条件行）")
        v = QVBoxLayout(box)

        # ---- 「筛选条件」= 存储的参数组合：切换 / 存参数 / 重命名 / 删除 ----
        row = QHBoxLayout()
        row.setSpacing(4)
        row.addWidget(QLabel("筛选条件"))
        self.cmb_preset = QComboBox()
        # ★ 组合名很长（"硬件质量：倾斜≤5″ + REJ=0 + 时长≥35"）。
        #   但下拉框本身**不能**把它当最小宽度 —— 那会把整个 ② 面板顶宽
        #   （实测 minSizeHint 被撑到 580，挤压图形区）。
        #   做法：**框**允许压窄到 200，**展开的列表**仍然给足 430 宽，
        #   于是"面板窄 + 名字完整可读"两者兼得。
        self.cmb_preset.setMinimumWidth(180)
        self.cmb_preset.setSizeAdjustPolicy(
            QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.cmb_preset.setMinimumContentsLength(8)
        self.cmb_preset.view().setMinimumWidth(430)     # 下拉列表保持宽，名字看得全
        self.cmb_preset.activated.connect(self._on_preset_activated)
        row.addWidget(self.cmb_preset, 1)
        v.addLayout(row)

        self.lbl_preset_state = QLabel("")
        self.lbl_preset_state.setProperty("hint", True)
        v.addWidget(self.lbl_preset_state)

        self.tbl_cond = QTableWidget(0, len(COND_COLS))
        self.tbl_cond.setHorizontalHeaderLabels(COND_COLS)
        self.tbl_cond.verticalHeader().setVisible(False)
        self.tbl_cond.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tbl_cond.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tbl_cond.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hh = self.tbl_cond.horizontalHeader()
        # ★ 列宽口径（用户本轮要求）：
        #   · 「连接」= **2 个汉字宽**（再留出下拉框的箭头与内边距）；
        #   · 「条件」= **4 个汉字宽**；
        #   · 「参数」= **10 个汉字宽**；
        #   · 剩下的宽度全给「命中」，整条表**正好铺满面板** —— 不再出现左右滑动条
        #     （用户："怎么现在又变成需要左右滑动了，铺满就行，不要左右滑动"）。
        hh.setMinimumSectionSize(24)
        self.tbl_cond.setMinimumWidth(0)
        self.tbl_cond.setTextElideMode(Qt.TextElideMode.ElideRight)
        # 铺满 + 不滑动：横向滚动条直接关掉，宽度全由 `_resize_cond_cols()` 算
        self.tbl_cond.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.tbl_cond.itemChanged.connect(self._on_cond_item_changed)
        self.tbl_cond.doubleClicked.connect(lambda i: self._edit_condition(i.row()))
        hh.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        for _c in (1, 2, 3, 4):
            hh.setSectionResizeMode(_c, QHeaderView.ResizeMode.Interactive)
        # ★ 不用 `Stretch` / `stretchLastSection`：程序化改列宽时那个"拉伸段"不一定
        #   跟着重算，会出现"五列之和 > 视口"、右边被切掉一截（实测差 46px）。
        #   「命中」的宽度由 `_resize_cond_cols()` 按"剩下的全部宽度"自己算。
        hh.setStretchLastSection(False)
        self._resize_cond_cols()
        # 视口自己变宽变窄时也要重算列宽（拖分隔条 / 布局重排 → eventFilter）
        # ★ 存一份引用：PySide 里每次 `viewport()` 可能给出新的 Python 包装对象，
        #   用 `is` 比较会认不出来，事件过滤就白挂了。
        self._cond_viewport = self.tbl_cond.viewport()
        self._cond_viewport.installEventFilter(self)
        # 右键菜单也能改参数 / 删除，操作就在条件栈里，不另设按钮条
        self.tbl_cond.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.tbl_cond.customContextMenuRequested.connect(self._cond_context_menu)
        # ★ 竖向分配（用户本轮口径："上面减小，下面日志部分加大"）：
        #   条件表**最多露 8 行**（再多就滚动），按钮排 + 判定式 + 日志吃掉剩下的高度。
        self.tbl_cond.verticalHeader().setDefaultSectionSize(30)
        self._cap_cond_table_height()
        v.addWidget(self.tbl_cond, 1)

        # 操作按钮排一行。② 面板要压窄，所以用紧凑写法：
        # 增删改收进一个「条件 ▾」菜单，上下移只留箭头符号。
        bar = QHBoxLayout()
        bar.setSpacing(2)
        b_menu = QPushButton("条件 ▾")
        b_menu.setToolTip("添加条件…／改参数…／删除\n（也可以右键条件行、或双击行改参数）")
        b_menu.clicked.connect(self._cond_menu)
        bar.addWidget(b_menu)
        self.btn_cond_menu = b_menu
        b_up = QPushButton("▲")
        b_up.setFixedWidth(26)
        b_up.setToolTip("上移（条件顺序影响「处理理由」记录的是哪一条；判定本身取交集）")
        b_up.clicked.connect(lambda: self._move_condition(-1))
        bar.addWidget(b_up)
        b_dn = QPushButton("▼")
        b_dn.setFixedWidth(26)
        b_dn.setToolTip("下移")
        b_dn.clicked.connect(lambda: self._move_condition(+1))
        bar.addWidget(b_dn)
        # 参数组合的"存 / 改名 / 删除"菜单按钮也挪到这一排 ——
        # 它原来跟下拉框挤同一行，字体放大后会把 ② 面板的最小宽度顶到 400+
        self.btn_preset_menu = QPushButton("参数组合 ▾")
        self.btn_preset_menu.setToolTip(
            "存参数（把当前条件栈存成组合）／重命名／删除")
        self.btn_preset_menu.clicked.connect(self._preset_menu)
        bar.addWidget(self.btn_preset_menu)
        bar.addStretch(1)
        v.addLayout(bar)

        # 判定式：把当前条件栈翻译成一句人话（或/且一眼看清）
        self.lbl_logic = QLabel("")
        self.lbl_logic.setWordWrap(True)
        self.lbl_logic.setProperty("title", True)
        self.lbl_logic.setToolTip(
            "「连接」列决定每条条件的角色：\n"
            "　首要 —— 必须满足（第一块）\n"
            "　或　 —— 这一组里至少一条满足\n"
            "　且　 —— 这一组里每条都要满足\n"
            "判定 = 首要 ∧ (或组) ∧ (且组)")
        v.addWidget(self.lbl_logic)

        # 汇总 / 日志：用户本轮要求"上面（条件）减小、下面（日志）加大"，
        # 所以日志拿 2 份、条件表拿 1 份，且条件表另有**最高 8 行**的上限。
        self.txt_summary = QTextBrowser()
        # ★ 横向 QSizePolicy=Ignored：QTextBrowser 自带的 minimumSizeHint 宽达 432
        #   （字体放大后更明显），会把整个 ② 面板的**最小宽度**顶到 432，
        #   于是"② 尽量窄"直接失效。Ignored 让布局忽略它的大小提示，宽度随面板走。
        _sp = self.txt_summary.sizePolicy()
        _sp.setHorizontalPolicy(QSizePolicy.Policy.Ignored)
        self.txt_summary.setSizePolicy(_sp)
        self.txt_summary.setMinimumHeight(120)       # 再挤也留得下几行日志
        v.addWidget(self.txt_summary, 2)
        return box

    #: 条件表最多露几行（多出来的行滚动）—— 其余高度全给下面的日志
    COND_VISIBLE_ROWS = 8
    #: 条件很少时至少留几行，别把表压成一条
    COND_MIN_ROWS = 3

    def _cap_cond_table_height(self) -> None:
        """条件表高度 = **现有条件占的行数**，上限 8 行（再多就滚动）。

        用户口径："上面减小，下面日志部分加大" —— 条件表只占它需要的行高，
        剩下的高度全给下面的日志。

        · 下限 = `min(8, 条件数)`：≤8 条条件时**一条都不用滚动**（原来在 1680×980
          窗口里 5 条条件只露 4 行，第 5 条要滚）；
        · 上限 = `min(8, max(3, 条件数 + 1))`：留一行空位，其余都给日志。
        """
        if getattr(self, "tbl_cond", None) is None:
            return
        n = len(getattr(self, "conds", None) or [])
        lo = min(self.COND_VISIBLE_ROWS, max(self.COND_MIN_ROWS, n))
        hi = min(self.COND_VISIBLE_ROWS, max(self.COND_MIN_ROWS, n + 1))
        hh = self.tbl_cond.horizontalHeader().height() or 32
        self.tbl_cond.setMinimumHeight(hh + 30 * lo + 6)
        self.tbl_cond.setMaximumHeight(hh + 30 * hi + 6)

    def _build_table_panel(self):
        box = QGroupBox("④ 结果表")
        self.result_box = box                     # 供"独立窗口最大化"用（reparent）
        box.setToolTip("勾选 = 保留、取消 = 剔除；表头可拖动换列序、点击表头排序；\n"
                       "右键可做人工保留/剔除、在图上定位、复制选中的观测")
        v = QVBoxLayout(box)

        # 第 1 排：显示模式
        # （"显示全部数据"原先左边有个复选框，右边又有切换按钮 —— 重复，已去掉复选框，
        #   状态由 `self.show_all` 记、界面由右边的按钮显示）
        # ★ 按钮分成**三排**（用户口径："不要四排就三排，最大化和选中操作在一排，
        #   不冲突"）：每排都 ≤430px，1680 窗口（④ 面板 ≈ 489px）与 ④ 的最小宽
        #   （430px）下都不会把按钮挤出面板。
        bar = QHBoxLayout()
        bar.setSpacing(4)
        self.show_all = True

        self.chk_only_manual = QCheckBox("只看人工改过的")
        self.chk_only_manual.setToolTip("只看你手工勾/取消过的那些观测")
        self.chk_only_manual.toggled.connect(self._on_view_mode_changed)
        bar.addWidget(self.chk_only_manual)

        bar.addStretch(1)
        self.btn_only_filtered = QPushButton("👉 只看筛选结果")
        self.btn_only_filtered.setToolTip(
            "在「显示全部数据」与「只显示筛选结果」之间切换")
        self.btn_only_filtered.clicked.connect(self._toggle_view_mode)
        bar.addWidget(self.btn_only_filtered)
        v.addLayout(bar)

        # 第 2 排：**选中/勾选操作 + 最大化**同一排（用户：这两件事不冲突）
        #   · 选中与勾选：**勾选**（保留/剔除）和**选中**（表格里选中的行）是两回事 ——
        #     用户口径："取消选中的意思是取消表格行的选中，不是取消勾选，
        #     勾选和选中是两回事，再加一个取消勾选，把 反选选中取消掉。"
        #   · 最大化：表格 + 图形**一起**拎进一个独立窗口并最大化（两者绑定），
        #     用户口径："是同时最大化，表格和图形，两者绑定。按钮放在只看筛选结果的下面。"
        bar3 = QHBoxLayout()
        bar3.setSpacing(4)
        self.btn_deselect = QPushButton("取消选中")
        self.btn_deselect.setToolTip(
            "**只取消表格里的行选中**（高亮那一批放开），勾选状态一个都不动\n"
            "对应：图形里点空白处；选中是选中，勾选是勾选，两回事")
        self.btn_deselect.clicked.connect(self._clear_table_selection)
        bar3.addWidget(self.btn_deselect)
        self.btn_check = QPushButton("勾选选中")
        self.btn_check.setToolTip("把表格里选中的行**勾上**（= 人工保留）")
        self.btn_check.clicked.connect(lambda: self._manual_bulk(True))
        bar3.addWidget(self.btn_check)
        self.btn_uncheck = QPushButton("取消勾选")
        self.btn_uncheck.setToolTip("把表格里选中的行**取消勾选**（= 人工剔除）")
        self.btn_uncheck.clicked.connect(lambda: self._manual_bulk(False))
        bar3.addWidget(self.btn_uncheck)

        bar3.addStretch(1)
        self.btn_float_both = QPushButton("⛶ 表格+图形 最大化")
        self.btn_float_both.setToolTip(
            "把**结果表和图形一起**放进一个独立窗口并最大化（左表右图，中间可拖动）\n"
            "表格还是这张表、图形还是这个画布：勾选、行选中、缩放平移都不丢\n"
            "关掉那个窗口（或点里面的「放回主窗口」）= 两块都放回原来的栏位")
        self.btn_float_both.clicked.connect(self._float_both)
        bar3.addWidget(self.btn_float_both)
        v.addLayout(bar3)

        # 第 3 排：撤销 + 结果动作（导出 / 复制 / 列设置）
        bar2 = QHBoxLayout()
        bar2.setSpacing(4)
        b_reset = QPushButton("恢复条件结果")
        b_reset.setToolTip("清空全部人工干预，回到条件筛选的结果（撤销批量取舍）")
        b_reset.clicked.connect(self._reset_manual)
        bar2.addWidget(b_reset)

        self.btn_export = QPushButton("导出 xlsx…")
        self.btn_export.setToolTip("把保留的观测按原始数据格式导出成 xlsx")
        self.btn_export.clicked.connect(self.export_xlsx)
        bar2.addWidget(self.btn_export)

        self.btn_copy = QPushButton("复制到剪贴板")
        self.btn_copy.setToolTip("把当前结果按制表符分隔复制，可直接粘进 Excel")
        self.btn_copy.clicked.connect(self.copy_to_clipboard)
        bar2.addWidget(self.btn_copy)

        self.btn_cols = QPushButton("列设置…")
        self.btn_cols.setToolTip("选择显示/导出的列与顺序")
        self.btn_cols.clicked.connect(self.open_column_dialog)
        bar2.addWidget(self.btn_cols)
        bar2.addStretch(1)
        v.addLayout(bar2)

        self.model = ObsTableModel(self)
        self.model.checkToggled.connect(self._on_check_toggled)
        # ★ 自己实现的排序代理：勾选框列与理由列**不参与排序**，其余列按真实值排
        self.proxy = ObsSortProxy(self)
        self.proxy.setSourceModel(self.model)
        self.table = QTableView()
        self.table.setModel(self.proxy)
        self.table.setSortingEnabled(True)
        # 让 Qt 默认排序走我们的代理（不可排的列会被忽略）
        self.table.horizontalHeader().setSortIndicatorShown(True)
        self.table.horizontalHeader().sortIndicatorChanged.connect(self._on_sort_requested)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        # ★ 选中行 = **亮黄**高亮（默认的蓝底会把深蓝加粗的"打勾"字压得看不清）。
        #   只动视图调色板，不写样式表 —— 样式表会接管整张表的绘制，
        #   把模型里按测点分组铺的白/浅蓝/淡黄底纹一起顶掉。
        pal = self.table.palette()
        pal.setColor(QPalette.ColorRole.Highlight, C_SEL_BG)
        pal.setColor(QPalette.ColorRole.HighlightedText, C_SEL_TEXT)
        self.table.setPalette(pal)
        # 选中行的底色最终由这个代理画（系统样式在非激活窗口下会把它画没了）
        self.table.setItemDelegate(RowHighlightDelegate(self.table))
        self.table.setAlternatingRowColors(False)
        self.table.verticalHeader().setDefaultSectionSize(30)   # 字体大了，行也加高
        self.table.horizontalHeader().setSectionsMovable(True)   # ★ 列可拖动排序
        self.table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
        self.table.selectionModel().selectionChanged.connect(self._on_table_selection)
        # ★ 手动筛选：右键对选中的观测做人工取舍
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context_menu)
        v.addWidget(self.table, 1)
        self._update_sel_buttons()        # 一开始没选中行 → 三个按钮置灰
        return box

    def _build_plot_panel(self):
        box = QGroupBox("⑤ 图形")
        self.plot_box = box                       # 供"独立窗口最大化"用（reparent）
        v = QVBoxLayout(box)
        bar = QHBoxLayout()
        self.cmb_view = QComboBox()
        for key, label in VIEW_KINDS.items():
            self.cmb_view.addItem(label, key)
        self.cmb_view.currentIndexChanged.connect(
            lambda: self.plot.set_kind(str(self.cmb_view.currentData())))
        bar.addWidget(QLabel("视图"))
        bar.addWidget(self.cmb_view, 1)
        v.addLayout(bar)
        self.plot = ObsPlot()
        self.plot.set_click_callback(self._on_plot_clicked)
        self.plot.set_box_callback(self._on_plot_box_selected)
        self.plot.set_toggle_box_callback(self._on_plot_box_toggled)
        self.plot.set_empty_click_callback(self._on_plot_empty_clicked)
        v.addWidget(self.plot, 1)
        return box

    def _build_result_bar(self):
        """窗口最底下那条：只留"保留/剔除"统计（结果动作已搬到第 ④ 面板的按钮排）。"""
        bar = QHBoxLayout()
        self.lbl_result = QLabel("尚未载入数据")
        self.lbl_result.setProperty("title", True)
        bar.addWidget(self.lbl_result)
        bar.addStretch(1)
        return bar

    # ================================================================== 载入
    def open_file(self) -> None:
        fp, _ = QFileDialog.getOpenFileName(
            self, "选择 CG-5 手簿", "", "CG-5 观测文件 (*.txt *.TXT *.csv *.dat);;所有文件 (*)")
        if not fp:
            return
        self.load_file(fp)

    def reload(self) -> None:
        if self.f is None or not self.f.path:
            self.open_file()
            return
        self.load_file(self.f.path, keep_view=True)

    def load_file(self, path: str, keep_view: bool = False) -> None:
        try:
            f = cg5.read_file(path)
        except Exception as exc:                       # noqa: BLE001
            QMessageBox.warning(self, "读取失败", f"{path}\n\n{exc}")
            return
        if not f.rows:
            QMessageBox.warning(
                self, "没读到观测",
                f"{Path(path).name}\n\n文件里没有识别到 CG-5 观测行。"
                "请确认是仪器导出的原始手簿（含 `/------LINE---STATION...` 列头）。")
            return

        self.f = f
        self.manual_keep.clear()
        self.manual_drop.clear()
        self.colorder = ColOrder(order=default_visible(f.columns), reason=True)

        self.lbl_file.setText(
            f"<b>{Path(path).name}</b>　观测 {len(f.rows)} 条　"
            f"日期 {len(f.dates)} 天　Survey {len({r.survey for r in f.rows if r.survey})} 个　"
            f"数据表 {f.n_tables} 张　仪器 S/N "
            f"{f.rows[0].sn or '—'}　潮汐改正 {f.tide_correction or '—'}")

        # 范围：两条线一起重建（默认最新一天 + 全部 Survey）
        keep = None
        if keep_view:
            keep = (sorted(self.scope_widget.selected_dates()),
                    sorted(self.scope_widget.selected_surveys()))
        self.scope_widget.load(f, keep=keep)
        if self._source_dlg is not None:
            self._source_dlg.set_file(f)
            self._source_dlg._loaded_path = f.path
        self._render()
        if not keep_view:
            self.statusBar().showMessage(
                f"已载入 {Path(path).name}：{len(f.rows)} 条观测，"
                f"当前范围 {len(self.scope)} 条", 8000)

    # ---- 两条线的"带入"映射（注入给 ScopeWidget）
    def _surveys_on(self, dates) -> list[str]:
        return self.f.surveys_on(set(dates)) if self.f else []

    def _dates_of(self, surveys) -> list[str]:
        return self.f.dates_of(set(surveys)) if self.f else []

    def _on_scope_changed(self) -> None:
        """日期/Survey 任一勾选变化 → 立即重算（人工干预保留，因为范围没变条目）。"""
        if self._loading or self.f is None:
            return
        self._render()

    # ---- 当前两条线的取值（供汇总/导出/默认文件名使用）
    def _scope_dates(self) -> list[str]:
        return sorted(self.scope_widget.selected_dates(), reverse=True)

    def _scope_surveys(self) -> list[str]:
        return sorted(self.scope_widget.selected_surveys())

    # ================================================================== 条件
    def _set_conditions(self, conds: list[Cond], *, preset_name: str = "") -> None:
        """整条栈替换（**全部勾选**）并立即生效。"""
        self.conds = [Cond.from_dict(c.to_dict()) for c in conds]
        for c in self.conds:
            c.enabled = True                    # 切换组合就全部勾选
        self._current_preset = preset_name
        self.manual_keep.clear()
        self.manual_drop.clear()
        self._refresh_cond_table()
        if preset_name:
            self._select_preset_in_combo(preset_name)
        self._render()

    # ---- 参数组合：切换 / 存 / 改 / 删
    def _reload_preset_combo(self) -> None:
        self._loading = True
        self.cmb_preset.clear()
        for p in self.store.presets:
            it = f"{p.name}" + ("" if not p.builtin else "（内置）")
            self.cmb_preset.addItem(it, p.name)
            self.cmb_preset.setItemData(
                self.cmb_preset.count() - 1,
                (p.desc or "") + ("\n（内置组合，不能改名/删除）" if p.builtin else
                                  "\n（自定义，可改名/删除）"),
                Qt.ItemDataRole.ToolTipRole)
        self._loading = False
        if self.store.error:
            self.statusBar().showMessage(
                f"参数组合文件读取失败，本次改动只存在内存里：{self.store.error}", 12000)

    def _select_preset_in_combo(self, name: str) -> None:
        i = self.cmb_preset.findData(name)
        if i >= 0 and i != self.cmb_preset.currentIndex():
            self._loading = True
            self.cmb_preset.setCurrentIndex(i)
            self._loading = False

    def _preset_menu(self) -> None:
        """「参数组合 ▾」：存参数 / 重命名 / 删除（原右侧三个按钮收进菜单）。"""
        from PySide6.QtWidgets import QMenu

        p = self.store.get(str(self.cmb_preset.currentData() or ""))
        m = QMenu(self)
        m.addAction("存参数…（把当前条件栈存成组合）", self._save_preset)
        m.addSeparator()
        a_ren = m.addAction("重命名…", self._rename_preset)
        a_del = m.addAction("删除", self._delete_preset)
        builtin = bool(p and p.builtin)
        a_ren.setEnabled(not builtin)
        a_del.setEnabled(not builtin)
        if builtin:
            a_ren.setToolTip("内置组合不能改名")
            a_del.setToolTip("内置组合不能删除")
        m.exec(self.btn_preset_menu.mapToGlobal(
            self.btn_preset_menu.rect().bottomLeft()))

    def _on_preset_activated(self, _idx: int) -> None:
        if self._loading:
            return
        name = str(self.cmb_preset.currentData() or "")
        preset = self.store.get(name)
        if preset is None:
            return
        # ★ 切换后立即全部勾选条件栈里的，并生效
        self._set_conditions(preset.instantiate(), preset_name=name)
        self.statusBar().showMessage(
            f"已切换参数组合「{name}」：{len(self.conds)} 条条件全部勾选并生效", 6000)

    def _save_preset(self) -> None:
        """把当前条件栈存成一个参数组合。"""
        if not getattr(self, "conds", None):
            QMessageBox.information(self, "提示", "条件栈是空的，先添加条件再存。")
            return
        default = self._current_preset or "我的条件"
        name, ok = QInputDialog.getText(self, "存参数组合",
                                        "参数组合名称：", text=default)
        if not ok:
            return
        name = name.strip()
        if not name:
            return
        exists = self.store.get(name) is not None
        if exists:
            r = QMessageBox.question(
                self, "已存在同名组合",
                f"「{name}」已存在，覆盖它吗？\n（内置组合不能覆盖）",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if r != QMessageBox.StandardButton.Yes:
                return
        okk, msg = self.store.add(name, self.conds, overwrite=exists)
        if not okk:
            QMessageBox.warning(self, "存参数失败", msg)
            return
        self._reload_preset_combo()
        self._set_conditions(self.conds, preset_name=name)
        self.statusBar().showMessage(
            f"已存为参数组合「{name}」" + (f"（{msg}）" if msg else ""), 8000)

    def _rename_preset(self) -> None:
        name = str(self.cmb_preset.currentData() or "")
        preset = self.store.get(name)
        if preset is None:
            return
        if preset.builtin:
            QMessageBox.information(self, "提示", f"「{name}」是内置组合，不能改名。")
            return
        new, ok = QInputDialog.getText(self, "重命名参数组合",
                                       "新名称：", text=name)
        if not ok or not new.strip():
            return
        okk, msg = self.store.rename(name, new.strip())
        if not okk:
            QMessageBox.warning(self, "重命名失败", msg)
            return
        self._reload_preset_combo()
        self._current_preset = new.strip()
        self._select_preset_in_combo(self._current_preset)
        self._refresh_preset_state()

    def _delete_preset(self) -> None:
        name = str(self.cmb_preset.currentData() or "")
        preset = self.store.get(name)
        if preset is None:
            return
        if preset.builtin:
            QMessageBox.information(self, "提示", f"「{name}」是内置组合，不能删除。")
            return
        r = QMessageBox.question(
            self, "删除参数组合", f"删除「{name}」？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if r != QMessageBox.StandardButton.Yes:
            return
        okk, msg = self.store.remove(name)
        if not okk:
            QMessageBox.warning(self, "删除失败", msg)
            return
        self._reload_preset_combo()
        self._current_preset = ""
        self._refresh_preset_state()
        self.statusBar().showMessage(f"已删除参数组合「{name}」", 5000)

    def _add_condition(self) -> None:
        kinds = list(COND_KINDS)
        kind = kinds[0] if len(kinds) == 1 else None
        if kind is None:
            dlg = _PickKindDialog(self)
            if dlg.exec() != QDialog.DialogCode.Accepted or not dlg.kind():
                return
            kind = dlg.kind()
        meta = COND_KINDS[kind]
        pd = CondDialog(kind, dict(meta.params), self)
        if pd.exec() != QDialog.DialogCode.Accepted:
            return
        self.conds.append(Cond(kind, pd.values(), source="manual"))
        self._refresh_cond_table()
        self._render()
        self._refresh_preset_state()

    def _edit_condition(self, row: int) -> None:
        if not (0 <= row < len(self.conds)):
            return
        c = self.conds[row]
        pd = CondDialog(c.kind, dict(c.params), self)
        if pd.exec() != QDialog.DialogCode.Accepted:
            return
        c.params = pd.values()
        c.source = "manual"
        self._refresh_cond_table()
        self._render()
        self._refresh_preset_state()

    def _del_condition(self) -> None:
        row = self.tbl_cond.currentRow()
        if 0 <= row < len(self.conds):
            del self.conds[row]
            self._refresh_cond_table()
            self._render()
            self._refresh_preset_state()

    def _resize_cond_cols(self) -> None:
        """定「连接 / 条件 / 参数」三列的宽度，**剩余全给「命中」**，整条表正好铺满。

        · 连接 = **2 个汉字** + 下拉框的箭头与内边距（用户要求"再加长点"）；
        · 条件 = **4 个汉字**；
        · 参数 = **最多 16 个汉字**，且**至少放得下当前最长的参数写法**
          （用户："连接和参数列再加长点，命中列缩短"）；
        · 命中 = `Stretch` 吃掉剩下的宽度（只留得下表头 + 三四位数字）。

        横向滚动条已经关掉，所以这里必须保证"三列 + 勾选 + 命中"塞得进视口：
        实在窄就先压参数（到 4 字），再压条件（到 3 字）。用户口径：
        "怎么现在又变成需要左右滑动了，铺满就行，不要左右滑动"。
        """
        if getattr(self, "tbl_cond", None) is None:      # resizeEvent 可能早于建表
            return
        fm = self.tbl_cond.fontMetrics()
        # ★ 一个字宽 = "汉"（**单字**）的宽度 —— 写成 "汉字"（两个字）所有列都会宽一倍
        cjk = fm.horizontalAdvance("汉") or 14
        # ★ 用户（本轮）："连接和参数列再加长点，命中列缩短" ——
        #   连接再多给一点控件余量、参数上限从 10 字放宽到 16 字，
        #   富余宽度优先喂给「参数」，「命中」只留得下表头 + 三四位数字。
        cap = cjk * 16 + 12                      # 参数列上限（16 个字宽）
        link_w = cjk * 2 + 48                    # 「首要」两字 + 下拉框箭头/内边距（加长）
        cond_w = cjk * 4 + 10
        need = 0
        for c in (getattr(self, "conds", None) or []):
            need = max(need, fm.horizontalAdvance(_param_text(c)))
        param_w = min(max(need + 10, cjk * 3), cap)     # 保证参数不被省略
        col0 = self.tbl_cond.columnWidth(0) or (fm.horizontalAdvance("勾选") + 22)
        min_hit = fm.horizontalAdvance("命中") + 24     # 命中列：表头 + 三四位数字就够
        avail = int(self.tbl_cond.viewport().width() or self.tbl_cond.width())
        if avail:
            # 有富余就把参数加长（用户口径：参数加长、命中缩短）
            room = avail - (col0 + link_w + cond_w + min_hit)
            param_w = min(cap, max(param_w, room))
            over = (col0 + link_w + cond_w + param_w + min_hit) - avail
            if over > 0:                                # 先把参数压到"够用"
                param_w = max(need + 10, param_w - over)
                over = (col0 + link_w + cond_w + param_w + min_hit) - avail
            if over > 0:                                # 还超就压条件
                cond_w = max(cjk * 3, cond_w - over)
                over = (col0 + link_w + cond_w + param_w + min_hit) - avail
            if over > 0:                                # 极端窄：参数再让一点
                param_w = max(cjk * 2, param_w - over)
        # 「命中」自己算，**不用 Stretch**：程序化改列宽时 Stretch 段不一定跟着重算，
        # 会出现"五列加起来比视口宽"→ 右边被切掉一截（实测差 46px）。这里把它算成
        # 剩下的全部宽度，五列之和**正好等于视口**。
        hit_w = min_hit
        if avail:
            hit_w = max(min_hit, avail - (col0 + link_w + cond_w + param_w))
            param_w = max(cjk * 2, avail - (col0 + link_w + cond_w + hit_w))
        self.tbl_cond.setColumnWidth(1, int(link_w))
        self.tbl_cond.setColumnWidth(2, int(cond_w))
        self.tbl_cond.setColumnWidth(3, int(param_w))
        self.tbl_cond.setColumnWidth(4, int(hit_w))

    def _refresh_cond_table(self) -> None:
        self._loading = True
        t = self.tbl_cond
        t.setRowCount(len(self.conds))
        for i, c in enumerate(self.conds):
            it = QTableWidgetItem()
            it.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled
                        | Qt.ItemFlag.ItemIsSelectable)
            it.setCheckState(Qt.CheckState.Checked if c.enabled else Qt.CheckState.Unchecked)
            it.setToolTip("勾上=参与筛选，取消=不参与")
            t.setItem(i, 0, it)

            # ---- 连接词：首要 / 或 / 且（就地可改，改完立刻重算） ----
            cmb = QComboBox()
            for value, cn, tip in LINKS:
                cmb.addItem(cn, value)
                cmb.setItemData(cmb.count() - 1, tip, Qt.ItemDataRole.ToolTipRole)
            cmb.setCurrentIndex(max(0, [v for v, _cn, _t in LINKS].index(c.link)))
            cmb.currentIndexChanged.connect(
                lambda _idx, row=i, box=cmb: self._on_link_changed(row, box))
            t.setCellWidget(i, 1, cmb)

            t.setItem(i, 2, QTableWidgetItem(c.cn))
            t.item(i, 2).setToolTip(f"{c.meta.desc}\n依据：{c.meta.basis}")

            t.setItem(i, 3, QTableWidgetItem(_param_text(c)))
            # 参数列已按最长文字定宽（保证完整显示）；悬停再给出**带标签的长写法**
            t.item(i, 3).setToolTip(c.describe())
            t.setItem(i, 4, QTableWidgetItem("—"))
            t.item(i, 4).setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        if self.conds and t.currentRow() < 0:
            t.selectRow(0)
        self._loading = False
        self._resize_cond_cols()          # 参数列跟着当前条件重新定宽
        self._cap_cond_table_height()     # 条件表最高 8 行，剩下的高度留给日志
        self._refresh_logic_label()

    def _on_link_changed(self, row: int, box) -> None:
        """「连接」列的下拉：首要 / 或 / 且 —— 立即重算。"""
        if self._loading or not (0 <= row < len(self.conds)):
            return
        link = str(box.currentData() or "and")
        if self.conds[row].link == link:
            return
        self.conds[row].link = link
        self.conds[row].source = "manual"
        self._render()
        self._refresh_logic_label()
        self._refresh_preset_state()
        self.statusBar().showMessage(
            f"第 {row + 1} 条条件改为「{LINK_CN.get(link, link)}」"
            f"　当前判定：{logic_text(self.conds)}", 8000)

    def _refresh_logic_label(self) -> None:
        """把条件栈翻成一句人话贴在表下（或/且一眼看清）。"""
        if not hasattr(self, "lbl_logic"):
            return
        self.lbl_logic.setText("判定：<b>" + logic_text(self.conds) + "</b>")

    def _refresh_preset_state(self) -> None:
        """提示当前栈与所选组合是否一致（改了参数没存时提醒一下）。"""
        name = self._current_preset
        if not name:
            self.lbl_preset_state.setText(
                "<span style='color:#8a8f98'>未绑定参数组合；改了条件可点「存参数」存下来。</span>")
            return
        p = self.store.get(name)
        if p is not None and p.same_as(self.conds):
            self.lbl_preset_state.setText(
                f"<span style='color:#1a7f37'>当前条件栈 = 组合「{name}」</span>")
        else:
            self.lbl_preset_state.setText(
                f"<span style='color:#b45309'>当前条件栈已不同于组合「{name}」"
                "（点「存参数」可覆盖保存）</span>")

    def _move_condition(self, delta: int) -> None:
        row = self.tbl_cond.currentRow()
        j = row + delta
        if not (0 <= row < len(self.conds)) or not (0 <= j < len(self.conds)):
            return
        self.conds[row], self.conds[j] = self.conds[j], self.conds[row]
        self._refresh_cond_table()
        self.tbl_cond.selectRow(j)
        self._render()
        self._refresh_preset_state()

    def _cond_menu(self) -> None:
        """「条件 ▾」：添加 / 改参数 / 删除。

        ② 面板要压窄，所以把三个按钮收成一个菜单 + 两个箭头。
        """
        from PySide6.QtWidgets import QMenu

        m = QMenu(self)
        m.addAction("＋ 添加条件…", self._add_condition)
        m.addAction("改参数…", lambda: self._edit_condition(self.tbl_cond.currentRow()))
        m.addAction("删除", self._del_condition)
        m.exec(self.btn_cond_menu.mapToGlobal(
            self.btn_cond_menu.rect().bottomLeft()))

    def _cond_context_menu(self, pos) -> None:
        """条件表右键：改参数 / 删除 / 上下移。"""
        from PySide6.QtWidgets import QMenu

        row = self.tbl_cond.rowAt(pos.y())
        if row >= 0:
            self.tbl_cond.selectRow(row)
        m = QMenu(self)
        m.addAction("改参数…", lambda: self._edit_condition(self.tbl_cond.currentRow()))
        m.addAction("删除", self._del_condition)
        m.addSeparator()
        m.addAction("上移", lambda: self._move_condition(-1))
        m.addAction("下移", lambda: self._move_condition(+1))
        m.exec(self.tbl_cond.viewport().mapToGlobal(pos))

    def _refresh_cond_hits(self) -> None:
        """把各条件的命中数写回条件栈（诊断"哪条在杀数据"）。"""
        self._loading = True
        for i, c in enumerate(self.conds):
            item = self.tbl_cond.item(i, 4)              # 第 5 列 = 命中
            if item is None:
                continue
            if not c.enabled:
                item.setText("—")
                continue
            item.setText(str(self.cond_hits.get(c.describe(), 0)))
        self._loading = False

    def _on_cond_item_changed(self, item: QTableWidgetItem) -> None:
        if self._loading or item.column() != 0:
            return
        row = item.row()
        if 0 <= row < len(self.conds):
            self.conds[row].enabled = item.checkState() == Qt.CheckState.Checked
            self._render()                              # ★ 勾选立即生效
            self._refresh_logic_label()
            self._refresh_preset_state()

    # ================================================================== 显示模式
    def _on_view_mode_changed(self, *_a) -> None:
        """「只看人工改过的」与"显示全部数据 / 只看筛选结果"互斥，最后一个操作生效。"""
        if self._loading:
            return
        if self.chk_only_manual.isChecked():
            self.show_all = False
        elif self.sender() is self.chk_only_manual:
            # 取消"只看人工改过的" → 回到默认（显示全部数据）
            self.show_all = True
        self._render()
        self._status_view_mode()

    def _status_view_mode(self) -> None:
        if self.chk_only_manual.isChecked():
            self.statusBar().showMessage("仅显示人工改过的观测", 4000)
        elif self.show_all:
            self.statusBar().showMessage(
                "显示全部导入数据：筛出的打勾、被剔除的不打勾", 4000)
        else:
            self.statusBar().showMessage("仅显示筛选结果（已打勾的）", 4000)

    def show_only_filtered(self) -> None:
        """切换为"只显示筛选结果"。"""
        self._loading = True
        self.show_all = False
        self.chk_only_manual.setChecked(False)
        self._loading = False
        self._render()
        self.statusBar().showMessage(
            f"只显示筛选结果：{len(self._keep_rows)} 条", 5000)

    def show_all_data(self) -> None:
        """切换为"显示全部数据"（默认）。"""
        self._loading = True
        self.show_all = True
        self.chk_only_manual.setChecked(False)
        self._loading = False
        self._render()
        self._status_view_mode()

    # ================================================================== 源文件预览
    def show_source_view(self) -> None:
        """打开/前置「查看原数据」窗口，并同步当前选中。"""
        if self.f is None:
            QMessageBox.information(self, "提示", "请先打开一个 CG-5 手簿。")
            return
        if self._source_dlg is None:
            self._source_dlg = SourceViewDialog(self)
            self._source_dlg.finished.connect(self._on_source_closed)
        dlg = self._source_dlg
        if getattr(dlg, "_loaded_path", None) != self.f.path:
            dlg.set_file(self.f)
            dlg._loaded_path = self.f.path
        dlg.set_selected_rows(self._selected_source_rows())
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self.statusBar().showMessage(
            "源文件预览：表格选中会自动跳到对应源行（F3 可再次打开）", 6000)

    def _on_source_closed(self, *_a) -> None:
        self._source_dlg = None

    def _sync_source_view(self) -> None:
        """表格选中变化 → 通知预览窗口（没开就什么都不做）。"""
        dlg = self._source_dlg
        if dlg is None or not dlg.isVisible():
            return
        dlg.set_selected_rows(self._selected_source_rows())

    # ================================================================== 手动筛选
    def _set_manual(self, src: int, keep: bool, *, render: bool = True) -> None:
        """把一条观测标记为**人工保留 / 人工剔除**（叠加在条件结果之上）。

        只要用户显式动过，就**记下来**（即使结果与自动判定一致）——
        这是"人工复核"的台账依据；混同于自动结果会让复核痕迹消失。
        """
        if keep:
            self.manual_keep.add(src)
            self.manual_drop.discard(src)
        else:
            self.manual_drop.add(src)
            self.manual_keep.discard(src)
        if render:
            self._render()

    def _selected_source_rows(self) -> list[int]:
        """表格里当前选中的行 → 源文件行号。"""
        out = []
        for i in self.table.selectionModel().selectedRows():
            src = self.model.source_row(self.proxy.mapToSource(i).row())
            if src >= 0:
                out.append(src)
        return out

    def _manual_bulk(self, keep: bool) -> None:
        """"勾选选中 / 取消选中"（以及右键"人工保留/剔除"）：作用于选中的行；
        没选中就作用于当前所有可见行（右键菜单那条路）。

        ★ 操作完**把多选恢复回去** —— 否则点一次按钮选中就没了，
          没法接着点「反选选中」或者对同一批行连着做两种操作。
        """
        rows = self._selected_source_rows()
        had_sel = bool(rows)
        if not rows:
            rows = [self.model.source_row(r) for r in range(self.model.rowCount())]
        rows = [s for s in rows if s >= 0]
        for s in rows:
            self._set_manual(s, keep, render=False)
        self._render()
        if had_sel:
            self._select_table_rows(set(rows))
        self.statusBar().showMessage(
            f"已人工{'保留' if keep else '剔除'} {len(rows)} 条观测"
            f"（人工干预合计 {len(self.manual_keep) + len(self.manual_drop)} 条）", 6000)

    def _clear_manual_rows(self) -> None:
        """把选中行的人工干预清掉（回到条件判定结果）。"""
        rows = self._selected_source_rows()
        for s in rows:
            self.manual_keep.discard(s)
            self.manual_drop.discard(s)
        self._render()
        self.statusBar().showMessage(f"已恢复 {len(rows)} 条观测的条件结果", 5000)

    def _table_context_menu(self, pos) -> None:
        """结果表右键菜单：人工取舍 + 与图形联动。"""
        from PySide6.QtWidgets import QMenu

        idx = self.table.indexAt(pos)
        if idx.isValid() and idx.row() not in {
                i.row() for i in self.table.selectionModel().selectedRows()}:
            self.table.selectRow(idx.row())
        rows = self._selected_source_rows()

        m = QMenu(self)
        n = len(rows)
        suffix = f"（{n} 条）" if n else "（当前全部可见行）"
        m.addAction(f"人工保留{suffix}", lambda: self._manual_bulk(True))
        m.addAction(f"人工剔除{suffix}", lambda: self._manual_bulk(False))
        m.addAction(f"恢复条件结果{suffix}", self._clear_manual_rows)
        m.addSeparator()
        m.addAction("在图上定位选中的观测（缩放到该时间范围）",
                    self._zoom_plot_to_selection)
        m.addAction("恢复图形全览", self.plot.reset_view)
        m.addSeparator()
        m.addAction("复制选中的观测…", self._copy_selection)
        m.addSeparator()
        m.addAction("查看原数据（跳到选中观测的源行）…", self.show_source_view)
        # 清空表格选择（= 图上点空白处那一下；Shift 框选一大批后想一次性放开时用）
        _act_clear = m.addAction("取消表格选中（清空选择）", self._on_plot_empty_clicked)
        _act_clear.setEnabled(bool(rows))
        m.exec(self.table.viewport().mapToGlobal(pos))

    def _zoom_plot_to_selection(self) -> None:
        """把图形缩放到选中观测的时间范围。"""
        rows = self._selected_source_rows()
        if not rows:
            return
        self.plot.focus_rows(rows)

    def _copy_selection_legacy_removed(self) -> None:
        """（旧实现已合并进 `copy_to_clipboard`：现在列与表格一致、含勾选框，
        且 Ctrl+C / 右键都走同一条路。）"""

    # ================================================================== 计算
    def _on_check_toggled(self, src: int, checked: bool) -> None:
        """表格里勾选/取消「处理理由」列的复选框 = 人工保留/剔除。"""
        self._set_manual(src, checked)

    # ★ 旧的 `_bulk()`（范围内全选 / 全不选）已按用户口径删掉：
    #   "全选和全不选 取消掉，这两个按钮没什么用处" —— 改由
    #   「勾选选中 / 取消勾选」作用于**表格里选中的行**。
    #   `_invert_selection()`（反选选中）也在下一轮按用户要求删掉了。

    def _clear_table_selection(self) -> None:
        """**取消选中**：只清空表格里的行选中（高亮），**勾选状态一个都不动**。

        用户口径："取消选中的意思是取消表格行的选中，不是取消勾选，
        勾选和选中是两回事。" —— 所以这里绝不能碰 `manual_keep / manual_drop`。
        """
        if not self._has_table_selection():
            return
        self.table.clearSelection()      # → selectionChanged → 图上高亮/预览跟着清
        self.statusBar().showMessage(
            "已取消表格选中（只是放开高亮，勾选状态没动）", 5000)

    def _has_table_selection(self) -> bool:
        sm = self.table.selectionModel()
        return bool(sm is not None and sm.hasSelection())

    def _update_sel_buttons(self) -> None:
        """「取消选中 / 勾选选中 / 取消勾选」只在表格里**有选中行**时可用。

        （与"查看原数据"里的上/下一条同理：没得作用就置灰，
          不做"点了没反应"的按钮。）
        """
        on = self._has_table_selection()
        for b in (getattr(self, "btn_deselect", None), getattr(self, "btn_check", None),
                  getattr(self, "btn_uncheck", None)):
            if b is not None:
                b.setEnabled(on)

    def _reset_manual(self) -> None:
        self.manual_keep.clear()
        self.manual_drop.clear()
        self._render()
        self.statusBar().showMessage("已恢复条件筛选结果（人工干预已清除）", 4000)

    def _toggle_view_mode(self) -> None:
        if self.show_all:
            self.show_only_filtered()
        else:
            self.show_all_data()

    # ============================================================ 独立窗口最大化
    def _float_both(self) -> None:
        """把 ④ 结果表 + ⑤ 图形**一起**拎进一个独立窗口并最大化（两者绑定）。

        用户口径："是同时最大化，表格和图形，两者绑定。按钮放在只看筛选结果的下面。"

        已经在浮动 → 前置/再最大化，不重复开窗。
        关掉那个窗口 = `_dock_both()` 把两块都放回原来的栏位。
        """
        win = self._float_wins.get("both")
        if win is not None and win.isVisible():
            win.showMaximized()
            win.raise_()
            win.activateWindow()
            return

        # 记住各自原来在第几栏 + 主窗口三栏宽度
        self._float_index = {"table": self.split.indexOf(self.result_box),
                             "plot": self.split.indexOf(self.plot_box)}
        if not self._split_sizes_before_float:
            self._split_sizes_before_float = list(self.split.sizes())

        fw = FloatPanel("④ 结果表 + ⑤ 图形 —— 独立窗口（关掉 = 放回主窗口）",
                        [self.result_box, self.plot_box], self._dock_both)
        self._float_wins["both"] = fw          # FloatPanel 里 addWidget 已完成 reparent
        fw.showMaximized()
        fw.raise_()
        fw.activateWindow()
        self.statusBar().showMessage(
            "结果表 + 图形已放到同一个独立窗口（左表右图，关闭即放回主窗口）", 8000)

    def _dock_both(self) -> None:
        """把一起浮动出去的 ④ 与 ⑤ 塞回主窗口（原栏位 + 原三栏宽度）。"""
        win = self._float_wins.pop("both", None)
        idx = getattr(self, "_float_index", {}) or {}
        for box, key, default in ((self.result_box, "table", 1),
                                  (self.plot_box, "plot", 2)):
            box.setParent(None)
            at = max(0, min(int(idx.get(key, default)), self.split.count()))
            self.split.insertWidget(at, box)   # 塞回原来的栏位（先表后图，顺序复原）
            box.show()
        if win is not None:
            win.hide()
            win.deleteLater()
        if self._split_sizes_before_float:
            self.split.setSizes(self._split_sizes_before_float)   # 还原三栏宽度
            self._split_sizes_before_float = []
        self.plot.redraw()                     # 画布换了宿主，重绘一次
        self.statusBar().showMessage("结果表与图形已放回主窗口", 5000)

    def _on_plot_box_selected(self, sources) -> None:
        """图形框选 → 表格选中对应行（双向联动），并可直接做人工取舍。"""
        srcs = set(int(s) for s in sources)
        self._select_table_rows(srcs)
        if not srcs:
            self.statusBar().showMessage("框选范围内没有观测", 4000)
            return
        n_kept = len(srcs & set(self._keep_rows))
        self.statusBar().showMessage(
            f"框选到 {len(srcs)} 条观测（保留 {n_kept} 条），已在表格中选中"
            "　—　右键可人工保留/剔除，或「恢复条件结果」撤销", 9000)

    def _on_plot_box_toggled(self, sources) -> None:
        """Ctrl + 拖动框选 → 这一批观测**整体取反**（保留的剔除、剔除的保留）。

        为什么是"整批取反"而不是"全设为剔除"：框里常常既有保留的也有已剔除的，
        取反能让"圈一片重新决定"一次到位，也不会因为重复框同一片而反复改变。
        """
        srcs = [int(s) for s in sources]
        if not srcs:
            self.statusBar().showMessage("框选范围内没有观测", 4000)
            return
        keep_set = set(self._keep_rows)
        for s in srcs:
            self._set_manual(s, s not in keep_set, render=False)
        self._render()
        n_back = len([s for s in srcs if s in set(self._keep_rows)])
        self.statusBar().showMessage(
            f"Ctrl+框选 {len(srcs)} 条已取反 → 保留 {n_back} 条、剔除 "
            f"{len(srcs) - n_back} 条（人工复核已记账，可用「恢复条件结果」撤销）", 9000)

    def _on_plot_empty_clicked(self) -> None:
        """点击图形空白处 → 取消当前选中（表格选中清空、图上高亮撤掉）。"""
        if not self._selected_source_rows():
            return                                      # 本来就没选中，不必刷
        self._select_table_rows(set())
        self.statusBar().showMessage("已取消选中", 4000)

    def _select_table_rows(self, sources: set[int]) -> None:
        """按源行号在表格里选中对应行（自动滚到第一行）。"""
        sm = self.table.selectionModel()
        if sm is None:
            return
        from PySide6.QtCore import QItemSelection, QItemSelectionModel

        vmap = self.model.view_row_map()
        sel = QItemSelection()
        first = None
        for src in sorted(sources):          # 升序：选中顺序稳定（便于图上/预览逐条走）
            r = vmap.get(src)
            if r is None:
                continue
            left = self.model.index(r, 0)
            right = self.model.index(r, self.model.columnCount() - 1)
            sel.select(left, right)
            if first is None:
                first = r
        self._loading = True
        try:
            sm.select(sel, QItemSelectionModel.SelectionFlag.ClearAndSelect
                      | QItemSelectionModel.SelectionFlag.Rows)
        finally:
            self._loading = False
        if first is not None:
            self.table.scrollTo(self.proxy.mapFromSource(self.model.index(first, 0)),
                                QAbstractItemView.ScrollHint.PositionAtCenter)

    def _on_plot_clicked(self, src: int, toggle: bool = False) -> None:
        """单击散点 = **只选中**（在表格里定位），不动保留状态；
        **Ctrl + 单击** = 该观测**取反**（剔除 / 取消，与表格勾选同一套账）。"""
        if toggle:
            keep_now = src in set(self._keep_rows)
            self._set_manual(src, not keep_now)
            self.statusBar().showMessage(
                f"Ctrl+单击：源行 {src} → {'剔除' if keep_now else '保留'}"
                "（与表格勾选同一套人工复核账）", 6000)
        row = self.model.view_row_of(src)
        if row < 0:
            return
        idx = self.proxy.mapFromSource(self.model.index(row, 0))
        if idx.isValid():
            self.table.selectRow(idx.row())
            self.table.scrollTo(idx, QAbstractItemView.ScrollHint.PositionAtCenter)

    def _render(self) -> None:
        if self.f is None:
            self._refresh_summary(0, 0)
            return

        dates = self.scope_widget.selected_dates()
        surveys = self.scope_widget.selected_surveys()
        # 两条线：组内并集、两组交集；某组为空 = 该线不参与筛选
        self.scope = self.f.filter_scope(dates, surveys)
        in_scope = {s: True for s in self.scope}

        # ---- 条件判定（只算一次） ----
        hits, self.cond_hits = apply_conditions(self.f, self.scope, self.conds)
        self.auto_reason = {src: h.reason for src, h in zip(self.scope, hits) if not h.keep}
        # ★ 被「最终取值」挑中的那一条：处理理由列写「最终取值」（其余保留行写「满足条件」）
        self.picked_rows = {src for src, h in zip(self.scope, hits) if h.picked}
        # ★ 通过了条件、只是没被最终取值挑中的：处理理由也写「满足条件」，另用字体颜色
        self.passed_rows = {src for src, h in zip(self.scope, hits) if h.passed}

        # 人工决定只在"当前范围"内生效（范围外的留着，切回来还在）
        scope_set = set(self.scope)
        m_keep = self.manual_keep & scope_set
        m_drop = self.manual_drop & scope_set
        manual = m_keep | m_drop

        keep_set: set[int] = set()
        for src in self.scope:
            keep = src not in self.auto_reason                 # 条件判定
            if src in m_keep:
                keep = True
            if src in m_drop:
                keep = False
            if keep:
                keep_set.add(src)
        self._keep_rows = [s for s in self.scope if s in keep_set]

        # ---- 表格 ----
        # 默认只列"保留的 + 人工改过的"；但若一条都没保留（条件太严或数据本身不合格），
        # 必须退回显示整个范围，否则表格空空如也、连手工勾回来的机会都没有。
        if self.chk_only_manual.isChecked():
            idx = [s for s in self.scope if s in manual]
        elif self.show_all or not keep_set:
            idx = list(self.scope)          # ★ 默认：全部导入数据，筛出的打勾
        else:
            idx = [s for s in self.scope if s in keep_set]   # 只看筛选结果
        # ★ "只看筛选结果"时，表里全是保留的 → 「☑」和「处理理由」两列没有信息量，
        #   按用户要求不再显示（复制也跟着不带这两列，因为复制走的是同一份列）。
        #   注意"只看人工改过的"不算：那一屏正是要复核勾选和理由的。
        only_kept = not self.show_all and not self.chk_only_manual.isChecked()
        cols = (self.colorder.visible(self.f.columns) if only_kept
                else self.colorder.display_columns(self.f.columns))
        self.model.set_data(
            self.f, idx, cols,
            [s in in_scope for s in idx],
            [s in keep_set for s in idx],
            [s in manual for s in idx],
            [self.auto_reason.get(s, "") for s in idx],
            [s in self.picked_rows for s in idx],
            [s in self.passed_rows for s in idx])
        self._resize_table_cols()

        # ---- 图形（始终显示整个范围，便于看被剔除的点） ----
        # 理论固体潮所需的经纬度/日期由 `theory_tide_uGal` **逐行**从各自 Survey 头
        # 里取（一个范围可能跨多个 Survey、多个日期）；这里只给一个兜底值。
        info = (self.f.survey_info(self.f.rows[self.scope[0]].survey)
                if self.scope else {})
        lat = info.get("latitude")
        lon = info.get("longitude")
        first_date = self.f.rows[self.scope[0]].date if self.scope else ""
        manual_kept = {s for s in m_keep if s in keep_set}
        self.plot.set_show_all(self.show_all)     # 图形跟着表格的显示模式走
        self.plot.set_data(
            self.f, self.scope,
            [True] * len(self.scope),
            [s in keep_set for s in self.scope],
            [s in manual for s in self.scope],
            date=first_date, lat=lat, lon=lon,
            manual_kept=[s in manual_kept for s in self.scope])

        self._refresh_cond_hits()
        self._refresh_summary(len(self.scope), len(self._keep_rows), manual)
        self._refresh_scope_labels()
        if hasattr(self, "btn_only_filtered"):
            self.btn_only_filtered.setText(
                "👉 只看筛选结果" if self.show_all else "👉 显示全部数据")

    def _resize_table_cols(self) -> None:
        hh = self.table.horizontalHeader()
        for i in range(self.model.columnCount()):
            name = self.model.columns_[i]
            if name == REASON_COL:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Interactive)
                if hh.sectionSize(i) < 140:
                    hh.resizeSection(i, 210)
            elif name == CHK_COL:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Fixed)
                hh.resizeSection(i, 46)
            else:
                hh.setSectionResizeMode(i, QHeaderView.ResizeMode.ResizeToContents)
        self._mark_sortable_headers()
        # 把列序对齐到 colorder（本方法自己 moveSection，别再触发 _on_section_moved）
        self._arranging = True
        try:
            for want, name in enumerate(self.colorder.display_columns(
                    self.f.columns if self.f else [])):
                for i in range(self.model.columnCount()):
                    if self.model.columns_[i] == name:
                        have = hh.visualIndex(i)
                        if have != want:
                            hh.moveSection(have, want)
                        break
        finally:
            self._arranging = False

    def _mark_sortable_headers(self) -> None:
        """在表头上把"能不能排序"说清楚，免得点了没反应以为是坏的。"""
        tips = self.model.header_tips
        tips.clear()
        tips[CHK_COL] = ("勾选框：勾上=保留、取消=剔除（人工复核会记录）\n"
                         "此列**不参与排序**；排序只对数据列起效")
        tips[REASON_COL] = ("被哪条勾选条件剔除；手工改过的会标注（人工复核）\n"
                            "此列**不参与排序**；排序只对数据列起效")
        for name in self.model.columns_:
            if name in (CHK_COL, REASON_COL):
                continue
            tips[name] = f"点击表头按「{name}」排序（数值列按数值排）"

    def _on_sort_requested(self, column: int, order) -> None:
        """表头点击 → 交给代理排序（不可排的列会被忽略并提示）。"""
        if self.model.columnCount() == 0 or not (0 <= column < self.model.columnCount()):
            return
        name = self.model.columns_[column]
        if not self.proxy.is_sortable(column):
            self.statusBar().showMessage(
                f"「{name}」不参与排序（它是勾选框/理由列，排序只对数据列起效）", 4000)
            return
        self.proxy.sort(column, order)
        self.statusBar().showMessage(
            f"已按「{name}」{'升序' if order == Qt.SortOrder.AscendingOrder else '降序'}排序", 3000)

    def _on_section_moved(self, logical: int, _old: int, _new: int) -> None:
        """用户拖动表头 → 同步到 colorder（导出/复制也按这个顺序）。

        勾选框列与理由列固定在左边，拖动它们不改变真实列顺序。
        """
        if self.f is None or getattr(self, "_arranging", False):
            return
        hh = self.table.horizontalHeader()
        order = []
        for vis in range(self.model.columnCount()):
            log = hh.logicalIndex(vis)
            if 0 <= log < self.model.columnCount():
                name = self.model.columns_[log]
                if name in (CHK_COL, REASON_COL):
                    continue                       # 这两列固定在最左，不参与
                order.append(name)
        self.colorder.order = [c for c in order if c in self.f.columns]

    def _on_table_selection(self) -> None:
        rows = set()
        for i in self.table.selectionModel().selectedRows():
            src = self.model.source_row(self.proxy.mapToSource(i).row())
            if src >= 0:
                rows.add(src)
        self.plot.set_highlight(rows)
        self._sync_source_view()          # ★ 同步到"查看原数据"窗口
        self._update_sel_buttons()        # ★ 没选中行时那三个按钮置灰

    # ---- 统计
    def _refresh_scope_labels(self) -> None:
        if self.f is None:
            self.scope_widget.set_summary("—")
            return
        n = len(self.scope)
        d, s = self.scope_widget.selected_dates(), self.scope_widget.selected_surveys()
        head = f"命中 <b>{n}</b> / 全部 {len(self.f.rows)} 条"
        if n == 0:
            # ★ 两条线是"且"（求交集）：哪条线没勾就出 0 条 —— 说清楚是缺了哪一边
            if not d and not s:
                why = "日期 与 Survey 都要勾选（两条线求交集）"
            elif not d:
                why = "还没有勾日期（两条线求交集：缺一边就是 0 条）"
            elif not s:
                why = "还没有勾 Survey（两条线求交集：缺一边就是 0 条）"
            else:
                why = "这两组对不上（这些天里没有这些 Survey）"
            head = f"<b>0 条</b> —— {why}"
        else:
            # ★ 显示**名称**而不是个数 —— "日期 1｜Survey 3" 看不出选的是哪一天、哪个 Survey
            head += "　（" + (
                f"日期 {_names_brief(d, len(self.f.dates), '天')}"
                f"｜Survey {_names_brief(s, len(self.f.survey_names()), '个')}"
            ) + "）"
        self.scope_widget.set_summary(head)

    def _refresh_summary(self, n_total: int, n_keep: int,
                         manual: set[int] | None = None) -> None:
        manual = manual or set()
        n_drop = n_total - n_keep
        scope_set = set(self.scope)
        n_mk = len([s for s in self.manual_keep if s in scope_set])
        n_md = len([s for s in self.manual_drop if s in scope_set])
        tag = ""
        if manual:
            bits = []
            if n_mk:
                bits.append(f"人工保留 {n_mk}")
            if n_md:
                bits.append(f"人工剔除 {n_md}")
            tag = "　人工干预 " + "、".join(bits) + " 条"
        if n_total and not n_keep:
            self.lbl_result.setText(
                f"<span style='color:#b91c1c'>保留 <b>0</b> / 剔除 <b>{n_drop}</b> "
                f"/ 范围共 <b>{n_total}</b>　—　条件太严或该批数据整体不合格，"
                "表格已自动改显全部观测</span>")
        else:
            self.lbl_result.setText(
                f"保留 <b>{n_keep}</b> / 剔除 <b>{n_drop}</b> / 范围共 <b>{n_total}</b>"
                + tag)

        if self.f is None or not n_total:
            if self.f is not None:
                d, s = (self.scope_widget.selected_dates(),
                        self.scope_widget.selected_surveys())
                if d and s:
                    self.txt_summary.setHtml(
                        "<span style='color:#b91c1c'>日期与 Survey 都勾了，但两者同时"
                        f"满足的观测为 0 条 —— 勾选的 {len(d)} 天里没有勾选的那 "
                        f"{len(s)} 个 Survey。换一组勾选即可。</span>")
                else:
                    self.txt_summary.setHtml(
                        "<span style='color:#b91c1c'>范围为空：日期与 Survey "
                        "<b>两条线都要勾选</b>（求交集，缺一边就是 0 条）。</span>")
            else:
                self.txt_summary.setHtml(
                    "<span style='color:#6b7280'>尚未载入数据。</span>")
            return

        d = self._scope_dates()
        s = self._scope_surveys()
        html = [f"<b>范围</b>："
                f"日期 {('、'.join(d[:4]) + ('…' if len(d) > 4 else '')) if d else '不限'}"
                f"｜Survey {('、'.join(s[:4]) + ('…' if len(s) > 4 else '')) if s else '不限'}"
                f"　共 {n_total} 条",
                f"<b>结果</b>：保留 {n_keep}　剔除 {n_drop}"]
        if self.conds:
            html.append("<b>各条件命中</b>（= 范围内**满足该条条件**的观测数）：")
            for c in self.conds:
                if not c.enabled:
                    html.append(f"　<span style='color:#8a8f98'>· {c.describe()}"
                                f"　（未勾选）</span>")
                    continue
                if c.kind == "final_pick":
                    html.append(f"　<span style='color:#1a7f37'>▸ {c.describe()}"
                                f"　（挑选口径，不做过滤）</span>")
                    continue
                n = self.cond_hits.get(c.describe(), 0)
                color = "#1a7f37" if n else "#b91c1c"
                html.append(f"　<span style='color:{color}'>▸ {c.describe()}"
                            f"　命中 {n}</span>")
        else:
            html.append("<span style='color:#6b7280'>未设置任何条件。</span>")

        # ★ 剔除构成：把"真不合格"和"合格但没被本轮挑中"分开数
        #   （用户问过："为什么观测时长连接改为或，就全都满足了？" ——
        #    因为宽松条件进「或」组后或组几乎恒真，真剔除的条数会骤降，
        #    "满足条件"（青字）条数暴涨，看着就像全放行了。）
        if n_drop:
            n_passed = len([s for s in self.passed_rows if s in scope_set])
            n_or = sum(1 for s, r in self.auto_reason.items()
                       if s in scope_set and str(r).startswith("或组都不满足"))
            n_single = max(0, len([s for s in self.auto_reason if s in scope_set
                                   and s not in self.passed_rows]) - n_or)
            html.append(
                "<b>剔除构成</b>：条件不合格 <b>{}</b>"
                "（「或」组整组淘汰 {} ＋ 单条条件 {}）　"
                "「满足条件」只是没被本轮「最终取值」挑中 <b>{}</b>".format(
                    n_or + n_single, n_or, n_single, n_passed))

        # ★ 一条都没保留时，直接点名"最可能的原因"，别让用户对着空表猜
        if n_total and not n_keep:
            worst = ""
            worst_n = 0
            for c in self.conds:
                if not c.enabled:
                    continue
                hit = self.cond_hits.get(c.describe(), 0)
                if hit > worst_n:
                    worst, worst_n = c.describe(), hit
            tip = (f"<b style='color:#b91c1c'>⚠ 全部 {n_total} 条都被条件剔除。</b>"
                   if n_drop == n_total else
                   f"<b style='color:#b91c1c'>⚠ 一条都没保留。</b>")
            if worst:
                tip += (f" 命中最多的是「{worst}」（{worst_n} 条）——"
                        "取消勾选它即可看到数据；也可能是该批数据的仪器设置"
                        "本身就与默认阈值不符（如观测时长设成了 35 s）。")
            html.insert(0, tip)

        # 按测点看剔除分布，前 8 个
        if self.auto_reason:
            cnt: dict[str, int] = {}
            for src, _r in self.auto_reason.items():
                st = self.f.rows[src].by(self.f.columns, C_STATION) or "?"
                cnt[st] = cnt.get(st, 0) + 1
            top = sorted(cnt.items(), key=lambda kv: -kv[1])[:8]
            html.append("<b>剔除最多的测点</b>：" + "　".join(
                f"{k} ×{v}" for k, v in top))

        # 手动筛选的账：人工留 / 人工剔各多少
        mk = [s for s in self.manual_keep if s in set(self.scope)]
        md = [s for s in self.manual_drop if s in set(self.scope)]
        if mk or md:
            bits = []
            if mk:
                bits.append(f"<span style='color:#0f766e'>人工保留 {len(mk)} 条</span>")
            if md:
                bits.append(f"<span style='color:#b91c1c'>人工剔除 {len(md)} 条</span>")
            html.append("<b>手动筛选</b>：" + "　".join(bits)
                        + "　（表格里勾选/取消，或右键批量操作；"
                          "「恢复条件结果」可全部撤销）")
        else:
            html.append("<span style='color:#8a8f98'>手动筛选：暂无人工干预；"
                        "在表格里勾选/取消「处理理由」列的复选框即可人工取舍</span>")
        self.txt_summary.setHtml("<br>".join(html))

    # ================================================================== 导出
    def _pick_export_indices(self, which: str) -> list[int]:
        return list(self.scope) if which == "scope" else list(self._keep_rows)

    def export_xlsx(self) -> None:
        if self.f is None or not self.scope:
            QMessageBox.information(self, "提示", "请先载入数据并选择日期 / Survey。")
            return
        # ★ 对话框带出**上次的选择**（记忆）；默认「附 Survey 文件头」是勾上的
        dlg = ExportDialog(len(self.scope), len(self._keep_rows), self,
                           options=self.settings.export_options())
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        which = dlg.which()
        # 把这次的选择记下来（下次打开还是这一套）
        self.settings.remember_export(
            mode=dlg.mode(), which=which, reason=dlg.with_reason(),
            survey_header=dlg.with_survey_header())
        idx = self._pick_export_indices(which)
        if not idx:
            QMessageBox.information(self, "提示", "没有可导出的观测行。")
            return

        svs = self._scope_surveys() or self.f.survey_names()
        date_tag = self._scope_dates()
        date_tag = date_tag[0] if len(date_tag) == 1 else (
            "多日期" if date_tag else "全部日期")
        suggested = exporter.default_name(self.f, date_tag, svs, dlg.mode())
        _last = str(self.settings.get("export/dir") or "")
        if _last and Path(_last).is_dir():
            suggested = str(Path(_last) / Path(suggested).name)
        fp, _ = QFileDialog.getSaveFileName(
            self, "导出 xlsx", suggested, "Excel 工作簿 (*.xlsx)")
        if not fp:
            return
        self.settings.set("export/dir", str(Path(fp).parent))
        self.settings.flush()

        reasons = None
        if dlg.with_reason():
            reasons = [self.auto_reason.get(
                s, "最终取值" if s in self.picked_rows else "满足条件") for s in idx]
        try:
            out = exporter.export_xlsx(
                self.f, idx, self.colorder, fp,
                mode=dlg.mode(), include_reason=dlg.with_reason(), reasons=reasons,
                include_survey_header=dlg.with_survey_header())
        except Exception as exc:                      # noqa: BLE001
            QMessageBox.warning(self, "导出失败", str(exc))
            return
        self.statusBar().showMessage(f"已导出 {len(idx)} 条观测：{out}", 10000)
        QMessageBox.information(
            self, "导出完成",
            f"已写出 {len(idx)} 条观测。\n\n{out}\n\n"
            f"格式：{'原始数据格式' if dlg.mode() == 'verbatim' else '自定义列序'}"
            f"　内容：{'范围内全部' if which == 'scope' else '仅保留'}")

    def copy_to_clipboard(self) -> None:
        """复制表格内容为制表符文本（可直接粘进 Excel）。

        ★ 三处按用户要求改过：
          1. **列与表格里看到的完全一致** —— 包括最前面的「☑」和「处理理由」。
             原来走 `colorder.copy_columns()`，理由列被甩到最后、勾选框列干脆没有；
          2. **有选中的行 → 只复制选中的行**（没选 = 当前全部可见行）；
          3. **整行复制**，不是只复制点到的那一格 —— 表格里按 `Ctrl+C` 走的就是这里。
        """
        if self.f is None or self.model.rowCount() == 0:
            QMessageBox.information(self, "提示", "没有可复制的内容。")
            return
        cols = list(self.model.columns_)
        if not cols:
            return
        sm = self.table.selectionModel()
        sel_view = sorted({i.row() for i in sm.selectedRows()}) if sm else []
        view_rows = sel_view or list(range(self.proxy.rowCount()))
        lines = ["\t".join(
            str(self.model.headerData(c, Qt.Orientation.Horizontal,
                                      Qt.ItemDataRole.DisplayRole) or "")
            for c in range(len(cols)))]
        n = 0
        for vr in view_rows:
            pi = self.proxy.index(vr, 0)
            mr = self.proxy.mapToSource(pi).row() if pi.isValid() else -1
            if mr < 0:
                continue
            vals = []
            for c, name in enumerate(cols):
                idx = self.model.index(mr, c)
                if name == CHK_COL:
                    checked = (self.model.data(idx, Qt.ItemDataRole.CheckStateRole)
                               == Qt.CheckState.Checked)
                    vals.append("☑" if checked else "")
                else:
                    v = self.model.data(idx, Qt.ItemDataRole.DisplayRole)
                    vals.append("" if v is None else str(v))
            lines.append("\t".join(vals))
            n += 1
        QGuiApplication.clipboard().setText("\r\n".join(lines))
        which = f"选中的 {n} 行" if sel_view else f"当前 {n} 行"
        self.statusBar().showMessage(
            f"已复制{which} × {len(cols)} 列到剪贴板"
            f"（列与表格一致，含勾选框/处理理由）", 8000)

    def _copy_selection(self) -> None:
        """右键菜单入口：与 Ctrl+C 同一个动作（有选中就只复制选中的行）。"""
        self.copy_to_clipboard()

    # ================================================================== 列设置
    def open_column_dialog(self) -> None:
        if self.f is None:
            QMessageBox.information(self, "提示", "请先载入数据。")
            return
        dlg = ColumnDialog(self.f.columns,
                           self.colorder.visible(self.f.columns),
                           self.colorder.reason, self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        self.colorder = dlg.result_colorder()
        self._render()
        self.statusBar().showMessage(
            f"列设置已更新：{len(self.colorder.order)} 列"
            + ("（含处理理由）" if self.colorder.reason else ""), 5000)


class _PickKindDialog(QDialog):
    """添加条件时先选条件类型。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("添加筛选条件")
        v = QVBoxLayout(self)
        v.addWidget(QLabel("选择要添加的条件类型："))
        self.lst = QListWidget()
        for kind, meta in COND_KINDS.items():
            it = QListWidgetItem(f"{meta.cn}　—　{meta.desc}")
            it.setData(Qt.ItemDataRole.UserRole, kind)
            it.setToolTip(f"依据：{meta.basis}")
            self.lst.addItem(it)
        self.lst.setCurrentRow(0)
        self.lst.itemDoubleClicked.connect(lambda _i: self.accept())
        v.addWidget(self.lst)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        v.addWidget(bb)

    def kind(self) -> str:
        it = self.lst.currentItem()
        return str(it.data(Qt.ItemDataRole.UserRole)) if it else ""


def _param_text(c: Cond) -> str:
    """参数列显示的文字：**紧凑但完整**（`3 次，≤5 μGal`）。

    条件列已经写了条件名，参数列再重复一遍标签既占宽又没用 —— 用紧凑写法后
    ② 面板不必很宽也能完整显示；完整长写法在单元格 tooltip 里（见 `_refresh_cond_table`）。
    """
    return c.params_brief()


def _names_brief(names, total: int, unit: str) -> str:
    """把一组选中的名称压成一行提示。

    · 空集 → "不限"（该条线不参与筛选）
    · 全选 → "全部 N 天 / N 个"
    · 少量 → 直接列名字（"2025-07-01、2025-06-30"）
    · 很多 → 前两个 + "等 N 个"
    """
    names = list(names)
    if not names:
        return "不限"
    if total > 1 and len(names) == total:
        return f"全部 {total} {unit}"
    if len(names) <= 2:
        return "、".join(names)
    return "、".join(names[:2]) + f" 等 {len(names)} {unit}"


def _ensure_qt_fonts() -> None:
    """PySide6 6.11 起不再自带字体目录，Qt 找不到字体会把中文画成方框。

    在**建 QApplication 之前**把 Qt 的字体目录指到系统字体；
    仅当用户没自己设过 QT_QPA_FONTDIR、且系统字体目录确实存在时才动。
    """
    if os.environ.get("QT_QPA_FONTDIR"):
        return
    fonts = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
    if os.path.isdir(fonts):
        os.environ["QT_QPA_FONTDIR"] = fonts


#: 全局界面字号（用户："所有的字体都加大，大气点"）。Qt 默认只有 9pt。
UI_FONT_PT = 11
#: 首选字体（缺哪个退到下一个；全都没有就用系统默认，不报错）
UI_FONT_CANDIDATES = ("Microsoft YaHei UI", "微软雅黑", "Microsoft YaHei",
                      "Noto Sans CJK SC", "Source Han Sans SC", "SimHei",
                      "SimSun")


def _apply_ui_font(app) -> None:
    """把全局字体调大一号。

    所有控件默认继承 `QApplication` 的字体（含表头、菜单、状态栏、对话框），
    所以一处设置就够；比逐个控件 `setFont` 更不容易漏。
    """
    from PySide6.QtGui import QFont, QFontDatabase

    try:
        families = set(QFontDatabase.families())
    except Exception:                                # noqa: BLE001
        families = set()
    fam = next((f for f in UI_FONT_CANDIDATES if f in families), "")
    f = QFont(fam) if fam else QFont()
    f.setPointSize(UI_FONT_PT)
    app.setFont(f)


def _create_app() -> QApplication:
    """建 QApplication（并统一放大字号）。缺字体目录时 Qt 会往 stderr 打警告 —— 静音它。"""
    from .plots import _quiet_qt_fonts

    _quiet_qt_fonts()
    _ensure_qt_fonts()
    app = QApplication.instance()
    if app is not None:
        _apply_ui_font(app)
        _apply_app_identity(app)
        return app                                    # type: ignore[return-value]
    try:
        fd = sys.stderr.fileno()
    except (AttributeError, OSError, ValueError):
        app = QApplication([])
        _apply_ui_font(app)
        _apply_app_identity(app)
        return app
    saved = os.dup(fd)
    try:
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, fd)
        os.close(devnull)
        app = QApplication([])
    finally:
        os.dup2(saved, fd)
        os.close(saved)
    _apply_ui_font(app)
    _apply_app_identity(app)
    return app


def _apply_app_identity(app: QApplication) -> None:
    """程序名 + **图标**（窗口、任务栏、Alt-Tab 都用它）。

    Windows 上任务栏图标认的是 AppUserModelID —— 不设它，钉到任务栏后会显示
    python.exe 的图标而不是本工具的。
    """
    app.setApplicationName(appinfo.APP_NAME)
    # ★ 不设 `setApplicationDisplayName`：Qt 会把它拼到每个窗口标题后面，
    #   主窗口标题会变成"CG5 数据挑选 — 独立小工具 - CG5Picker — CG5 数据挑选"。
    app.setApplicationVersion(appinfo.version())
    app.setOrganizationName(appinfo.AUTHOR_NAME_EN)
    p = appinfo.icon_path()
    if p is not None:
        ic = QIcon(str(p))
        if not ic.isNull():
            app.setWindowIcon(ic)
    if sys.platform.startswith("win"):
        try:
            import ctypes
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                f"{appinfo.AUTHOR_NAME_EN}.{appinfo.APP_NAME}.{appinfo.version()}")
        except Exception:                                  # noqa: BLE001
            pass


def run(argv: list[str] | None = None) -> int:
    """入口：建 QApplication，显示主窗口；给了文件路径就直接载入。"""
    from .plots import ensure_cjk_font

    argv = list(sys.argv[1:] if argv is None else argv)
    files = [a for a in argv if not a.startswith("-")]
    app = _create_app()
    ensure_cjk_font()
    win = MainWindow()
    win.show()
    if getattr(win, "_want_maximized", False):
        win.showMaximized()          # ★ 默认全屏启动
    if files and Path(files[0]).exists():
        win.load_file(files[0])
    return app.exec()
