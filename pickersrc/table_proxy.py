"""排序代理 —— 只对**真实数据列**排序，勾选框列与理由列永远不参与排序。

用户要求："处理理由和勾选框要置顶在最前面，排序只对其他列起效。"

Qt 默认的 `QSortFilterProxyModel` 会让表头每一列都可排序，点前两列会把"打勾/不打勾"
的行混在一起，复核时完全没法用。所以这里自己实现：
  · `CHK_COL` / `REASON_COL` → `sort()` 直接忽略（表头也标成不可排）
  · 其余列按**数值**排（能转成 float 的），否则按文本排 —— 避免 `9 > 10` 这类字典序错误

排序键直接取自源模型（`ObsTableModel.sort_key`），不依赖 Qt 的 sortRole 机制，
`QsortFilterProxyModel` 只负责搬行。
"""
from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt

__all__ = ["CHK_COL", "ObsSortProxy", "sortable_columns"]


class ObsSortProxy(QSortFilterProxyModel):
    """按真实列值排序；编号/理由列不排序。"""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._column = -1
        self._order = Qt.SortOrder.AscendingOrder

    # ---------------------------------------------------------------- 接口
    def sort(self, column: int, order: Qt.SortOrder = Qt.SortOrder.AscendingOrder) -> None:
        """忽略不可排序列；其余按源模型给的键排。"""
        if not self.is_sortable(column):
            return                              # 勾选框/理由列：什么都不做
        self._column, self._order = column, order
        super().sort(column, order)

    def is_sortable(self, column: int) -> bool:
        src = self.sourceModel()
        if src is None or not (0 <= column < src.columnCount()):
            return False
        return src.columns_[column] not in _NO_SORT

    # ---------------------------------------------------------------- 比较
    def lessThan(self, left: QModelIndex, right: QModelIndex) -> bool:
        src = self.sourceModel()
        if src is None:
            return super().lessThan(left, right)
        a = src.sort_key(left.row(), left.column())
        b = src.sort_key(right.row(), right.column())
        # 空值永远排在最后（不管升序降序），免得空行挡住数据
        a_empty, b_empty = _is_empty(a), _is_empty(b)
        if a_empty or b_empty:
            if a_empty and b_empty:
                return False
            return b_empty if self._order == Qt.SortOrder.AscendingOrder else a_empty
        try:
            return a < b
        except TypeError:
            return str(a) < str(b)


#: 不参与排序的列：勾选框列（打勾/不打勾混在一起没法复核）与理由列
_NO_SORT = ("☑", "处理理由")


def _is_empty(v) -> bool:
    """空值 = None / 空文本 / **NaN**（数值列解析失败）。

    NaN 必须当空值处理：`nan < x` 恒为 False，否则排序结果非单调，
    表里看着就像"没排干净"。
    """
    if v is None:
        return True
    if isinstance(v, str):
        return not v.strip()
    if isinstance(v, float):
        return v != v
    return False


def sortable_columns(available: list[str], reason: bool = True) -> list[str]:
    """列出可排序列（供调试/自检）。"""
    from .table_model import CHK_COL
    from .colorder import REASON_COL

    out = [CHK_COL] if reason else []
    out += [c for c in available if c != REASON_COL]
    return out
