"""观测表模型 —— 大表格必须用 model/view，否则每次勾选都要重建几千个 item。

"处理理由"列直接写在模型里（而不是另开模型），这样列顺序可任意拖动、
排序也不丢数据。所有"保留 / 条件剔除 / 人工剔除"的判定只在
`MainWindow` 里算一次，模型只负责展示与勾选事件回传。
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QFont

from .cg5 import CG5File
from .colorder import REASON_COL
from .display import format_id_cell

__all__ = ["ObsTableModel", "CHK_COL"]

#: 勾选框列（不属于原始文件列）—— 永远排在表格第一列，且**不参与排序**
CHK_COL = "☑"

#: 需要做"整数去零 / 小数保留"显示的编号类列
_ID_COLS = ("线号", "点号")

#: 按**数值**排序的列（其余按文本排）。编号列也按数值排，`10` 才会排在 `9` 后面。
_NUM_COLS = (
    "线号", "点号", "高程(m)", "读数(mGal)", "标准差(mGal)",
    "倾斜X(arcsec)", "倾斜Y(arcsec)", "温度(℃)", "仪器潮汐改正值(mGal)",
    "观测时长(s)", "REJ", "十进制时间", "地形改正值(mGal)",
)

__all__ = ["ObsTableModel"]

#: 按测点分组的行底纹（两个浅色交替，只用来区分"不同测点"）
C_BAND_A = QColor("#ffffff")
C_BAND_B = QColor("#eef3fa")
#: 打勾（保留）的行：**淡黄底**。仍然是两个色交替 —— 用户要的是"一眼看出哪些
#: 是挑出来的"，同时保留"相邻测点换色"的分组信息（整批同一个黄会让相邻测点糊成
#: 一片，等于把之前那条需求做废）。
C_KEEP_BG_A = QColor("#fff6c2")
C_KEEP_BG_B = QColor("#f7e79a")
#: 表格里**被点击选中**的行：亮黄高亮（在 `window.py` 里设进视图调色板的
#: Highlight / HighlightedText）。比打勾的淡黄更饱和，所以"当前定位在哪一行"
#: 一眼可辨；字色用近黑，压在亮黄上对比度足够。
C_SEL_BG = QColor("#ffc400")
C_SEL_TEXT = QColor("#101418")
#: 打勾（保留）的行：文字换色 + 加粗
C_CHECKED_TEXT = QColor("#0b4f9e")
#: "满足条件、但没被最终取值挑中"的行：处理理由写「满足条件」，用**青色**区别于
#: 真正的剔除理由（琥珀 C_REASON / 红 C_DROP）—— 它只是没被选为最终取值，不算被剔除。
C_PASSED = QColor("#0f766e")

C_KEEP = QColor("#1a7f37")
C_DROP = QColor("#b91c1c")
C_OUT = QColor("#6b7280")
C_HINT = QColor("#8a8f98")
C_REASON = QColor("#b45309")


class ObsTableModel(QAbstractTableModel):
    """结果表：`(文件, 源行号)` 是每一行的唯一身份。"""

    checkToggled = Signal(int, bool)          # 源行号, 是否勾选

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._f: CG5File | None = None
        self._idx: list[int] = []
        self._cols: list[str] = []
        self._pos: dict[str, int] = {}
        self._in_scope = np.zeros(0, dtype=bool)
        self._keep = np.zeros(0, dtype=bool)
        self._manual = np.zeros(0, dtype=bool)
        self._reason: list[str] = []
        #: 每行所属**测点分组**的序号（相邻组交替取 0/1 做底纹）
        self._band: list[int] = []
        self._band_font = QFont()
        self._band_font.setBold(True)
        #: 表头提示（列名 → 文字）。勾选框/理由列由窗口填"不参与排序"之类说明。
        self.header_tips: dict[str, str] = {}

    # ---------------------------------------------------------------- 装数据
    def set_data(self, f: CG5File | None, idx, cols, in_scope, keep, manual,
                 reason, picked=None, passed=None) -> None:
        self.beginResetModel()
        self._f = f
        self._idx = list(idx)
        self._cols = list(cols)
        self._pos = {c: i for i, c in enumerate(f.columns)} if f is not None else {}
        self._in_scope = np.asarray(in_scope, dtype=bool)
        self._keep = np.asarray(keep, dtype=bool)
        self._manual = np.asarray(manual, dtype=bool)
        self._reason = list(reason)
        #: 被「最终取值」挑中的行（处理理由写「最终取值」）
        self._picked = (np.zeros(len(self._idx), dtype=bool) if picked is None
                        else np.asarray(picked, dtype=bool))
        #: 通过了条件、只是没被最终取值挑中的行（处理理由写「满足条件」，另用颜色）
        self._passed = (np.zeros(len(self._idx), dtype=bool) if passed is None
                        else np.asarray(passed, dtype=bool))
        self._band = self._compute_bands(f)
        self.endResetModel()

    def _compute_bands(self, f: CG5File | None) -> list[int]:
        """按「线号+点号」给连续行分组，相邻组交替 0 / 1（用于行底纹）。

        注意分的是**当前表里连续的行**（视图顺序），不是整个文件 ——
        底纹是为了让用户看清"屏幕上这几行属于同一个测点"。
        """
        if f is None or not self._idx:
            return []
        line_i = f.columns.index("线号") if "线号" in f.columns else -1
        st_i = f.columns.index("点号") if "点号" in f.columns else -1
        out: list[int] = []
        band = 0
        prev: tuple[str, str] | None = None
        for src in self._idx:
            cells = f.rows[src].cells
            key = ((cells[line_i] if 0 <= line_i < len(cells) else ""),
                   (cells[st_i] if 0 <= st_i < len(cells) else ""))
            if prev is not None and key != prev:
                band ^= 1                        # 换测点就换底色（只有两个色）
            prev = key
            out.append(band)
        return out

    @property
    def columns_(self) -> list[str]:
        return list(self._cols)

    def source_row(self, view_row: int) -> int:
        """视图行号 → 源文件行号（越界返回 -1）。"""
        return self._idx[view_row] if 0 <= view_row < len(self._idx) else -1

    def view_row_of(self, source_row: int) -> int:
        try:
            return self._idx.index(source_row)
        except ValueError:
            return -1

    def view_row_map(self) -> dict[int, int]:
        """`{源行号: 视图行号}` —— 供框选/高亮批量反查。"""
        return {src: i for i, src in enumerate(self._idx)}

    # ---------------------------------------------------------------- 表格接口
    def rowCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._idx)

    def columnCount(self, parent=QModelIndex()) -> int:
        return 0 if parent.isValid() else len(self._cols)

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if orientation != Qt.Orientation.Horizontal:
            return "" if role == Qt.ItemDataRole.DisplayRole else None
        if role == Qt.ItemDataRole.DisplayRole and 0 <= section < len(self._cols):
            return self._cols[section]
        if role == Qt.ItemDataRole.ToolTipRole and 0 <= section < len(self._cols):
            name = self._cols[section]
            if name in self.header_tips:
                return self.header_tips[name]
            if name == CHK_COL:
                return "勾选框：勾上=保留、取消=剔除；此列不参与排序"
            if name == REASON_COL:
                return "被哪条勾选条件剔除；手工改过的会标注（人工）；此列不参与排序"
            if self._f is not None:
                i = self._f.columns.index(name) if name in self._f.columns else -1
                if 0 <= i < len(self._f.colsource):
                    return f"原始列名：{self._f.colsource[i]}"
            return name
        return None

    def data(self, index: QModelIndex, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid():
            return None
        r, c = index.row(), index.column()
        f = self._f
        if f is None or not (0 <= r < len(self._idx)) or not (0 <= c < len(self._cols)):
            return None

        col = self._cols[c]
        # ★ 勾选框独立成列：勾上 = 保留（人工取舍也在这里体现）
        if role == Qt.ItemDataRole.CheckStateRole and col == CHK_COL:
            return (Qt.CheckState.Checked if self._keep[r]
                    else Qt.CheckState.Unchecked)

        if col == CHK_COL:
            if role == Qt.ItemDataRole.ToolTipRole:
                if not self._in_scope[r]:
                    return "范围外"
                if self._keep[r]:
                    return ("人工保留（已复核）" if self._manual[r]
                            else "条件判定：保留")
                return ((self._reason[r] or "人工剔除")
                        + ("（人工复核）" if self._manual[r] else ""))
            if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole):
                return ""
            return None

        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.EditRole,
                    Qt.ItemDataRole.ToolTipRole):
            if col == REASON_COL:
                txt = self._reason[r] or ""
                if self._manual[r]:
                    txt = (txt + "（人工复核）") if txt else "人工剔除"
                if role == Qt.ItemDataRole.DisplayRole:
                    if not self._in_scope[r]:
                        return "范围外"
                    if self._keep[r]:
                        # ★ 满足（筛选）条件的行写「满足条件」；
                        #   其中被「最终取值」挑中的那一条写「最终取值」
                        if (r < len(self._picked) and self._picked[r]
                                and not self._manual[r]):
                            return "最终取值"
                        return ("满足条件" if not self._manual[r]
                                else "满足条件（人工复核）")
                    if r < len(self._passed) and self._passed[r]:
                        # ★ 通过了条件、只是没被最终取值挑中：也写「满足条件」
                        #   （用另一种字体颜色，见 ForegroundRole —— 它不算"被剔除"）
                        return "满足条件"
                    return txt or "—"
                if r < len(self._passed) and self._passed[r] and not self._manual[r]:
                    return "满足条件"
                return txt or ("满足条件" if self._keep[r] else "剔除")
            src = self._idx[r]
            i = self._pos.get(col, -1)
            cells = f.rows[src].cells
            raw = cells[i] if 0 <= i < len(cells) else ""
            if role == Qt.ItemDataRole.ToolTipRole:
                if col in _ID_COLS and raw != format_id_cell(raw):
                    return f"原文：{raw}\n（显示时按整数去零；含小数则原样保留）"
                return raw or None
            if col in _ID_COLS:
                return format_id_cell(raw)          # ★ 线号/点号：整数去零
            return raw

        if role == Qt.ItemDataRole.ForegroundRole and col in (REASON_COL, CHK_COL):
            if not self._in_scope[r]:
                return QBrush(C_OUT)
            if col == CHK_COL:
                return None
            if not self._keep[r]:
                # ★ "满足条件、但没被最终取值挑中"的行用**另一种颜色** ——
                #   它不是被剔除，别和真正的剔除理由（琥珀/红）混在一起
                if r < len(self._passed) and self._passed[r] and not self._manual[r]:
                    return QBrush(C_PASSED)
                return QBrush(C_REASON if not self._manual[r] else C_DROP)
            return None

        # ★ 行底纹：**打勾（保留）的行铺淡黄**（两个黄交替，保留"相邻测点换色"），
        #   其余行仍按测点分组的白/浅蓝交替。
        if role == Qt.ItemDataRole.BackgroundRole:
            if not (0 <= r < len(self._band)):
                return None
            if self._in_scope[r] and self._keep[r]:
                return QBrush(C_KEEP_BG_A if self._band[r] == 0 else C_KEEP_BG_B)
            return QBrush(C_BAND_A if self._band[r] == 0 else C_BAND_B)

        # ★ 打勾（保留）的行：文字换色并加粗；范围外的行仍然转灰
        if role == Qt.ItemDataRole.ForegroundRole:
            if not self._in_scope[r]:
                return QBrush(C_OUT)
            if self._keep[r] and col != REASON_COL:
                return QBrush(C_CHECKED_TEXT)

        if role == Qt.ItemDataRole.FontRole:
            if not self._in_scope[r]:
                return None
            if self._keep[r]:
                return self._band_font                # 勾选行加粗
            if col in (REASON_COL, CHK_COL):
                fnt = QFont()
                fnt.setBold(True)
                return fnt
            return None

        if role == Qt.ItemDataRole.ForegroundRole and not self._in_scope[r]:
            return QBrush(C_OUT)                       # 范围外整行转灰

        if role == Qt.ItemDataRole.TextAlignmentRole:
            if col == CHK_COL:
                return int(Qt.AlignmentFlag.AlignCenter)
            if col == REASON_COL:
                return int(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            return None

        if role == Qt.ItemDataRole.UserRole:
            return self._idx[r]                        # 排序/定位用源行号
        return None

    def flags(self, index: QModelIndex):
        base = super().flags(index)
        if (index.isValid() and 0 <= index.column() < len(self._cols)
                and self._cols[index.column()] == CHK_COL):
            return base | Qt.ItemFlag.ItemIsUserCheckable
        return base

    def setData(self, index: QModelIndex, value, role=Qt.ItemDataRole.EditRole) -> bool:
        if (role == Qt.ItemDataRole.CheckStateRole and index.isValid()
                and self._cols[index.column()] == CHK_COL):
            src = self._idx[index.row()]
            checked = (Qt.CheckState(value) == Qt.CheckState.Checked)
            self.checkToggled.emit(src, checked)
            return True
        return False

    # ---------------------------------------------------------------- 排序键
    def sort_key(self, row: int, column: int):
        """给排序代理用的原始键：数值列给 float，其余给文本（编号列给小写文本）。

        为什么不用 `DisplayRole`：显示层做过格式化（`0.0000000`→`0`、理由拼接），
        拿显示文本排序会串味；这里直接取**原始单元格**，数值列转 float。
        """
        if not (0 <= row < len(self._idx)) or not (0 <= column < len(self._cols)):
            return ""
        col = self._cols[column]
        if col == CHK_COL:
            return 1 if self._keep[row] else 0
        if col == REASON_COL:
            return self._reason[row] or ""
        f = self._f
        pos = self._pos.get(col, -1)
        if f is None or pos < 0:
            return ""
        cells = f.rows[self._idx[row]].cells
        raw = cells[pos] if pos < len(cells) else ""
        if col in _NUM_COLS:
            try:
                return float(raw)
            except (TypeError, ValueError):
                return float("nan")
        if col in _ID_COLS:
            return format_id_cell(raw).lower()      # `1A` 与 `1a` 排一起
        return raw.lower()
