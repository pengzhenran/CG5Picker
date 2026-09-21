"""CG-5 原始手簿解析 —— 只做"如实解析"，不做任何挑选。

关键事实（实测 `914_20250701.txt`，4001 行）：
**一个导出文件通常含多天、多 Survey、多张数据表**，
所以本模块把"选哪天 / 选哪个 Survey"完全留给界面。

与 GravProc 的 `io/cg5.py` 相比，这里额外保留**每一行的原始文本**，
因为导出要求"按照原始数据格式导出，去掉每行开头的空格"——
只有留着原文才能保证数值的字面精度（如 `0.0000000`、`7432.742`）不丢。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

__all__ = [
    "CG5_COLUMNS", "SURVEY_KEYS", "SETUP_KEYS", "ObsRow", "CG5File", "RuleHit",
    "parse_text", "read_file", "looks_like_cg5", "normalize_date",
]

#: CG-5 列头 → 界面/导出用的中文列名。列头形如
#: `/------LINE-----STATION-----ALT.------GRAV.---SD.--TILTX--TILTY-TEMP---TIDE---DUR-REJ-----TIME----DEC.TIME+DATE--TERRAIN---DATE`
#: ★ 分隔用的短横个数**不固定**：既有多根（`------LINE`），也有**单根**
#:   （`TILTY-TEMP`、`DUR-REJ`）。若按 `-{2,}` 切分会把 4 列并进邻列，整行错位。
CG5_COLUMNS: dict[str, str] = {
    "LINE": "线号",
    "STATION": "点号",
    "ALT.": "高程(m)",
    "ALT": "高程(m)",
    "GRAV.": "读数(mGal)",
    "GRAV": "读数(mGal)",
    "SD.": "标准差(mGal)",
    "SD": "标准差(mGal)",
    "TILTX": "倾斜X(arcsec)",
    "TILTY": "倾斜Y(arcsec)",
    "TEMP": "温度(℃)",
    "TIDE": "仪器潮汐改正值(mGal)",
    "DUR": "观测时长(s)",
    "REJ": "REJ",
    "TIME": "时刻",
    "DEC.TIME+DATE": "十进制时间",
    "TERRAIN": "地形改正值(mGal)",
    "DATE": "日期",
}

#: Survey 块里要提取的字段（原文字段名 → 内部键）
SURVEY_KEYS: dict[str, str] = {
    "Survey name": "survey",
    "Instrument S/N": "sn",
    "Client": "client",
    "Operator": "operator",
    "Date": "date",
    "Time": "time",
    "LONG": "longitude",
    "LAT": "latitude",
    "ZONE": "zone",
    "GMT DIFF.": "gmt_diff",
}

#: SETUP / OPTIONS 里要提取的字段
SETUP_KEYS: dict[str, str] = {
    "Gref": "gref", "Gcal1": "gcal1", "Tempco": "tempco",
    "Drift": "drift_rate", "Tide Correction": "tide_correction",
    "Cont. Tilt": "cont_tilt", "Auto Rejection": "auto_rejection",
    "Terrain Corr.": "terrain_corr", "Seismic Filter": "seismic_filter",
    "Raw Data": "raw_data",
}

_HDR_COL_RE = re.compile(r"^/\s*-{2,}\s*(.+?)\s*$")
_KV_RE = re.compile(r"^/\s*([^:]+?)\s*:\s*(.*?)\s*$")


def _fold(s: str) -> str:
    """把各种空白（含 TAB / 全角空格 / NBSP）折叠成单个普通空格。"""
    return re.sub(r"[\s\u00a0\u3000]+", " ", s)


def _map_columns(cols: list[str]) -> list[str]:
    """原文列头 → 中文列名，重名列自动加 `#2`、`#3`。"""
    out: list[str] = []
    seen: dict[str, int] = {}
    for c in cols:
        base = CG5_COLUMNS.get(c, c)
        k = seen.get(base, 0)
        seen[base] = k + 1
        out.append(base if k == 0 else f"{base}#{k + 1}")
    return out


@dataclass
class ObsRow:
    """一条观测。`text` 是原始行的去首尾空格形态，导出时优先使用。"""

    date: str = ""            # 归一化到 YYYY-MM-DD
    survey: str = ""          # 所属 Survey 块
    sn: str = ""              # 仪器序列号
    cells: list[str] = field(default_factory=list)   # 与列头对齐的单元格
    text: str = ""            # 原始行去首尾空格
    src: int = -1             # 源文件行号（1 基），便于溯源
    tbl: int = 0              # 第几张数据表（0 基）

    def by(self, columns: list[str], name: str) -> str:
        """按列名取单元格（缺列/越界返回空串）。"""
        try:
            i = columns.index(name)
        except ValueError:
            return ""
        return self.cells[i] if 0 <= i < len(self.cells) else ""


@dataclass
class RuleHit:
    """一条观测的取舍结果：`keep=False` 时带上理由与规则名。

    · `picked=True` —— 它是**被「最终取值」挑中的那一条**（处理理由写「最终取值」）；
    · `passed=True` —— 它**通过了筛选条件**，只是没被最终取值挑中
      （处理理由写「满足条件」，用另一种颜色，好和真正的剔除区分开）。
    """

    keep: bool = True
    reason: str = ""
    rule: str = ""
    picked: bool = False
    passed: bool = False


@dataclass
class CG5File:
    """一个 CG-5 导出文件的解析结果。"""

    path: str = ""
    raw_lines: list[str] = field(default_factory=list)
    header: str = ""                                       # 原始列头行（去掉开头 '/'）
    columns: list[str] = field(default_factory=list)       # 中文列名
    colsource: list[str] = field(default_factory=list)     # 原文列名（与 columns 等长）
    rows: list[ObsRow] = field(default_factory=list)
    surveys: list[dict] = field(default_factory=list)      # 各 Survey 块的头信息
    setup: dict = field(default_factory=dict)
    n_tables: int = 0

    # ---------------------------------------------------------------- 清单
    @property
    def dates(self) -> list[str]:
        """全部日期，**最新在前**（界面默认取第一个）。"""
        return sorted({r.date for r in self.rows if r.date}, reverse=True)

    def surveys_of(self, date: str) -> list[str]:
        """给定日期下出现过的 Survey，名称排序。"""
        return sorted({r.survey for r in self.rows if r.date == date and r.survey})

    def count_of(self, date: str, survey: str = "") -> int:
        return sum(1 for r in self.rows
                   if r.date == date and (not survey or r.survey == survey))

    def date_survey_counts(self) -> dict[tuple[str, str], int]:
        out: dict[tuple[str, str], int] = {}
        for r in self.rows:
            out[(r.date, r.survey)] = out.get((r.date, r.survey), 0) + 1
        return out

    def survey_info(self, name: str) -> dict:
        for s in self.surveys:
            if s.get("survey") == name:
                return s
        return {}

    def subset(self, date: str, surveys: list[str] | None = None) -> list[int]:
        """按日期 + Survey 圈定观测，返回**源顺序**的行下标。"""
        want = None if surveys is None else set(surveys)
        return [i for i, r in enumerate(self.rows)
                if r.date == date and (want is None or r.survey in want)]

    def survey_names(self) -> list[str]:
        """全部 Survey 名（去空名），名称排序。"""
        return sorted({r.survey for r in self.rows if r.survey})

    def filter_scope(self, dates: "set[str] | None" = None,
                     surveys: "set[str] | None" = None) -> list[int]:
        """**两条线求交集**：日期集 与 Survey 集（用户口径："前后两个选择是且"）。

        ★ 空集 ≠ 不限：
          · `None` = 这条线**不参与**（内部/测试用，表示"不限"）；
          · **空集 = 空结果（0 条）** —— 一条都没勾就是"还没选"，不该当成"不限"。

        这是踩过坑才改的：以前"空集 = 不参与筛选"，于是把日期「清空」会**突然变成
        整份文件都进来**（用户看到的就是"全部取消，反而选中全部"），而把 Survey
        全取消也不会让数据变少（"取消 survey 选择，数据没取消"）。
        现在两条线都必须有勾选，缺一条就是 0 条，界面会提示"两条线都要勾"。
        """
        if dates is None and surveys is None:
            return list(range(len(self.rows)))
        if dates is not None and not dates:
            return []
        if surveys is not None and not surveys:
            return []
        out: list[int] = []
        for i, r in enumerate(self.rows):
            if dates is not None and r.date not in dates:
                continue
            if surveys is not None and r.survey not in surveys:
                continue
            out.append(i)
        return out

    def surveys_on(self, dates: "set[str]") -> list[str]:
        """这些日期上出现过的 Survey（供"带入 Survey"）。"""
        return sorted({r.survey for r in self.rows
                       if r.date in dates and r.survey})

    def dates_of(self, surveys: "set[str]") -> list[str]:
        """这些 Survey 出现过的日期，最新在前（供"带入日期"）。"""
        return sorted({r.date for r in self.rows
                       if r.survey in surveys and r.date}, reverse=True)

    @property
    def tide_correction(self) -> str:
        return str(self.setup.get("tide_correction", ""))


def looks_like_cg5(text: str) -> bool:
    """是不是 CG-5 原始导出（而不是自定义制表符表）。"""
    head = "\n".join(text.splitlines()[:200])
    if "CG-5 SURVEY" in head:
        return True
    for line in text.splitlines()[:50]:
        m = _HDR_COL_RE.match(line.rstrip())
        if m and "STATION" in m.group(1).upper():
            return True
    return False


def normalize_date(v: object) -> str:
    """`2025/ 6/23`、`2025-06-23`、`2025年6月23日` → ISO 日期串。"""
    s = str(v).strip()
    if not s:
        return ""
    m = re.match(r"^(\d{4})\s*[-/]\s*(\d{1,2})\s*[-/]\s*(\d{1,2})", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    m = re.match(r"^(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", s)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return s


def _parse_ll(s: str) -> float | None:
    """`114.4000000 E` / `30.5 N` → 十进制度（带符号）。"""
    m = re.match(r"^([-\d.]+)\s*([NSEW]?)$", (s or "").strip(), re.I)
    if not m:
        return None
    try:
        v = float(m.group(1))
    except ValueError:
        return None
    return -abs(v) if m.group(2).upper() in ("S", "W") else v


def _date_from_stamp(stamp: str, fallback: str) -> str:
    """从 `45799.82042`（Excel 天数）或 `2025/06/23` 里取日期；取不到用 Survey 头日期。"""
    s = (stamp or "").strip()
    if re.match(r"^\d{4}\s*[-/]", s) or "年" in s:
        return normalize_date(s) or fallback
    if s and s[0].isdigit() and "." in s:
        try:
            from datetime import date, timedelta

            return (date(1899, 12, 30) + timedelta(days=int(float(s)))).isoformat()
        except (ValueError, OverflowError):
            return fallback
    return fallback


def parse_text(text: str) -> CG5File:
    """解析 CG-5 原始导出文本（不做任何筛选）。"""
    out = CG5File()
    out.raw_lines = text.splitlines()

    cur: dict = {}                 # 当前 Survey 块的键值
    surveys: list[dict] = []
    setup: dict = {}
    n_cols = 0                     # 文件里见过的最宽列头
    last_sv_date = ""
    seen_sn = ""

    for ln, raw in enumerate(out.raw_lines, start=1):
        s = raw.rstrip()
        st = s.strip()
        if not st:
            continue

        if st.startswith("/"):
            body = st[1:].strip()
            if body.upper().startswith("CG-5 SURVEY"):
                if cur:
                    surveys.append(cur)
                cur = {}
                continue
            m = _HDR_COL_RE.match(s)
            if m and "STATION" in m.group(1).upper():
                src = [c.strip() for c in re.split(r"-+", m.group(1)) if c.strip()]
                # 同一个文件里列头会重复出现（每个 setup 一套）。以"最宽的一次"
                # 为准，否则只会按第一张表定宽，后段数据行被截断。
                if len(src) > n_cols:
                    n_cols = len(src)
                    out.columns = _map_columns(src)
                    out.colsource = list(src)
                if not out.header:
                    out.header = body
                out.n_tables += 1
                continue
            if body.upper().startswith(("CG-5 SETUP", "CG-5 OPTIONS")):
                continue
            kv = _KV_RE.match(s)
            if kv:
                key, val = kv.group(1).strip(), kv.group(2).strip()
                if key in SURVEY_KEYS:
                    cur[SURVEY_KEYS[key]] = val
                    if key == "Date":
                        last_sv_date = normalize_date(val)
                    elif key == "Instrument S/N":
                        seen_sn = val
                elif key in SETUP_KEYS:
                    setup[SETUP_KEYS[key]] = val
            continue

        # 表外的 "Line\t11.000N" 之类
        if ":" not in st and st.lower().startswith(("line\t", "line ")):
            continue
        if n_cols == 0:
            continue

        flat = _fold(st).strip()
        cells = flat.split(" ")
        if len(cells) < 3:                            # 残缺行，跳过
            continue
        cells = (cells + [""] * n_cols)[:n_cols]
        out.rows.append(ObsRow(
            date=_date_from_stamp(cells[-1], last_sv_date),
            survey=cur.get("survey", ""),
            sn=cur.get("sn", seen_sn),
            cells=cells,
            text=flat,
            src=ln,
            tbl=out.n_tables,
        ))

    if cur:
        surveys.append(cur)

    for s in surveys:
        s = dict(s)
        if "date" in s:
            s["date"] = normalize_date(s["date"])
        for k in ("longitude", "latitude"):
            if k in s:
                s[k] = _parse_ll(s[k])
        out.surveys.append(s)
    out.setup = setup
    return out


def read_file(path: str | Path) -> CG5File:
    """读文件并解析（自动尝试常见编码）。"""
    p = Path(path)
    data = p.read_bytes()
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030", "latin-1"):
        try:
            text = data.decode(enc)
        except UnicodeDecodeError:
            continue
        out = parse_text(text)
        out.path = str(p)
        return out
    raise ValueError(f"无法解码文件：{p}")
