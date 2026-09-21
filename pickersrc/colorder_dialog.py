"""列设置对话框 —— 勾选要显示的列，并调整顺序。

左侧"可选列"、右侧"显示顺序"。按钮：添加 / 移除 / 上移 / 下移 / 重置默认。
支持在右侧直接拖动行排序。
"""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QCheckBox, QDialog, QDialogButtonBox, QGroupBox,
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QVBoxLayout,
)

from .colorder import ColOrder, default_visible, step

__all__ = ["ColumnDialog"]


class ColumnDialog(QDialog):
    """返回用户设定的列顺序（`result_order()`）与是否附理由列。"""

    def __init__(self, available: list[str], current: list[str],
                 reason: bool = True, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("列设置 —— 显示哪些列、按什么顺序")
        self.resize(720, 520)
        self._available = list(available)

        root = QVBoxLayout(self)
        tip = QLabel("导出的列顺序与此处一致。<b>选中</b>列后点方向按钮或直接拖动可调整顺序。")
        tip.setWordWrap(True)
        root.addWidget(tip)

        body = QHBoxLayout()

        g_left = QGroupBox("可选列（原始文件里全部列）")
        lv = QVBoxLayout(g_left)
        self.left = QListWidget()
        self.left.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.left.itemDoubleClicked.connect(lambda _i: self._add())
        lv.addWidget(self.left)
        body.addWidget(g_left, 1)

        mid = QVBoxLayout()
        mid.addStretch(1)
        for text, fn in (("添加 →", self._add), ("← 移除", self._remove)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            mid.addWidget(b)
        mid.addSpacing(12)
        for text, d in (("上移", -1), ("下移", +1)):
            b = QPushButton(text)
            b.clicked.connect(lambda _c=False, dd=d: self._move(dd))
            mid.addWidget(b)
        mid.addStretch(1)
        body.addLayout(mid)

        g_right = QGroupBox("显示顺序（左→右）")
        rv = QVBoxLayout(g_right)
        self.right = QListWidget()
        self.right.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.right.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.right.itemDoubleClicked.connect(lambda _i: self._remove())
        rv.addWidget(self.right)
        body.addWidget(g_right, 1)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        self.chk_reason = QCheckBox("表格附「处理理由」列")
        self.chk_reason.setChecked(bool(reason))
        self.chk_reason.setToolTip("只影响界面显示；导出时另有开关。")
        bottom.addWidget(self.chk_reason)
        b_default = QPushButton("重置为默认顺序")
        b_default.clicked.connect(self._reset)
        bottom.addWidget(b_default)
        bottom.addStretch(1)

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok
                              | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        bottom.addWidget(bb)
        root.addLayout(bottom)

        self._fill_left()
        self._fill_right(current or default_visible(self._available))
        self._reload_right()

    # ------------------------------------------------------------------ 内部
    def _fill_left(self) -> None:
        for c in self._available:
            it = QListWidgetItem(c)
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.left.addItem(it)

    def _fill_right(self, order: list[str]) -> None:
        self.right.clear()
        for c in order:
            it = QListWidgetItem(c)
            it.setData(Qt.ItemDataRole.UserRole, c)
            self.right.addItem(it)
        self._sync_left()

    def _order(self) -> list[str]:
        return [self.right.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(self.right.count())]

    def _sync_left(self) -> None:
        """可选列里把已选中的项灰掉，避免重复添加。"""
        chosen = set(self._order())
        for i in range(self.left.count()):
            it = self.left.item(i)
            it.setHidden(it.data(Qt.ItemDataRole.UserRole) in chosen)

    def _reload_right(self) -> None:
        self._sync_left()

    def _add(self) -> None:
        for it in self.left.selectedItems():
            name = it.data(Qt.ItemDataRole.UserRole)
            if name not in self._order():
                self.right.addItem(name)
        self._sync_left()

    def _remove(self) -> None:
        for it in self.right.selectedItems():
            self.right.takeItem(self.right.row(it))
        self._sync_left()

    def _move(self, delta: int) -> None:
        rows = sorted({self.right.row(i) for i in self.right.selectedItems()})
        if not rows:
            return
        order = self._order()
        # 从上往下移时先处理靠下的行，避免相互覆盖
        for r in (reversed(rows) if delta > 0 else rows):
            order = step(order, r, delta)
        self._fill_right(order)
        for r in (r + delta for r in rows):
            if 0 <= r < self.right.count():
                self.right.item(r).setSelected(True)

    def _reset(self) -> None:
        self._fill_right(default_visible(self._available))

    # ------------------------------------------------------------------ 结果
    def result_order(self) -> list[str]:
        return self._order()

    def result_reason(self) -> bool:
        return self.chk_reason.isChecked()

    def result_colorder(self) -> ColOrder:
        return ColOrder(order=self._order(), reason=self.chk_reason.isChecked())
