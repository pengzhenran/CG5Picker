"""单元格显示格式 —— 只影响**显示**，绝不改动原始字符串。

针对 `线号` / `点号` 这类"仪器按浮点写的编号"（原始手簿里是 `0.0000000`、
`1.0000000`、`1110.0000000`），用户要求：

  · 整数 → 显示整数         `0.0000000` → `0`
  · 有小数 → **保留小数**   `12.5000000` → `12.5000000`（原样，不截断不四舍五入）
  · 含字母或符号 → 原样显示 `1A` / `L-3` / `2+3` → 原样

判定顺序很重要：先看"整串是不是纯数值"，不是就直接原样返回 ——
绝不能对 `1A`、`L-3` 做数值解析（`float("1A")` 会抛错，`float("nan")` 更糟）。

`+0.5` 这种带正号又有小数的写法，取 `float` 的正规形式（`0.5`）——
因为原字面量的前导 `+` 不是有效数据。

**原始字符串始终保留在 `ObsRow.cells` 里**：导出、分组、筛选一律用原文，
本模块只产出表格显示文本（配合 tooltip 仍可看到原文）。
"""
from __future__ import annotations

import re

__all__ = ["format_id_cell", "is_numeric_text", "NUMERIC_TEXT_RE"]

#: 纯数值文本：可选正负号、可选小数点、可有可无整数/小数部分。
#: 用 `fullmatch` 判定 —— `1A`、`L-3`、`2 3`、`1e5`、`1,000` 都不匹配 → 原样显示。
NUMERIC_TEXT_RE = re.compile(r"[+-]?(?:\d+\.?\d*|\.\d+)")


def is_numeric_text(s: str) -> bool:
    """整串是不是一个纯数值（不含字母、符号、千分位、科学计数法）。"""
    return bool(s) and NUMERIC_TEXT_RE.fullmatch(s) is not None


def format_id_cell(raw: object) -> str:
    """编号类单元格的显示文本：整数去零、小数原样保留、含字母/符号原样。"""
    s = str(raw).strip()
    if not s or not is_numeric_text(s):
        return s                                  # 空串 / 非纯数值 → 原样

    try:
        v = float(s)
    except ValueError:
        return s                                  # 理论上到不了这里，保险起见

    if v == int(v):
        return str(int(v))                        # `0.0000000` → `0`，`007` → `7`

    # 有小数：**原样保留**，只把非标准的前导 `+` 去掉（`+0.5` → `0.5`）
    return s[1:] if s.startswith("+") else s
