"""导出 —— 按原始数据格式写 xlsx（表头 + 数据，去掉每行开头的空格）。

两种导出格式，**不改动任何数值/精度**，只按列决定单元格类型：

1. **原始格式（verbatim，默认）** —— 一行一条观测，单元格按原始列头**原顺序**排列，
   内容与原始文件一致（`0.0000000`、`7432.742` 原样保留），
   只是去掉了每行开头的空格。这是"原始数据格式导出"的字面实现，
   适合直接替换/归档原始手簿。

2. **自定义列序（parsed）** —— 按界面上设定的**显示列序**输出所选列，
   便于只带出关心的几列；单元格取值规则相同。

两种格式都写：第 1 行 = 表头（原始列头，去掉开头的 `/` 与多余空白），
第 2 行起 = 数据。输出 `.xlsx`（openpyxl，不依赖 pandas）。

单元格类型（用户口径："除了时间和日期，都是文本类型，不方便"）：

| 列 | 写成 | 显示 |
|---|---|---|
| 线号 / 点号 | 去零后是纯数字 → **数值** | 用 `0.0000000` 之类格式**保留原文长度** |
| 高程/读数/标准差/倾斜/温度/潮汐/时长/REJ/十进制时间/地形 | **数值** | Excel 默认（能直接求和、排序） |
| **时刻** | **真时间**（`datetime.time`） | `hh:mm:ss` → 还是 `07:42:01` |
| **日期** | **真日期**（`datetime.date`） | `yyyy/mm/dd` → 还是 `2025/07/02` |
| 其它 | 文本 | 原样 |

> **为什么时刻/日期现在是真日期而不是文本**（用户实测踩到）：写成文本时
> WPS/Excel 会在单元格上打绿三角并提示"该数据未识别为日期，可能影响日期筛选、
> 排序、运算等功能"。改成真日期后**显示完全不变**（靠数字格式），但能筛选、排序、做差。
>
> Survey 文件头（可选写在表格最上面）里的字段也分类型：`Instrument S/N` / `ZONE` /
> `GMT DIFF.` → **数值**，`Date` → **真日期**，`Time` → **真时间**，
> 其余（Survey name / Client / Operator / LONG / LAT）保持**原文文本** ——
> `106.6000000 E` 这种带方向的写法不能被数值化。原始 `.txt` 本身不动，归档仍有逐字原文。
"""
from __future__ import annotations

import datetime as _dt
import re
from pathlib import Path
from typing import Sequence

from .cg5 import SURVEY_KEYS, CG5File
from .colorder import REASON_COL, ColOrder
from .display import format_id_cell, is_numeric_text

__all__ = ["export_xlsx", "verbatim_table", "parsed_table", "default_name",
           "survey_headers"]

_MODE_VERBATIM = "verbatim"
_MODE_PARSED = "parsed"
_KV_RE = re.compile(r"^/\s*([^:]+?)\s*:\s*(.*?)\s*$")

#: 导出时写成**数值**的列（Excel 里能直接算、能排序）；其余写文本。
_NUM_COLS = (
    "高程(m)", "读数(mGal)", "标准差(mGal)", "倾斜X(arcsec)", "倾斜Y(arcsec)",
    "温度(℃)", "仪器潮汐改正值(mGal)", "观测时长(s)", "REJ", "十进制时间",
    "地形改正值(mGal)",
)
#: 编号列：先按显示规范去零（`15.0000000` → `15`），去零后是纯数值就**写数值**
#: 并保留原文的小数位数；含字母/符号的原样文本。
_ID_COLS = ("线号", "点号")
#: 日期列：写**真日期**（`datetime.date` + `yyyy/mm/dd`）。显示与原文同形，
#: 但 Excel/WPS 认它是日期（不再打"该数据未识别为日期"的绿三角）。
_DATE_COLS = ("日期", "DATE")
#: 时刻列：写**真时间**（`datetime.time` + `hh:mm:ss`），`07:42:01` 显示不变。
_TIME_COLS = ("时刻", "TIME")

#: Survey 文件头里**按数值写**的字段（原文 → 数字格式规则见 `_kv_value`）。
#: `Instrument S/N: 41465`、`ZONE: 0`、`GMT DIFF.: -8.0` 原来是文本，Excel 里
#: 既不能排序也不能算，还被打绿三角。
_KV_NUM = ("Instrument S/N", "ZONE", "GMT DIFF.")

_DATE_RE = re.compile(r"^(\d{4})\s*/\s*(\d{1,2})\s*/\s*(\d{1,2})$")
_TIME_RE = re.compile(r"^(\d{1,2}):(\d{1,2}):(\d{1,2})(?:\.\d+)?$")


def _base_col(col: str) -> str:
    """去掉重名列的后缀（`日期#2` → `日期`）。"""
    return col.split("#", 1)[0]


def _date_cell(s: str) -> tuple[_dt.date, str] | None:
    """`2025/07/02`（也容 `2025/ 7/ 1` 这种手簿写法）→ `(date, "yyyy/mm/dd")`。"""
    m = _DATE_RE.match(s)
    if not m:
        return None
    try:
        return _dt.date(int(m.group(1)), int(m.group(2)), int(m.group(3))), "yyyy/mm/dd"
    except ValueError:                       # 13 月 / 32 日之类：原样留着，别崩
        return None


def _time_cell(s: str) -> tuple[_dt.time, str] | None:
    """`07:42:01` → `(time, "hh:mm:ss")`。"""
    m = _TIME_RE.match(s)
    if not m:
        return None
    try:
        return _dt.time(int(m.group(1)), int(m.group(2)), int(m.group(3))), "hh:mm:ss"
    except ValueError:
        return None


def _num_with_len(text: str) -> tuple[float, str]:
    """数值 + **保留原文小数位数**的 Excel 数字格式。

    `12.5000000` → `(12.5, "0.0000000")`：单元格是数值（能算），显示还是原来的长度。
    """
    dec = len(text.split(".", 1)[1]) if "." in text else 0
    return float(text), ("0." + "0" * dec if dec else "0")


def _int_if_plain(text: str):
    """整数字面量 → `int`（`41465` → 整数，不带 `.0`）；否则 None。"""
    if re.fullmatch(r"[+-]?\d+", text):
        return int(text)
    return None


def _kv_value(label: str, value: str):
    """Survey 文件头的一个字段值 → 单元格内容。

    · `Instrument S/N` / `ZONE` / `GMT DIFF.` → **数值**（整数写整数）
    · `Date` → **真日期**、`Time` → **真时间**
    · 其余（Survey name / Client / Operator / LONG / LAT）→ **原文文本**
      —— `106.6000000 E` 这种带方向的写法不能被数值化。

    返回 `(值, 数字格式)` 元组时表示"数值 + 指定显示格式"。
    """
    s = str(value).strip()
    if label in _KV_NUM:
        n = _int_if_plain(s)
        if n is not None:
            return n                            # `41465` / `0` → 整数
        if is_numeric_text(s):
            return _num_with_len(s)             # `-8.0` → 数值 + 保留原文小数位
        return s
    if label == "Date":
        return _date_cell(s) or s
    if label == "Time":
        return _time_cell(s) or s
    return s


def _cell_value(col: str, raw) -> object:
    """按列决定写进单元格的内容。

    · 编号列 → 去零后是纯数值就写**数值**（并保留原长度），否则原样文本；
    · 数值列 → `float`（导出后能直接求和/排序，不再全是文本）；
    · 日期列 → **真日期**（`yyyy/mm/dd` 显示同形，但 Excel 认它是日期）；
    · 时刻列 → **真时间**（`hh:mm:ss` 显示不变）；
    · 其余 → 原样文本。

    返回 `(值, 数字格式)` 元组时表示"数值 + 指定显示格式"。
    """
    s = str(raw).strip()
    base = _base_col(col)
    if base in _ID_COLS:
        t = format_id_cell(s)                  # 整数去零；`1A` / `L-3` 原样
        if t and is_numeric_text(t):
            return _num_with_len(t)            # 纯数字 → 数值，且保留原长度
        return t
    if base in _NUM_COLS:
        if not is_numeric_text(s):
            return s
        return float(s)
    if base in _DATE_COLS:
        return _date_cell(s) or s
    if base in _TIME_COLS:
        return _time_cell(s) or s
    return s


def survey_headers(f: CG5File, idx: Sequence[int]
                   ) -> list[tuple[str, list[tuple[str, str]]]]:
    """这些观测涉及到的 **Survey 文件头**，按文件里出现的先后排列。

    → `[(survey 名, [(原文标签, 原值), …]), …]`

    直接按原始文本行取（标签与原值都是原文），所以 `LONG: 114.4000000 E`
    这种写法不会被改写成十进制数。
    """
    blocks: dict[str, list[tuple[str, str]]] = {}
    cur: str | None = None
    for raw in f.raw_lines:
        st = raw.strip()
        if not st.startswith("/"):
            continue
        if st[1:].strip().upper().startswith("CG-5 SURVEY"):
            cur = None                              # 下一个 "Survey name" 定名
            continue
        m = _KV_RE.match(st)
        if not m:
            cur = None                              # 进到别的段（SETUP / OPTIONS）
            continue
        key, val = m.group(1).strip(), m.group(2).strip()
        if key not in SURVEY_KEYS:
            continue
        if SURVEY_KEYS[key] == "survey":
            cur = val
            # 「Survey name」这一行本身也要进块（它让块自解释是哪个 Survey）
            blocks.setdefault(cur, [(key, val)])
            continue
        if cur is not None:
            blocks[cur].append((key, val))

    wanted: list[str] = []
    for i in idx:
        s = f.rows[i].survey
        if s and s in blocks and s not in wanted:
            wanted.append(s)
    return [(s, blocks[s]) for s in wanted]


def _clean_header(f: CG5File) -> str:
    """原始列头行 → 去开头 `/`、去掉多余空白后的表头。"""
    return " ".join((f.header or "").split())


def verbatim_table(f: CG5File, idx: Sequence[int]) -> tuple[str, list[list[str]]]:
    """原始格式：表头 + 每行的原始单元格（原列序、原文内容）。"""
    head = " ".join(f.colsource) or _clean_header(f)
    body = [[c for c in f.rows[i].cells] for i in idx]
    return head, body


def parsed_table(f: CG5File, idx: Sequence[int],
                 colorder: ColOrder) -> tuple[str, list[list[str]]]:
    """自定义列序：按 `colorder` 输出所选列。"""
    cols = [c for c in colorder.order if c in f.columns] or list(f.columns)
    pos = {c: f.columns.index(c) for c in cols}
    head = " ".join(cols)
    body = [[(f.rows[i].cells[pos[c]] if pos[c] < len(f.rows[i].cells) else "")
             for c in cols] for i in idx]
    return head, body


def _table(f: CG5File, idx: Sequence[int], colorder: ColOrder,
           mode: str) -> tuple[list[str], list[str], list[list[str]]]:
    """→ `(表头单元格, 每列的中文列名, 数据行)`。中文列名用于决定单元格类型。"""
    if mode == _MODE_PARSED:
        cols = [c for c in colorder.order if c in f.columns] or list(f.columns)
        pos = {c: f.columns.index(c) for c in cols}
        body = [[(f.rows[i].cells[pos[c]] if pos[c] < len(f.rows[i].cells) else "")
                 for c in cols] for i in idx]
        return list(cols), list(cols), body
    head = list(f.colsource) or _clean_header(f).split(" ")
    cols = list(f.columns)
    if len(cols) < len(head):                       # 没解析到中文列名时按原位补齐
        cols = cols + [f"col{i + 1}" for i in range(len(cols), len(head))]
    body = [list(f.rows[i].cells) for i in idx]
    return head, cols, body


def default_name(f: CG5File, date: str, surveys: Sequence[str], mode: str,
                 ext: str = "xlsx") -> str:
    """建议文件名：`CG5挑选_<日期>_<survey…>_<格式>.xlsx`。"""
    tag = "-".join([s for s in surveys if s]) or "全部survey"
    tag = "".join(ch for ch in tag if ch not in '\\/:*?"<>|')
    kind = "原始格式" if mode == _MODE_VERBATIM else "自定义列序"
    stem = Path(f.path).stem if f.path else "CG5"
    return f"{stem}_{date}_{tag}_挑选_{kind}.{ext}"


def export_xlsx(f: CG5File, idx: Sequence[int], colorder: ColOrder,
                path: str | Path, *, mode: str = _MODE_VERBATIM,
                include_reason: bool = False,
                reasons: Sequence[str] | None = None,
                include_survey_header: bool = False) -> str:
    """把挑选结果写成 xlsx，返回实际写入路径。

    `mode`：`verbatim`（原始格式，默认）｜`parsed`（自定义列序）
    `include_reason`：附加一列"处理理由"（勾上时导出也带出理由）
    `include_survey_header`：把 Survey 的**文件头字段**写在**表格最上面**
    （用户口径："不是输出 survey 列，是输出 survey 的文件头信息，放在头上"）

    单元格类型：编号列去零后是纯数值就写数值（保留原长度）、数值列写**数值**、
    **时刻/日期写真时间/真日期**（显示同形，Excel 里能筛选排序）；
    Survey 文件头里的 `Instrument S/N` / `ZONE` / `GMT DIFF.` 写数值，
    `Date` / `Time` 写真日期时间，其余字段保持原文。
    """
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
    except ImportError as exc:                      # pragma: no cover
        raise RuntimeError("缺少 openpyxl，无法导出 xlsx。请先安装 openpyxl。") from exc

    head_cells, cols_cn, body = _table(f, idx, colorder, mode)

    add_reason = bool(include_reason and reasons is not None)
    if add_reason:
        head_cells = head_cells + [REASON_COL]
        cols_cn = cols_cn + [REASON_COL]

    wb = Workbook()
    ws = wb.active
    ws.title = "挑选结果"

    # ★ 行号自己数，别用 `ws.max_row + 1`：**空工作表 openpyxl 也报 max_row == 1**，
    #   于是"没有 Survey 文件头"时 header_row 会算成 2 —— 表头样式被加到第 2 行
    #   （顺手创建了一个空行），数据从第 3 行才开始，冻结窗格也偏了一行。
    row_no = 0

    # ---- Survey 文件头（可选）：写在最上面 ----
    #   标签一律原文（`Instrument S/N:`），值按字段定类型：
    #   S/N、ZONE、GMT DIFF. → 数值；Date / Time → 真日期 / 真时间；
    #   其余（Survey name / Client / Operator / LONG / LAT）→ 原文文本。
    if include_survey_header:
        for _name, kvs in survey_headers(f, idx):
            for label, value in kvs:
                v = _kv_value(label, value)
                fmt = None
                if isinstance(v, tuple):            # (值, 数字格式)
                    v, fmt = v
                ws.append([f"{label}:", v])
                row_no += 1
                for c in ws[row_no]:
                    c.fill = PatternFill("solid", fgColor="F2F2F2")
                ws.cell(row=row_no, column=1).font = Font(bold=True)
                if fmt:
                    ws.cell(row=row_no, column=2).number_format = fmt
            ws.append([])                           # 每个 Survey 之间空一行
            row_no += 1

    header_row = row_no + 1
    ws.append(head_cells)                           # 数据表头一律文本
    row_no = header_row
    for c in ws[header_row]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DCE6F1")
        c.alignment = Alignment(horizontal="center", vertical="center")

    for k, row in enumerate(body):
        vals, fmts = [], {}
        for j in range(len(row)):
            v = _cell_value(cols_cn[j], row[j])
            if isinstance(v, tuple):                # (数值, 数字格式)
                v, fmts[j] = v
            vals.append(v)
        if add_reason:
            vals.append(str(reasons[k]) if k < len(reasons) else "")
        ws.append(vals)
        row_no += 1
        for j, fmt in fmts.items():                 # 编号列保留原文的小数位数
            ws.cell(row=row_no, column=j + 1).number_format = fmt

    for col in ws.columns:
        width = max((len(str(c.value)) if c.value is not None else 0)
                    for c in col)
        ws.column_dimensions[col[0].column_letter].width = min(22, max(8, width + 2))
    ws.freeze_panes = f"A{header_row + 1}"          # 冻结到数据表头之下

    p = Path(path)
    if p.suffix.lower() != ".xlsx":
        p = p.with_suffix(".xlsx")
    p.parent.mkdir(parents=True, exist_ok=True)
    wb.save(p)
    return str(p)
