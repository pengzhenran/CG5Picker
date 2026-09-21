"""按测点分组 —— 互差 / 时间间隔 / 最少次数 都必须在"同一测点"内判定。

**为什么不能按"连续行段"分组**（实测教训）：`914_20250710.txt` 的点号序列是
`1,1,1, 3,3,3,3,3, 1,1, 1110,...` —— 测点 1 被观测了两次，中间隔着测点 3。
若按连续行段分组，测点 1 会被劈成 3+2 两段，两边都凑不够"连续 3 次"，
于是整批数据被误判为全部不合格（实测该天 242 条观测保留 0 条）。

规范与现场口径都是"**同一测点的连续 n 次观测**"，所以这里按 **点号+线号**
在整个圈定范围内分组，组内按时间排序 —— 这与 GravProc 的
`core.selection._evaluate(mutual_diff)`（`idx = np.where(st == s)[0]`）一致。
"""
from __future__ import annotations

from typing import Sequence

from .cg5 import ObsRow

__all__ = ["group_by_station", "group_masks", "NUMERIC_COLS"]

#: 需要转成数值参与判定的列（其余列按文本比较）
NUMERIC_COLS = (
    "高程(m)", "读数(mGal)", "标准差(mGal)", "倾斜X(arcsec)", "倾斜Y(arcsec)",
    "温度(℃)", "仪器潮汐改正值(mGal)", "观测时长(s)", "REJ",
    "地形改正值(mGal)", "十进制时间",
)


def cell_of(row: ObsRow, columns: Sequence[str], name: str) -> str:
    """按列名取单元格文本（缺列/越界返回空串）。"""
    try:
        i = list(columns).index(name)
    except ValueError:
        return ""
    return row.cells[i] if 0 <= i < len(row.cells) else ""


def hms_to_hours(s: str) -> float:
    """`19:44:04` → 小数小时；解析失败 → nan。"""
    try:
        h, m, sec = (int(x) for x in s.split(":"))
        return h + m / 60.0 + sec / 3600.0
    except (ValueError, AttributeError):
        return float("nan")


def group_masks(rows: Sequence[ObsRow], columns: Sequence[str]) -> list[str]:
    """每行的分组键文本（线号 + 点号），供 UI 显示/调试。"""
    line = "线号" if "线号" in columns else ""
    st = "点号" if "点号" in columns else ""
    return [f"{cell_of(r, columns, line)}|{cell_of(r, columns, st)}" for r in rows]


def group_by_station(rows: Sequence[ObsRow], columns: Sequence[str],
                     *, sort_by_time: bool = True) -> list[list[int]]:
    """按 线号+点号 分组，返回各组的**局部下标**（`rows` 内的位置）。

    组内默认按时间升序；时间解析不出来时保持原始顺序，
    这样 `time_gap`（相邻观测间隔）的"相邻"才有意义。
    """
    line = "线号" if "线号" in columns else ""
    st = "点号" if "点号" in columns else ""
    has_line = bool(line)
    has_st = bool(st)
    if not has_st and not has_line:
        return [list(range(len(rows)))] if rows else []

    buckets: dict[tuple[str, str], list[int]] = {}
    for i, r in enumerate(rows):
        key = (cell_of(r, columns, line) if has_line else "",
               cell_of(r, columns, st) if has_st else "")
        buckets.setdefault(key, []).append(i)

    if sort_by_time:
        time_col = "时刻" if "时刻" in columns else ""
        dec_col = "十进制时间" if "十进制时间" in columns else ""
        if time_col or dec_col:
            def key_of(j: int) -> tuple[float, int]:
                if dec_col:
                    try:
                        return (float(cell_of(rows[j], columns, dec_col)), j)
                    except ValueError:
                        pass
                if time_col:
                    v = hms_to_hours(cell_of(rows[j], columns, time_col))
                    if v == v:
                        return (v, j)
                return (float("inf"), j)

            for k in buckets:
                buckets[k].sort(key=key_of)

    return list(buckets.values())
