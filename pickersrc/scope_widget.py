"""范围选择 —— **先选一条主线（日期 / Survey），另一条线在右侧自动跟随**。

设计（按用户口径）：
  · **第一步先决定"按日期"还是"按 Survey"**（左上角两个单选）；
  · **横向两块**：左边 = 主线（全部可选），右边 = 与左选对应的另一条线；
      - 按日期   → 右边是这些天上出现过的 **Survey，默认全选**；
      - 按 Survey → 右边是这些 Survey 出现过的 **日期，默认只勾最新一天**；
  · **默认**：按日期、最新一天（右边自然是那天的 Survey）。
  · 右侧列表的条数按**左侧勾选**统计（不是整个文件的条数），所以不会再出现
    "Survey 914（3650 条）"这种跟当前日期对不上的数字。
  · 筛选语义仍是 `CG5File.filter_scope`：两条线取交集；某条线一个都没勾 = 该线不筛选
    （于是"主线清空"= 整份文件）。

纯界面组件；解析与筛选语义在 `cg5.py`，便于无 GUI 单测。
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QGroupBox, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QRadioButton, QVBoxLayout,
    QWidget,
)

__all__ = ["ScopeWidget", "DATE_ROLE", "MODE_DATE", "MODE_SURVEY"]

#: 列表项里存"干净的值"（日期串 / Survey 名）的角色
DATE_ROLE = Qt.ItemDataRole.UserRole
MODE_DATE = "date"
MODE_SURVEY = "survey"


def _latlon_text(info: dict) -> str:
    """Survey 头里的经纬度 → `37.4000N 106.6000E`（缺了就返回空串）。"""
    la, lo = info.get("latitude"), info.get("longitude")
    if la is None or lo is None:
        return ""
    ns = "N" if float(la) >= 0 else "S"
    ew = "E" if float(lo) >= 0 else "W"
    return f"{abs(float(la)):.4f}{ns} {abs(float(lo)):.4f}{ew}"


class _CheckList(QWidget):
    """带标题与 `全选 / 清空` 的复选列表。"""

    changed = Signal()

    def __init__(self, title: str, parent=None) -> None:
        super().__init__(parent)
        self._loading = False

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(2)

        head = QHBoxLayout()
        head.setSpacing(4)
        self.lbl = QLabel(f"<b>{title}</b>")
        head.addWidget(self.lbl)
        head.addStretch(1)
        b_all = QPushButton("全选")
        b_all.setToolTip(f"{title}：全部勾上")
        b_all.clicked.connect(lambda: self.set_all(True))
        head.addWidget(b_all)
        b_none = QPushButton("清空")
        b_none.setToolTip(f"{title}：全部取消勾选（= 这条线不参与筛选）")
        b_none.clicked.connect(lambda: self.set_all(False))
        head.addWidget(b_none)
        v.addLayout(head)

        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self.list.setMinimumHeight(88)
        self.list.setMaximumHeight(126)
        self.list.itemChanged.connect(self._on_item_changed)
        v.addWidget(self.list)

    def set_title(self, text: str) -> None:
        self.lbl.setText(f"<b>{text}</b>")

    # ------------------------------------------------------------------ 填充
    def fill(self, items: list[tuple[str, str]], *, checked: bool = True) -> None:
        """`items` 为 `[(值, 显示文字), ...]`；`checked=True` 时全勾上。"""
        self._loading = True
        self.list.clear()
        for value, text in items:
            it = QListWidgetItem(text)
            it.setFlags(it.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            it.setCheckState(Qt.CheckState.Checked if checked
                             else Qt.CheckState.Unchecked)
            it.setData(DATE_ROLE, value)
            self.list.addItem(it)
        self._loading = False
        self.changed.emit()

    # ------------------------------------------------------------------ 读写
    def values(self) -> list[str]:
        """已勾选的值，保持列表顺序。"""
        out = []
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.checkState() == Qt.CheckState.Checked:
                out.append(str(it.data(DATE_ROLE)))
        return out

    def set_values(self, values) -> None:
        want = set(values)
        self._loading = True
        for i in range(self.list.count()):
            it = self.list.item(i)
            it.setCheckState(Qt.CheckState.Checked if it.data(DATE_ROLE) in want
                             else Qt.CheckState.Unchecked)
        self._loading = False
        self.changed.emit()

    def set_all(self, checked: bool) -> None:
        self._loading = True
        for i in range(self.list.count()):
            self.list.item(i).setCheckState(
                Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        self._loading = False
        self.changed.emit()

    def count(self) -> int:
        return self.list.count()

    def values_all(self) -> list[str]:
        return [str(self.list.item(i).data(DATE_ROLE))
                for i in range(self.list.count())]

    # ------------------------------------------------------------------ 交互
    def _on_item_changed(self, _it: QListWidgetItem) -> None:
        if not self._loading:
            self.changed.emit()


class ScopeWidget(QGroupBox):
    """① 范围：主线（左）+ 跟随线（右）。

    `dates` / `surveys` 两个列表对象**始终**分别代表日期与 Survey，
    只是左右位置随模式互换 —— 于是"按日期"与"按 Survey"共用同一套读写接口。
    """

    changed = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__("① 范围", parent)
        self.setToolTip(
            "第一步先选一条**主线**：按日期、或按 Survey。\n"
            "左边是主线（可多选），右边自动列出与之对应的另一条线：\n"
            "　· 按日期　 → 右边是这些天上出现过的 Survey（默认全选）\n"
            "　· 按 Survey → 右边是这些 Survey 出现过的日期（默认只勾最新一天）\n"
            "两条线取交集；某条线一个都不勾 = 这条线不筛选（= 整份文件）。")
        self._loading = False
        self._mode = MODE_DATE
        self._f = None
        self._d2s = lambda *_a: []
        self._s2d = lambda *_a: []

        v = QVBoxLayout(self)
        v.setContentsMargins(8, 6, 8, 6)
        v.setSpacing(4)

        # ---- 第一步：选主线 ----
        head = QHBoxLayout()
        head.setSpacing(6)
        head.addWidget(QLabel("第一步："))
        self.rb_date = QRadioButton("按日期")
        self.rb_date.setToolTip("主线 = 日期：先勾日期，右边自动列出这些天的 Survey")
        self.rb_survey = QRadioButton("按 Survey")
        self.rb_survey.setToolTip(
            "主线 = Survey：先勾 Survey，右边自动列出这些 Survey 的日期（默认最新一天）")
        self.rb_date.setChecked(True)
        grp = QButtonGroup(self)
        grp.addButton(self.rb_date)
        grp.addButton(self.rb_survey)
        self.rb_date.toggled.connect(
            lambda on: on and self.set_mode(MODE_DATE))
        self.rb_survey.toggled.connect(
            lambda on: on and self.set_mode(MODE_SURVEY))
        head.addWidget(self.rb_date)
        head.addWidget(self.rb_survey)
        head.addStretch(1)
        self.lbl = QLabel("—")
        self.lbl.setProperty("title", True)
        head.addWidget(self.lbl)
        v.addLayout(head)

        # ---- 横向两块：主线（左）+ 跟随线（右） ----
        self.dates = _CheckList("日期")
        self.dates.changed.connect(self._on_dates_changed)
        self.surveys = _CheckList("Survey")
        self.surveys.changed.connect(self._on_surveys_changed)
        self.body = QHBoxLayout()
        self.body.setSpacing(8)
        v.addLayout(self.body, 1)
        self._relayout()
        self._retitle()

    # ------------------------------------------------------------------ 注入
    def set_lookup(self, dates_to_surveys, surveys_to_dates) -> None:
        """注入"另一条线"的取值函数（来自 `CG5File`）。"""
        self._d2s = dates_to_surveys
        self._s2d = surveys_to_dates

    # ------------------------------------------------------------------ 模式
    def mode(self) -> str:
        return self._mode

    def primary(self) -> _CheckList:
        """主线列表（左）。"""
        return self.dates if self._mode == MODE_DATE else self.surveys

    def secondary(self) -> _CheckList:
        """跟随列表（右）。"""
        return self.surveys if self._mode == MODE_DATE else self.dates

    def set_mode(self, mode: str) -> None:
        """切换主线；新主线回到它自己的默认值（日期=最新一天 / Survey=最新那天的）。"""
        if mode not in (MODE_DATE, MODE_SURVEY) or mode == self._mode:
            return
        self._mode = mode
        self._loading = True
        try:
            self._retitle()
            self._relayout()
            if self._f is not None:
                # ★ 两条列表都要**重建成"全部可选"**：换主线时，新主线在旧模式下
                #   可能是"跟随线"（里面只有被过滤过的那几项），不重填就会出现
                #   "想勾的项根本不在列表里、勾了没反应"（自检抓到的空列表 bug）。
                self.dates.fill(self._date_items(), checked=False)
                self.surveys.fill(self._survey_items(), checked=False)
                self._apply_defaults()
        finally:
            self._loading = False
        self._emit()

    def _retitle(self) -> None:
        if self._mode == MODE_DATE:
            self.dates.set_title("日期（主线）")
            self.surveys.set_title("Survey（跟随日期）")
        else:
            self.surveys.set_title("Survey（主线）")
            self.dates.set_title("日期（跟随 Survey）")

    def _relayout(self) -> None:
        """主线摆左边、跟随线摆右边（横向两块）。"""
        while self.body.count():
            self.body.takeAt(0)
        self.body.addWidget(self.primary(), 1)
        self.body.addWidget(self.secondary(), 1)

    # ------------------------------------------------------------------ 装载
    def load(self, f, *, keep: tuple[list[str], list[str]] | None = None) -> None:
        """按新载入的文件重建两组；`keep` 用于重新载入时保留原勾选（仅按日期模式）。"""
        self._f = f
        self._loading = True
        try:
            if f is None:
                self.dates.fill([])
                self.surveys.fill([])
            else:
                self.dates.fill(self._date_items(), checked=False)
                self.surveys.fill(self._survey_items(), checked=False)
                kept = False
                if keep is not None and self._mode == MODE_DATE and keep[0]:
                    want = [d for d in keep[0] if d in set(f.dates)]
                    if want:
                        self.dates.set_values(want)
                        self.rebuild_secondary()
                        svs = [s for s in (keep[1] or [])
                               if s in set(self.surveys.values_all())]
                        if svs:
                            self.surveys.set_values(svs)
                        kept = True
                if not kept:
                    self._apply_defaults()
        finally:
            self._loading = False
        self._retitle()
        self._relayout()
        self._emit()

    def _apply_defaults(self) -> None:
        """默认：按日期 → 最新一天；按 Survey → 最新那天的 Survey（右边只勾最新一天）。"""
        f = self._f
        if f is None:
            return
        if self._mode == MODE_DATE:
            self.dates.set_values({f.dates[0]} if f.dates else set())
            self.rebuild_secondary()
        else:
            newest = f.dates[0] if f.dates else ""
            svs = set(self._d2s({newest})) or set(f.survey_names()[:1])
            self.surveys.set_values(svs)
            self.rebuild_secondary(all_checked=False)

    def rebuild_secondary(self, *, all_checked: bool | None = None) -> None:
        """按主线勾选重建跟随线。

        `True`  = 全勾（按日期主线）
        `False` = 只勾**最新一项**（按 Survey 主线：用户口径"默认选最新"）
        `None`  = 按模式取默认（日期主线全勾 / Survey 主线最新一项）
        """
        f = self._f
        if f is None:
            return
        if self._mode == MODE_DATE:
            dates = set(self.dates.values())
            order = list(self._d2s(dates)) if dates else []
            items = self._survey_items(limit_dates=dates)
            items = [it for n in order for it in items if it[0] == n]
            self.surveys.fill(items, checked=False)
            if items:
                check = (all_checked is not False)
                self.surveys.set_values({s for s, _ in items} if check
                                        else {items[0][0]})
        else:
            svs = set(self.surveys.values())
            order = list(self._s2d(svs)) if svs else []      # 最新在前
            items = self._date_items(limit_surveys=svs)
            items = [it for n in order for it in items if it[0] == n]
            self.dates.fill(items, checked=False)
            if items:
                # ★ 按 Survey 主线时**默认只勾最新一天**（用户口径）；
                #   只有显式 all_checked=True 才全勾 —— 上一版这里写反了，
                #   一进"按 Survey"就把所有日期全勾上（自检抓到的）。
                self.dates.set_values({d for d, _ in items}
                                      if all_checked is True else {items[0][0]})

    # ------------------------------------------------------------------ 读写
    def selected_dates(self) -> set[str]:
        return set(self.dates.values())

    def selected_surveys(self) -> set[str]:
        return set(self.surveys.values())

    def scope_indices(self, f) -> list[int]:
        """当前范围（源顺序行下标）。两条线都空 → 全部观测。"""
        if f is None:
            return []
        return f.filter_scope(self.selected_dates(), self.selected_surveys())

    def set_summary(self, text: str) -> None:
        self.lbl.setText(text)

    def _emit(self) -> None:
        if not self._loading:
            self.changed.emit()

    # ------------------------------------------------------------------ 跟随
    def _on_dates_changed(self) -> None:
        if self._loading:
            return
        if self._mode != MODE_DATE:
            self._emit()                     # 日期是跟随线：只重算命中
            return
        self._loading = True
        try:
            self.rebuild_secondary(all_checked=True)   # 按日期 → Survey 默认全选
        finally:
            self._loading = False
        self._emit()

    def _on_surveys_changed(self) -> None:
        if self._loading:
            return
        if self._mode != MODE_SURVEY:
            self._emit()
            return
        self._loading = True
        try:
            self.rebuild_secondary(all_checked=False)  # 按 Survey → 日期默认最新一天
        finally:
            self._loading = False
        self._emit()

    # ------------------------------------------------------------------ 列表项
    def _date_items(self, limit_surveys=None) -> list[tuple[str, str]]:
        """日期列表项；给了 `limit_surveys` 时条数只算这些 Survey 的。"""
        f = self._f
        if f is None:
            return []
        cnt = f.date_survey_counts()
        want = None if limit_surveys is None else set(limit_surveys)
        out = []
        for d in f.dates:                                   # 最新在前
            n = sum(v for (dd, ss), v in cnt.items()
                    if dd == d and (want is None or ss in want))
            out.append((d, f"{d}（{n} 条）"))
        return out

    def _survey_items(self, limit_dates=None) -> list[tuple[str, str]]:
        """Survey 列表项；给了 `limit_dates` 时条数只算这些天的。

        用户要求"survey 列表后面加上经纬度的显示" —— 坐标来自各 Survey 头。
        同一文件里不同 Survey 的坐标可以完全不同（实测 914 = 30.5N/114.4E、
        nx914 = 37.4N/106.6E），摆在列表里一眼能看出这一项用的是哪套坐标。
        """
        f = self._f
        if f is None:
            return []
        cnt = f.date_survey_counts()
        want = None if limit_dates is None else set(limit_dates)
        out = []
        for s in f.survey_names():
            n = sum(v for (dd, ss), v in cnt.items()
                    if ss == s and (want is None or dd in want))
            ll = _latlon_text(f.survey_info(s))
            out.append((s, f"{s}（{n} 条）" + (f"　{ll}" if ll else "")))
        return out
