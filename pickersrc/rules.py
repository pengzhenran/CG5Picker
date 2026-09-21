"""筛选条件（勾选式）—— 可增减、可改参、**勾选立即生效**。

设计取舍：
  · 每条条件是**一个可勾选的项**，勾上=参与筛选，取消=不参与，改参数立刻重算。
  · **连接词**（`Cond.link`）把条件分成**三组**，先分组判定、再取交集：

      | 连接 | 含义 | 对应界面 |
      |---|---|---|
      | `primary` 首要 | 组内**全部**满足 | 第一块：首要条件 |
      | `or` 或 | 组内**至少一条**满足 | 第二块：或 |
      | `and` 且 | 组内**全部**满足 | 第二块：且 |

    空组不参与。于是"连续3个互差不超5 **或** 连续2个互差不超1 **且** 观测时长≥35 s"
    就是：或组两条互差 + 且组（或首要）一条时长。
  · 每条被剔除的观测记录**使它不通过的那条条件**作为理由（或组全不满足时列出整组），
    表格里"处理理由"列可查。
  · `互差` 取该测点**最后 n 次**观测判定，合格则只保留**最后一次**。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Sequence

from .cg5 import CG5File, ObsRow, RuleHit
from .grouping import cell_of, group_by_station, hms_to_hours

__all__ = [
    "CondKind", "Cond", "COND_KINDS", "PARAM_CN", "PRESETS", "LINKS", "LINK_CN",
    "apply_conditions", "preview", "default_conditions", "logic_text",
    "group_of", "numeric", "migrate_conds",
    "C_LINE", "C_STATION", "C_RAW", "C_SD", "C_DUR", "C_REJ", "C_TIME",
    "C_TILTX", "C_TILTY", "C_TEMP", "C_TIDE", "C_DECTIME",
]

#: 连接词：`(值, 界面文字, 说明)` —— 界面下拉框与判定都用它
LINKS: tuple[tuple[str, str, str], ...] = (
    ("primary", "首要", "首要条件：勾上的都必须满足（第一块）"),
    ("or", "或", "或：这一组里至少一条满足即可"),
    ("and", "且", "且：这一组里每条都要满足"),
)
LINK_CN: dict[str, str] = {k: cn for k, cn, _d in LINKS}

#: 各条件用到的列名（中文列名，与 CG5File.columns 对应）
C_LINE, C_STATION = "线号", "点号"
C_RAW, C_SD = "读数(mGal)", "标准差(mGal)"
C_TILTX, C_TILTY = "倾斜X(arcsec)", "倾斜Y(arcsec)"
C_TEMP = "温度(℃)"
C_DUR, C_REJ, C_TIME = "观测时长(s)", "REJ", "时刻"
C_TIDE, C_DECTIME = "仪器潮汐改正值(mGal)", "十进制时间"

#: 参数默认中文名（各条件可用 `CondKind.params_cn` 覆盖，避免"标准差上限(互差上限)"这类串味）
PARAM_CN: dict[str, str] = {
    "n": "次数",
    "limit_uGal": "上限 (μGal)",
    "lo": "下限 (s)",
    "hi": "上限 (s)（0=不限）",
    "limit_arcsec": "倾斜上限（角秒）",
    "limit_min": "最大间隔（分钟）",
}


# ==========================================================================
# 数值工具
# ==========================================================================
def numeric(rows: Sequence[ObsRow], columns: Sequence[str], name: str) -> list[float]:
    """按列名取一列数值；缺列或非数值 → `nan`。"""
    try:
        i = list(columns).index(name)
    except ValueError:
        return [float("nan")] * len(rows)
    out: list[float] = []
    for r in rows:
        s = r.cells[i] if 0 <= i < len(r.cells) else ""
        try:
            out.append(float(s))
        except (TypeError, ValueError):
            out.append(float("nan"))
    return out


def _hms_to_h(s: str) -> float:
    """`19:44:04` → 小数小时；解析失败 → nan。"""
    return hms_to_hours(s)


def _blocks(rows: Sequence[ObsRow], columns: Sequence[str]) -> list[list[int]]:
    """同一测点的所有观测（组内按时间排序）—— 见 `grouping` 模块的实测教训。

    注意：**不是**"连续行段"。手簿里同一测点可能被观测两轮
    （如 `1,1,1, 3,3,3,3,3, 1,1`），按行段切会把它劈开，导致凑不够
    "连续 3 次"而误剔整批数据。
    """
    return group_by_station(rows, columns)


def _cell(r: ObsRow, columns: Sequence[str], name: str) -> str:
    return cell_of(r, columns, name)


# ==========================================================================
# 条件类型
# ==========================================================================
@dataclass
class CondKind:
    """一种筛选条件的元信息 + 判定实现。"""

    kind: str
    cn: str
    desc: str
    basis: str
    params: dict[str, Any]                 # 参数名 → 默认值（顺序即表单顺序）
    evaluate: Callable[[CG5File, Sequence[int], dict], list[bool]]
    needs: tuple[str, ...] = ()            # 依赖的列，缺列则整条不适用
    params_cn: dict[str, str] = field(default_factory=dict)   # 参数中文名（覆盖 PARAM_CN）


def _eval_mutual_diff(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """**任意连续 n 次**观测的极差 ≤ 限差 → 这 n 个读数都算"满足条件"。

    用户口径："满足条件的 3 个数中，最后选择最后一个数。" ——
    判定（互差）与取值（挑哪一条）是**两件事**：
      · 本条只负责判定：把**互差合格的窗口**里的读数全部标成"满足条件"；
      · **具体保留哪一条**由「最终取值」条件决定（默认取最新；也可取最小距平）。

    ★ 判定用**滑动窗口**（对整段序列逐个窗口扫），不是"只看最后 n 次"。
      踩过的坑（用户实测 `1465_20250702.txt` 线0/点0，一天 11 次观测）：
        06:59:55 与 07:01:00 两次读数**完全相同**（6822.267，互差 0 μGal），
        但当时只看"最后 2 次"（07:32:06 / 07:33:06），这两条就被误判成
        "或组都不满足"。现场读法本来就是"连续 n 个互差合格的那些数里取最后一个"，
        合格窗口出现在序列中间也算数 —— 而且 最终取值=最新 仍会挑到最新的那条。
    """
    n = max(2, int(p.get("n", 3)))
    lim = float(p.get("limit_uGal", 5.0))
    rows = [f.rows[i] for i in idx]
    vals = numeric(rows, f.columns, C_RAW)
    good = [False] * len(rows)
    for blk in _blocks(rows, f.columns):          # 组内已按时间排序
        if len(blk) < n:
            continue                              # 凑不够 n 次 → 无从判定，不保留
        for s in range(len(blk) - n + 1):         # ★ 滑动窗口：逐个窗口判定
            w = [vals[blk[j]] for j in range(s, s + n)]
            if any(v != v for v in w):            # 含缺值 → 这个窗口不判定
                continue
            if (max(w) - min(w)) * 1000.0 <= lim + 1e-9:
                for j in range(s, s + n):
                    good[blk[j]] = True           # 窗口内全部标为满足
    return good


def _eval_final_pick(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """「最终取值」不是过滤器 —— 它只在**已经满足其它条件**的读数里挑一条。

    真正的挑选在 `apply_conditions` 的收尾步骤里做（那时才知道谁满足了），
    这里一律返回 True，避免把它当成过滤条件而误剔。
    """
    return [True] * len(idx)


def _row_hours(f: CG5File, r: ObsRow) -> float:
    """这一行的**时间**（小时，跨天连续）：优先 `十进制时间`（含日期），其次 `时刻`。"""
    d = _cell(r, f.columns, C_DECTIME)
    if d:
        try:
            return float(d) * 24.0
        except ValueError:
            pass
    return hms_to_hours(_cell(r, f.columns, C_TIME))


def pick_final(f: CG5File, idx: Sequence[int], flags: list[bool],
               mode: str, picked: list[bool] | None = None,
               gap_min: float = 5.0) -> None:
    """**每一轮观测**只留一条：`latest`（最新，默认）或 `min_dev`（最小距平）。

    最小距平 = 离**这些合格读数的均值**差值最小的那一条；
    **只有两个读数时取最新一个**（两点的均值必然落在中间，取"距平最小"没有意义）。

    ★ **按"独立观测"分段，而不是"每个测点全天只留一条"**（用户实测踩到）：
      `1465_20250702.txt` 的点号 1 一天被观测了 **5 轮**
      （06:37~06:40、06:50~06:55、07:23~07:25、07:35~07:42、17:06~17:08，多半是基点重复观测），
      同点相邻间隔超过 `gap_min` 分钟就算**另一轮**。全天只留一条会把 4 轮有效成果丢掉，
      用户看到的就是"上午那些条明明满足条件，却没有一条被标为最终取值"。

    直接就地改 `flags`（True=保留）；`picked` 非空时把**真正做过取舍的那一轮里**被挑中的
    那一条标成 True（处理理由列要写「最终取值」）。
    """
    rows = [f.rows[i] for i in idx]
    t = [_row_hours(f, r) for r in rows]
    vals = numeric(rows, f.columns, C_RAW)
    gap = max(0.0, float(gap_min)) / 60.0

    def newest(cand: list[int]) -> int:
        return max(cand, key=lambda j: (t[j] if t[j] == t[j] else -1.0, j))

    def split_runs(blk: list[int]) -> list[list[int]]:
        """把该测点按时间间隔切成"几轮观测"。"""
        runs: list[list[int]] = []
        cur: list[int] = []
        for j in blk:
            if cur:
                a, b = t[cur[-1]], t[j]
                if a == a and b == b and (b - a) > gap + 1e-9:
                    runs.append(cur)      # 隔太久 → 新的一轮
                    cur = []
            cur.append(j)
        if cur:
            runs.append(cur)
        return runs

    for blk in _blocks(rows, f.columns):
        for run in split_runs(blk):
            cand = [j for j in run if flags[j]]
            if len(cand) <= 1:
                continue                  # 这一轮本来就只剩一条：没做取舍
            pick = newest(cand)
            if mode == "min_dev" and len(cand) > 2:
                vals_ok = [vals[j] for j in cand if vals[j] == vals[j]]
                if vals_ok:
                    mean = sum(vals_ok) / len(vals_ok)
                    pick = min((j for j in cand if vals[j] == vals[j]),
                               key=lambda j: abs(vals[j] - mean))
            if picked is not None:
                picked[pick] = True
            for j in cand:
                if j != pick:
                    flags[j] = False


def _eval_seg_gap(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """分段间隔 —— **本身不剔除任何观测**，它是「最终取值」的分轮参数。

    用户口径（本轮）："最终取值里参数里有个分段间隔，这个要单独出来，是个'且'连接。"

    所以它像 `final_pick` 一样**不参与过滤**（全部命中），只把"同点相邻间隔超过多少
    分钟算新的一轮"这个数带进条件栈：界面上看得见、能改，判定式里也写得出来。
    """
    return [True] * len(idx)


def _eval_duration(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """观测时长落在 [lo, hi] 内；`hi<=0` 表示只卡下限。默认下限 35 s。"""
    lo = float(p.get("lo", 35.0))
    hi = float(p.get("hi", 0.0))
    v = numeric([f.rows[i] for i in idx], f.columns, C_DUR)
    out = []
    for x in v:
        if x != x:
            out.append(False)
        elif hi > 0:
            out.append(lo - 1e-9 <= x <= hi + 1e-9)
        else:
            out.append(x >= lo - 1e-9)
    return out


def _eval_std(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    lim = float(p.get("limit_uGal", 5.0))
    return [x == x and x * 1000.0 <= lim + 1e-9
            for x in numeric([f.rows[i] for i in idx], f.columns, C_SD)]


def _eval_tilt(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    lim = float(p.get("limit_arcsec", 5.0))
    rows = [f.rows[i] for i in idx]
    tx = numeric(rows, f.columns, C_TILTX)
    ty = numeric(rows, f.columns, C_TILTY)
    out = []
    for a, b in zip(tx, ty):
        ok = True
        if a == a:
            ok = ok and abs(a) <= lim + 1e-9
        if b == b:
            ok = ok and abs(b) <= lim + 1e-9
        out.append(ok)
    return out


def _eval_temp(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    lo, hi = float(p.get("lo", -40.0)), float(p.get("hi", 60.0))
    return [x == x and lo - 1e-9 <= x <= hi + 1e-9
            for x in numeric([f.rows[i] for i in idx], f.columns, C_TEMP)]


def _eval_rej(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    return [x == 0 for x in numeric([f.rows[i] for i in idx], f.columns, C_REJ)]


def _eval_min_obs(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """每个测点的观测次数不少于 n（整点保留或整点剔除）。"""
    need = max(1, int(p.get("n", 3)))
    rows = [f.rows[i] for i in idx]
    flags = [True] * len(rows)
    for blk in _blocks(rows, f.columns):
        if len(blk) < need:
            for j in blk:
                flags[j] = False
    return flags


def _eval_time_gap(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """同点相邻观测时间间隔不超过 limit_min 分钟。"""
    lim = float(p.get("limit_min", 10.0)) / 60.0
    rows = [f.rows[i] for i in idx]
    t = [_hms_to_h(x) for x in
         [_cell(r, f.columns, C_TIME) for r in rows]]
    flags = [True] * len(rows)
    for blk in _blocks(rows, f.columns):
        if len(blk) < 2:
            continue
        for a, b in zip(blk, blk[1:]):
            ta, tb = t[a], t[b]
            same_day_gap = abs(tb - ta)
            if same_day_gap > lim + 1e-9:
                flags[a] = False
                flags[b] = False
    return flags


def _eval_independent_gap(f: CG5File, idx: Sequence[int], p: dict) -> list[bool]:
    """同点相邻观测的**时间间隔大于阈值**才算"独立观测"。

    现场口径："间隔 5min 以上为独立观测" —— 两次读数挨得太近（< 5 min），
    说明还是同一轮读数、不算独立；要留就留中间隔足够的那几条。

    判定（组内按时间升序）：
      · 与**前一次**观测间隔 > 阈值；
      · 或与**后一次**观测间隔 > 阈值；
      · 只有一次观测的点：无从比较 → 视为独立（不因此剔除）。
    首/末条只要与相邻那一次拉开了间隔就算独立，不会整点被误剔。
    """
    lim = float(p.get("limit_min", 5.0)) / 60.0
    rows = [f.rows[i] for i in idx]
    t = [hms_to_hours(_cell(r, f.columns, C_TIME)) for r in rows]
    flags = [True] * len(rows)
    for blk in _blocks(rows, f.columns):
        for a, j in enumerate(blk):
            tt = t[j]
            if tt != tt:                      # 时间读不出来 → 不判定
                continue
            prev_ok = prev_bad = False
            nxt_ok = nxt_bad = False
            if a > 0 and t[blk[a - 1]] == t[blk[a - 1]]:
                gap = abs(tt - t[blk[a - 1]])
                prev_ok, prev_bad = gap > lim, gap <= lim
            if a + 1 < len(blk) and t[blk[a + 1]] == t[blk[a + 1]]:
                gap = abs(t[blk[a + 1]] - tt)
                nxt_ok, nxt_bad = gap > lim, gap <= lim
            if not (prev_ok or nxt_ok):
                # 两边都比阈值近 → 不够独立；若两边都没得比（单次观测）则保留
                flags[j] = not (prev_bad or nxt_bad)
    return flags


COND_KINDS: dict[str, CondKind] = {
    k.kind: k for k in [
        CondKind(
            "mutual_diff", "互差",
            "最后 n 次观测的极差不大于限差 → 该测点取最后一次观测",
            "DZ/T 0004-2015、DZ/T 0171-2017 观测数据取舍",
            {"n": 3, "limit_uGal": 5.0}, _eval_mutual_diff, (C_RAW, C_STATION),
            {"n": "连续观测次数", "limit_uGal": "互差上限 (μGal)"}),
        CondKind(
            "duration", "观测时长", "观测时长不小于最短时长（可另设上限）",
            "CG-5 单次观测时长设置",
            {"lo": 35.0, "hi": 0.0}, _eval_duration, (C_DUR,),
            {"lo": "最短时长 (s)", "hi": "最长时长 (s)（0=不限）"}),
        CondKind(
            "min_obs", "最少观测次数", "每个测点的观测次数不少于 n",
            "规范要求每测点观测次数下限",
            {"n": 3}, _eval_min_obs, (C_STATION,),
            {"n": "每点最少观测次数"}),
        CondKind(
            "std_limit", "标准差上限", "单次观测标准差不超过上限",
            "仪器重复性指标",
            {"limit_uGal": 5.0}, _eval_std, (C_SD,),
            {"limit_uGal": "标准差上限 (μGal)"}),
        CondKind(
            "tilt_limit", "倾斜上限", "|倾斜X| 与 |倾斜Y| 均不超过上限",
            "CG-5 操作要求（一般 ≤ 5″，自动调平范围）",
            {"limit_arcsec": 5.0}, _eval_tilt, (C_TILTX, C_TILTY),
            {"limit_arcsec": "倾斜上限（角秒）"}),
        CondKind(
            "rej_zero", "REJ 必须为 0", "剔除 REJ ≠ 0 的观测",
            "CG-5 REJ 非 0 表示读数被仪器舍弃",
            {}, _eval_rej, (C_REJ,)),
        CondKind(
            "temp_range", "温度区间", "温度落在 [下限, 上限] 内",
            "仪器工作温度范围",
            {"lo": -40.0, "hi": 60.0}, _eval_temp, (C_TEMP,),
            {"lo": "温度下限 (℃)", "hi": "温度上限 (℃)"}),
        CondKind(
            "time_gap", "观测时间间隔", "同点相邻观测间隔不超过上限（分钟）",
            "同一测点应连续观测",
            {"limit_min": 10.0}, _eval_time_gap, (C_TIME,),
            {"limit_min": "同点最大间隔（分钟）"}),
        CondKind(
            "independent_gap", "独立观测间隔",
            "同点相邻观测的时间间隔大于阈值，才算独立观测",
            "现场口径：间隔 5 min 以上为独立观测",
            {"limit_min": 5.0}, _eval_independent_gap, (C_TIME,),
            {"limit_min": "独立观测最小间隔（分钟）"}),
        # ★ 「最终取值」不是过滤器，是**挑选口径**：在已经满足其它条件的读数里
        #   **每一轮观测**只留一条（默认最新；也可取最小距平）。
        #   分轮的间隔**单独成条**（见下面的「分段间隔」），不再塞在它的参数里
        #   —— 用户口径："最终取值里参数里有个分段间隔，这个要单独出来，是个'且'连接。"
        CondKind(
            "final_pick", "最终取值",
            "在已满足条件的读数里，**每一轮观测**只保留一条：默认取最新；"
            "也可选「最小距平」（离这些合格读数的均值最近，只有两个读数时取最新）。"
            "「每一轮」怎么分由「分段间隔」那条决定",
            "DZ/T 0004-2015 观测成果取值；用户口径"
            "「满足条件的 3 个数中，最后选择最后一个数」",
            {"mode": "latest"}, _eval_final_pick, (C_RAW, C_STATION),
            {"mode": "取值方式"}),
        # ★ 「分段间隔」：从「最终取值」的参数里拆出来的**独立一条（且）**。
        #   它自己不剔除观测，只定义"多少分钟以上算新的一轮"。
        CondKind(
            "seg_gap", "分段间隔",
            "同一点相邻两次观测相隔**超过**这个时间，就算**新的一轮**："
            "「最终取值」在每一轮里各留一条（一天测几轮就留几条）。"
            "本条不剔除任何观测，只给「最终取值」定分轮口径",
            "用户口径：上午/下午各测一轮时两轮都要留一条；"
            "基点重复观测不会因为间隔大而被并成一轮",
            {"gap_min": 5.0}, _eval_seg_gap, (C_TIME, C_STATION),
            {"gap_min": "间隔（分钟）"}),
    ]
}


# ==========================================================================
# 条件实例
# ==========================================================================
@dataclass
class Cond:
    """一条可勾选的筛选条件。

    `link`（连接词）决定它在条件栈里的角色：`primary` 首要 / `or` 或 / `and` 且。
    默认 `and` —— 老预设（JSON 里没有这个键）读进来仍然等价于"全部取交集"。
    """

    kind: str
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    source: str = "preset"                  # preset | manual
    link: str = "and"                       # primary | or | and

    def __post_init__(self) -> None:
        if self.kind not in COND_KINDS:
            raise KeyError(f"未知筛选条件 {self.kind!r}；可用：{sorted(COND_KINDS)}")
        if self.link not in LINK_CN:
            self.link = "and"

    @property
    def meta(self) -> CondKind:
        return COND_KINDS[self.kind]

    @property
    def cn(self) -> str:
        return self.meta.cn

    @property
    def link_cn(self) -> str:
        return LINK_CN.get(self.link, "且")

    def describe(self) -> str:
        """带参数的中文描述，用于"处理理由"列与汇总。"""
        if self.kind == "seg_gap":                 # 别写成"分段间隔（间隔（分钟）=5）"
            return f"分段间隔 >{_fmt(self.params.get('gap_min', 5))} min"
        ps = []
        names = self.meta.params_cn
        for k, v in self.params.items():
            if k in ("hi", "max_s") and float(v or 0) == 0:
                continue
            ps.append(f"{names.get(k) or PARAM_CN.get(k, k)}={_fmt(v)}")
        return f"{self.cn}（{'，'.join(ps)}）" if ps else self.cn

    def params_brief(self) -> str:
        """参数列的**紧凑但完整**写法：`3 次，≤5 μGal`、`≥35 s`。

        条件列已经写了条件名（互差 / 观测时长…），参数列不必再重复标签 ——
        这样 ② 面板不必很宽就能**完整显示**参数（长写法 `describe()` 留给悬停提示）。
        """
        p = self.params
        if self.kind == "mutual_diff":
            return (f"{_fmt(p.get('n', 3))} 次，≤"
                    f"{_fmt(p.get('limit_uGal', 5))} μGal")
        if self.kind == "final_pick":
            return "最新" if p.get("mode") != "min_dev" else "最小距平"
        if self.kind == "seg_gap":
            return f">{_fmt(p.get('gap_min', 5))} min"
        if self.kind == "duration":
            lo, hi = _fmt(p.get("lo", 35)), float(p.get("hi", 0) or 0)
            return f"≥{lo} s" if hi <= 0 else f"{lo}~{_fmt(hi)} s"
        if self.kind == "min_obs":
            return f"≥{_fmt(p.get('n', 3))} 次"
        if self.kind == "std_limit":
            return f"≤{_fmt(p.get('limit_uGal', 5))} μGal"
        if self.kind == "tilt_limit":
            return f"≤{_fmt(p.get('limit_arcsec', 5))}″"
        if self.kind == "temp_range":
            return f"{_fmt(p.get('lo'))}~{_fmt(p.get('hi'))} ℃"
        if self.kind == "time_gap":
            return f"≤{_fmt(p.get('limit_min', 10))} min"
        if self.kind == "independent_gap":
            return f">{_fmt(p.get('limit_min', 5))} min"
        if not p:
            return "—"
        return "，".join(
            f"{self.meta.params_cn.get(k) or PARAM_CN.get(k, k)}={_fmt(v)}"
            for k, v in p.items())

    def brief(self) -> str:
        """短描述：`互差 3次/5μGal`、`时长 ≥35s` —— 给"或组都不满足"和判定式用。"""
        p = self.params
        if self.kind == "mutual_diff":
            return (f"互差 {_fmt(p.get('n', 3))}次/"
                    f"{_fmt(p.get('limit_uGal', 5))}μGal")
        if self.kind == "duration":
            hi = float(p.get("hi", 0) or 0)
            lo = _fmt(p.get("lo", 35))
            return f"时长 ≥{lo}s" if hi <= 0 else f"时长 {lo}~{hi}s"
        if self.kind == "min_obs":
            return f"每点 ≥{_fmt(p.get('n', 3))} 次"
        return f"{self.cn} {self.params_brief()}".strip()

    def to_dict(self) -> dict:
        return {"kind": self.kind, "params": dict(self.params),
                "enabled": self.enabled, "source": self.source,
                "link": self.link}

    @classmethod
    def from_dict(cls, d: dict) -> "Cond":
        return cls(kind=d["kind"], params=dict(d.get("params", {})),
                   enabled=bool(d.get("enabled", True)),
                   source=d.get("source", "manual"),
                   link=d.get("link", "and"))


def _fmt(v: Any) -> str:
    if isinstance(v, float) and v == int(v):
        return str(int(v))
    return str(v)


def default_conditions() -> list[Cond]:
    """出厂默认 = **「互相差 或，时长 且，最后取最新」**（用户指定的新默认）。

    `(互差 连续3次/5μGal 或 互差 连续2次/1μGal) 且 观测时长 ≥35 s`
    `且 最终取值=最新 且 分段间隔 >5 min`

    ★ 「分段间隔」本轮从「最终取值」的参数里拆出来，单独一条、用**且**连接
      （用户："最终取值里参数里有个分段间隔，这个要单独出来，是个'且'连接"）。
    """
    return [
        Cond("duration", {"lo": 35.0, "hi": 0.0}, link="primary"),
        Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0}, link="or"),
        Cond("mutual_diff", {"n": 2, "limit_uGal": 1.0}, link="or"),
        # ★ 挑选口径单独成条：默认取最新，也可以改成"最小距平"
        Cond("final_pick", {"mode": "latest"}, link="and"),
        # ★ 分轮间隔也是单独一条（且）：间隔超过 5 min 就算新的一轮
        Cond("seg_gap", {"gap_min": 5.0}, link="and"),
    ]


def migrate_conds(conds: Sequence[Cond]) -> list[Cond]:
    """老预设置的「最终取值」把分段间隔塞在 `params['gap_min']` 里 —— 拆成独立一条。

    读老 JSON（`%APPDATA%\\CG5Picker\\presets.json`）时用；已经拆过的不动。
    """
    out: list[Cond] = []
    gap: float | None = None
    for c in conds:
        if c.kind == "final_pick" and "gap_min" in c.params:
            gap = float(c.params.pop("gap_min") or 5.0)
        out.append(c)
    if gap is None or any(c.kind == "seg_gap" for c in out):
        return out
    at = next((k for k, c in enumerate(out) if c.kind == "final_pick"), len(out) - 1)
    out.insert(at + 1, Cond("seg_gap", {"gap_min": gap}, link="and"))
    return out


#: 预设条件集（一键套用，之后仍可逐条增减改参）
#: ★ 用户要求去掉「严格互差」与「全不勾选」两个内置组合。
PRESETS: dict[str, dict[str, Any]] = {
    "default": {
        "cn": "默认：互差(3/5 或 2/1) 且 时长≥35 且 取最新 且 分段>5min",
        "desc": "出厂默认（用户指定）。观测时长 ≥35 s 为**首要条件**；"
                "读数重复性满足「连续 3 次互差 ≤5 μGal」**或**"
                "「连续 2 次互差 ≤1 μGal」其一即可；"
                "最后按「最终取值=最新」+「分段间隔 >5 min」"
                "**每一轮观测**留一条（可改成「最小距平」）。",
        "conds": default_conditions,
    },
    "mutual_only": {
        "cn": "仅互差：连续3互差5",
        "desc": "只看读数重复性，不管观测时长。",
        "conds": lambda: [Cond("mutual_diff", {"n": 3, "limit_uGal": 5.0})],
    },
    "duration_only": {
        "cn": "仅时长：≥35 s",
        "desc": "只按观测时长卡，用于快速剔除短观测。",
        "conds": lambda: [Cond("duration", {"lo": 35.0, "hi": 0.0})],
    },
    "hardware": {
        "cn": "硬件质量：倾斜≤5″ + REJ=0 + 时长≥35",
        "desc": "只按仪器状态剔除，不评判读数离散。",
        "conds": lambda: [Cond("tilt_limit", {"limit_arcsec": 5.0}),
                          Cond("rej_zero", {}),
                          Cond("duration", {"lo": 35.0, "hi": 0.0})],
    },
}


# ==========================================================================
# 执行
# ==========================================================================
def group_of(conds: Sequence[Cond]) -> dict[str, list[Cond]]:
    """按连接词把**已勾选**的条件分成三组（`primary` / `or` / `and`）。"""
    out: dict[str, list[Cond]] = {"primary": [], "or": [], "and": []}
    for c in conds:
        if c.enabled:
            out.setdefault(c.link, []).append(c)
    return out


def logic_text(conds: Sequence[Cond]) -> str:
    """把条件栈翻译成一句人话，例如：

        `(互差 3次/5μGal 或 互差 2次/1μGal) 且 时长 ≥35s`
    """
    g = group_of(conds)
    parts: list[str] = []
    if g["or"]:
        joiner = " 或 "
        s = joiner.join(c.brief() for c in g["or"])
        parts.append(f"({s})" if len(g["or"]) > 1 else s)
    rest = [c.brief() for c in g["primary"]] + [c.brief() for c in g["and"]]
    if rest:
        parts.append(" 且 ".join(rest))
    if not parts:
        return "（没有勾选任何条件：全部保留）"
    return " 且 ".join(parts)


def apply_conditions(f: CG5File, idx: Sequence[int],
                     conds: Sequence[Cond]) -> tuple[list[RuleHit], dict[str, int]]:
    """按条件栈筛选 `idx` 圈定的观测（**用连接词分组判定**）。

    判定 = `首要组(全部满足)` **且** `或组(至少一条满足)` **且** `且组(全部满足)`，
    空组不参与 —— 于是：

      · 全是"且"（老行为）→ 与以前完全一致（交集）；
      · 两条互差标"或"、时长标"且" → `(互差3/5 或 互差2/1) 且 时长≥35`。

    返回 `(hits, 各条件命中数)`：
      · `hits[k].reason` 是**使它不通过的那条条件**（或组全不满足时列出整组）；
      · **命中数 = 满足该条条件的观测数**（不是被它剔除的数量 ——
        用户看着"时长 命中 0"会以为时长没用上，其实满屏都不合格才是 0）。
      · `final_pick`（最终取值）不参与过滤：它在最后一步从"已满足的读数"里挑一条。
    """
    n = len(idx)
    hits = [RuleHit(keep=True) for _ in range(n)]
    per_cond: dict[str, int] = {}
    final_mode: str | None = None
    final_cond: Cond | None = None
    final_gap = 5.0

    # 先各算一遍（每条只算一次），按组收好
    groups: dict[str, list[tuple[Cond, list[bool]]]] = {
        "primary": [], "or": [], "and": []}
    for c in conds:
        if not c.enabled:
            continue
        if c.kind == "final_pick":                    # 不参与过滤，留到最后一步
            final_mode = str(c.params.get("mode", "latest"))
            final_cond = c
            continue
        if c.kind == "seg_gap":                       # 只提供分轮间隔，不剔除任何观测
            final_gap = float(c.params.get("gap_min", 5.0) or 0.0)
            per_cond[c.describe()] = n                # 命中 = 全部（它不剔人）
            continue
        try:
            ok = c.meta.evaluate(f, idx, c.params)
        except Exception as exc:                      # noqa: BLE001
            per_cond[f"{c.describe()} ✖{type(exc).__name__}"] = n
            continue
        if len(ok) != n:
            ok = (list(ok) + [True] * n)[:n]
        # ★ 命中 = 通过该条条件的观测数
        per_cond[c.describe()] = (per_cond.get(c.describe(), 0)
                                  + sum(1 for x in ok if x))
        groups.setdefault(c.link, []).append((c, list(ok)))

    or_grp = groups.get("or", [])
    or_reason = ("或组都不满足（"
                 + " ｜ ".join(c.brief() for c, _ok in or_grp) + "）")
    for k in range(n):
        # 1) 首要 / 且：任一不满足 → 剔除，理由就是那一条
        bad: Cond | None = None
        for link in ("primary", "and"):
            for c, ok in groups.get(link, []):
                if not ok[k]:
                    bad = c
                    break
            if bad is not None:
                break
        if bad is not None:
            hits[k].keep = False
            hits[k].reason = bad.describe()
            hits[k].rule = bad.kind
            continue
        # 2) 或组：一条都不满足 → 剔除，理由列出整组
        if or_grp and not any(ok[k] for _c, ok in or_grp):
            hits[k].keep = False
            hits[k].reason = or_reason
            hits[k].rule = "or_group"

    # 3) 「最终取值」：在已满足的读数里，**每一轮观测**只留一条
    if final_mode is not None:
        flags = [h.keep for h in hits]
        before = list(flags)
        picked_flags = [False] * n
        pick_final(f, idx, flags, final_mode, picked_flags, final_gap)
        for k in range(n):
            if before[k] and not flags[k]:
                # ★ 它**通过了筛选条件**，只是没被挑中 —— 处理理由就写「满足条件」
                #   （用户口径：这种行显示"满足条件"即可，另用字体颜色区分）
                hits[k].keep = False
                hits[k].reason = "满足条件"
                hits[k].rule = "final_pick"
                hits[k].passed = True
            elif picked_flags[k]:
                # ★ 被「最终取值」挑中的那一条：处理理由写「最终取值」
                hits[k].picked = True
        if final_cond is not None:
            # 「最终取值」的命中数 = **被它挑中的条数**（写"满足条件的条数"会显示 0，
            # 因为它挑剩下的那些都归到"满足条件"了）
            per_cond[final_cond.describe()] = sum(1 for h in hits if h.picked)
    return hits, per_cond


def preview(f: CG5File, idx: Sequence[int],
            conds: Sequence[Cond]) -> dict[str, Any]:
    """预览：给出保留/剔除数与各条件命中数，不修改任何数据。"""
    hits, per_cond = apply_conditions(f, idx, conds)
    n_keep = sum(1 for h in hits if h.keep)
    by_rule: dict[str, int] = {}
    for h in hits:
        if not h.keep and h.rule:
            by_rule[h.rule] = by_rule.get(h.rule, 0) + 1
    return {
        "n_total": len(idx),
        "n_keep": n_keep,
        "n_drop": len(idx) - n_keep,
        "per_cond": per_cond,
        "by_rule": by_rule,
        "hits": hits,
        "summary": f"保留 {n_keep} / 剔除 {len(idx) - n_keep} / 共 {len(idx)}",
    }
