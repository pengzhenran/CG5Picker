"""查看原数据 —— 原始手簿预览窗口。

需求："再加一个查看原数据的功能，用一个窗口预览。"
（按钮/菜单上的名字就叫「查看原数据」，比"源文件"更贴现场说法。）

设计要点：
  · **显示原始文件全文**（源行号 + 原文），不做任何解析/格式化 —— 这是"原数据"，
    用来核对解析结果对不对、看看手簿头信息。
  · **与结果表联动**：表格里选中的观测，在预览里把对应源行高亮出来；
    勾着「跟随表格选中」就自动滚到第一条（人工复核时逐条核对用）。
  · 支持查找（关键词 / 上一条 / 下一条），并可"只看命中行"集中看。

★ 用户口径（本轮精简）："第一条、上一条、下一条、末一条 感觉没用" —— 实测
  `第一条/末一条` 功能上等于"连按几次上一条/下一条"，**已删**；`上一条/下一条`
  **只在表格里选中多条观测时**才有意义（单选时四个按钮点了都纹丝不动），
  所以现在**没得跳就置灰**，并在下面写清楚原因，不再"点了没反应、看着像坏了"。
  同理「只看命中行」在没输关键词时是死的 → 置灰 + 提示先输关键词。

行号映射在 `set_file()` 里**一次建好**（源行号 → 视图行号），
选中变化时只做字典查表 + 跳转，不做全量扫描 —— 否则几千行下拖动选择会卡。
"""
from __future__ import annotations

from pathlib import Path
from typing import Iterable, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import (QColor, QFont, QKeySequence, QShortcut,
                           QTextCharFormat, QTextCursor, QTextDocument)
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit,
    QPushButton, QTextEdit, QVBoxLayout,
)

from .cg5 import CG5File

__all__ = ["SourceViewDialog"]

_BG_SELECT = QColor("#fff3bf")      # 选中观测的源行底色
_BG_FIND = QColor("#ffe08a")        # 查找命中底色


class SourceViewDialog(QDialog):
    """原始手簿预览（非模态，可与主窗口同时操作）。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("查看原数据 —— CG-5 原始手簿")
        self.resize(1000, 760)
        self.setSizeGripEnabled(True)

        self._f: CG5File | None = None
        self._row_of_line: dict[int, int] = {}      # 源行号 → 编辑器块号
        self._selected: list[int] = []              # 当前选中观测的源行号（升序）
        self._cursor = -1                           # 正在看第几条
        self._suppress = False
        self._find_msg = ""                         # 「找到「x」」这类提示
        self._filter_note = ""                      # 「只看命中：5 / 4010 行」

        v = QVBoxLayout(self)

        # ---------------- 顶部：文件信息 + 跟随开关 ----------------
        top = QHBoxLayout()
        self.lbl_info = QLabel("—")
        self.lbl_info.setWordWrap(True)
        top.addWidget(self.lbl_info, 1)

        self.chk_follow = QCheckBox("跟随表格选中")
        self.chk_follow.setChecked(True)
        self.chk_follow.setToolTip(
            "勾上：结果表里点哪一行，本窗口就自动滚到对应的源行并高亮\n"
            "（这就是这个窗口的主要用法 —— 逐条核对原文）")
        top.addWidget(self.chk_follow)
        v.addLayout(top)

        # ---------------- 查找条 ----------------
        bar = QHBoxLayout()
        bar.addWidget(QLabel("查找"))
        self.ed_find = QLineEdit()
        self.ed_find.setPlaceholderText(
            "输入关键词，如点号、Survey 名、日期…（回车 = 下一个，Esc = 清空）")
        self.ed_find.returnPressed.connect(lambda: self.find_next(+1))
        self.ed_find.textChanged.connect(lambda _t: self._update_find_state())
        bar.addWidget(self.ed_find, 1)
        for text, fn in (("下一个", lambda: self.find_next(+1)),
                         ("上一个", lambda: self.find_next(-1)),
                         ("清空", self.clear_find)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            bar.addWidget(b)
        self.chk_only_hits = QCheckBox("只看命中行")
        self.chk_only_hits.toggled.connect(lambda _b: self.reload())
        bar.addWidget(self.chk_only_hits)
        v.addLayout(bar)
        # Esc 在查找框里 = 清空（不关闭窗口；QDialog 默认 Esc 会 reject）
        _esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self.ed_find)
        _esc.setContext(Qt.ShortcutContext.WidgetShortcut)
        _esc.activated.connect(self.clear_find)
        self._update_find_state()

        # ---------------- 正文 ----------------
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        # 等宽字体 + 行号靠左对齐，几千行也不串位
        mono = QFont("Consolas")
        mono.setStyleHint(QFont.StyleHint.Monospace)
        mono.setPointSize(11)          # 跟全局字号一起放大（原来是 9）
        self.view.setFont(mono)
        self.view.setTabStopDistance(40)
        v.addWidget(self.view, 1)

        # ---------------- 底部：选中跳转 ----------------
        # ★ 用户口径（本轮）："第一条 / 末一条" 功能上等于连按几次上一条/下一条 → 删；
        #   "上一条 / 下一条" 只在**表格里选中多条**时才有意义 → 没得跳就置灰。
        bottom = QHBoxLayout()
        self.lbl_sel = QLabel("未选中观测")
        bottom.addWidget(self.lbl_sel, 1)
        self.btn_prev = QPushButton("◀ 上一条")
        self.btn_prev.setToolTip(
            "在**表格里选中的多条观测**之间往回走\n"
            "（表格里用 Ctrl / Shift 点行可以多选；只选了一条就没什么可跳的）")
        self.btn_prev.clicked.connect(lambda: self.goto_selected(self._cursor - 1))
        bottom.addWidget(self.btn_prev)
        self.btn_next = QPushButton("下一条 ▶")
        self.btn_next.setToolTip(self.btn_prev.toolTip())
        self.btn_next.clicked.connect(lambda: self.goto_selected(self._cursor + 1))
        bottom.addWidget(self.btn_next)
        b_close = QPushButton("关闭")
        b_close.clicked.connect(self.close)
        bottom.addWidget(b_close)
        v.addLayout(bottom)
        self._update_nav_state()

    # ================================================================== 状态
    def _sel_text(self) -> str:
        """左下角那句话：说清楚"现在在第几条"，以及为什么跳不动。"""
        n = len(self._selected)
        if not n:
            return "未选中观测"
        i = self._cursor if 0 <= self._cursor < n else 0
        if n == 1:
            return (f"已选中 1 条观测（源行 {self._selected[0]}）"
                    "　—　表格里 Ctrl/Shift 多选后可逐条走")
        return f"第 {i + 1} / {n} 条　源行 {self._selected[i]}"

    def _refresh_label(self) -> None:
        parts = [p for p in (self._find_msg, self._filter_note, self._sel_text()) if p]
        self.lbl_sel.setText("　｜　".join(parts))

    def _update_nav_state(self) -> None:
        """上/下一条可用性：**只有选中 ≥2 条、且不在两端**时才可点。

        （实测：只选中 1 条时四个跳转按钮点了都不动 —— 与其静默无效让人以为坏了，
          不如直接置灰，并在下面写清楚原因。）
        """
        n, i = len(self._selected), self._cursor
        self.btn_prev.setEnabled(n > 1 and i > 0)
        self.btn_next.setEnabled(n > 1 and 0 <= i < n - 1)
        self._refresh_label()

    def _update_find_state(self) -> None:
        """「只看命中行」必须有关键词才有意义 → 没输关键词时置灰并提示。"""
        has = bool(self.ed_find.text().strip())
        self.chk_only_hits.setEnabled(has)
        self.chk_only_hits.setToolTip(
            "只显示包含该关键词的行，便于集中看" if has
            else "先在左边输入关键词，这个开关才有意义")
        if not has and self.chk_only_hits.isChecked():
            self.chk_only_hits.setChecked(False)     # 会触发 reload()

    # ================================================================== 装载
    def set_file(self, f: CG5File | None) -> None:
        """载入一个手簿（全文 + 建行号映射）。"""
        self._f = f
        self._selected, self._cursor = [], -1
        self._find_msg, self._filter_note = "", ""
        if f is None:
            self.lbl_info.setText("尚未载入文件")
            self.view.setPlainText("")
            self._update_nav_state()
            return
        name = Path(f.path).name if f.path else "（未命名）"
        self.lbl_info.setText(
            f"<b>{name}</b>　共 {len(f.raw_lines)} 行　观测 {len(f.rows)} 条　"
            f"日期 {len(f.dates)} 天　Survey {len(f.survey_names())} 个　"
            f"仪器 S/N {f.rows[0].sn or '—'}　潮汐改正 {f.tide_correction or '—'}"
            f"<br><span style='color:#6b7280'>{f.path}</span>")
        self.clear_find()
        self.reload()

    def reload(self) -> None:
        """按"只看命中行"重画正文，并重建行号映射。"""
        f = self._f
        if f is None:
            return
        key = self.ed_find.text().strip()
        only = self.chk_only_hits.isChecked() and bool(key)
        self._row_of_line = {}
        parts: list[str] = []
        for i, raw in enumerate(f.raw_lines, start=1):
            if only and key and key.lower() not in raw.lower():
                continue
            self._row_of_line[i] = len(parts)
            parts.append(f"{i:>6}  {raw.rstrip()}")
        self.view.setPlainText("\n".join(parts))
        self.apply_highlights()
        self._filter_note = (f"只看命中：{len(parts)} / {len(f.raw_lines)} 行"
                             if only else "")
        self._refresh_label()

    # ================================================================== 高亮
    def apply_highlights(self) -> None:
        """重画底色：选中的观测行（黄）与查找命中（淡黄）。"""
        if self._f is None:
            return
        self._suppress = True
        try:
            extra = []
            for line in self._selected:
                blk = self._row_of_line.get(line)
                if blk is None:
                    continue
                sel = QTextEdit.ExtraSelection()
                fmt = QTextCharFormat()
                fmt.setBackground(_BG_SELECT)
                sel.format = fmt
                cur = QTextCursor(self.view.document().findBlockByNumber(blk))
                cur.select(QTextCursor.SelectionType.LineUnderCursor)
                sel.cursor = cur
                extra.append(sel)
            self.view.setExtraSelections(extra)
        finally:
            self._suppress = False

    # ================================================================== 联动
    def set_selected_rows(self, lines: Iterable[int]) -> None:
        """结果表选中了哪些观测（源行号）→ 高亮并跳到第一条。"""
        srcs = sorted({int(x) for x in lines})
        changed = srcs != self._selected
        self._selected = srcs
        if changed:
            self._cursor = 0 if srcs else -1
        if not srcs:
            self.apply_highlights()
            self._update_nav_state()
            return
        self.apply_highlights()
        if changed and self.chk_follow.isChecked():
            self.goto_selected(0)
        else:
            self._update_nav_state()

    def goto_selected(self, i: int) -> None:
        """跳到选中观测里的第 i 条（边界自动收拢）。"""
        if not self._selected:
            self._update_nav_state()
            return
        i = max(0, min(i, len(self._selected) - 1))
        self._cursor = i
        line = self._selected[i]
        blk = self._row_of_line.get(line)
        if blk is None:
            # 该行被"只看命中行"过滤掉了 → 自动关掉过滤再跳
            if self.chk_only_hits.isChecked():
                self.chk_only_hits.setChecked(False)
                self.reload()
                blk = self._row_of_line.get(line)
            if blk is None:
                self._update_nav_state()
                return
        cur = QTextCursor(self.view.document().findBlockByNumber(blk))
        self.view.setTextCursor(cur)
        self.view.centerCursor()
        self._update_nav_state()

    # ================================================================== 查找
    def find_next(self, direction: int) -> None:
        """在正文里查找关键词；到末尾自动回绕。

        ★ 用 `QTextDocument.FindFlag`，不是 `QTextEdit.FindFlag` ——
          后者在 PySide6 里**不存在**，写错会直接 AttributeError（实测踩过）。
        """
        key = self.ed_find.text().strip()
        if not key:
            return
        flags = (QTextDocument.FindFlag.FindBackward if direction < 0
                 else QTextDocument.FindFlag(0))
        if not self.view.find(key, flags):
            # 回绕到另一端再试一次
            cur = self.view.textCursor()
            cur.movePosition(QTextCursor.MoveOperation.End if direction < 0
                             else QTextCursor.MoveOperation.Start)
            self.view.setTextCursor(cur)
            if not self.view.find(key, flags):
                self._find_msg = f"未找到「{key}」"
                self._refresh_label()
                return
        self._find_msg = f"找到「{key}」"
        self._refresh_label()

    def clear_find(self) -> None:
        self.ed_find.clear()
        self._find_msg = ""
        if self.chk_only_hits.isChecked():
            self.chk_only_hits.setChecked(False)
        if self._f is not None:
            self.reload()
