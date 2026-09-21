"""CG5 数据挑选 —— 独立小工具（PySide6）。

只做一件事：**从 CG-5 原始手簿里按日期 / Survey / 条件挑出可用观测，
看图形确认，然后按原始格式导出 xlsx**。

模块划分（都能脱离 GUI 单测）：
  · `cg5`       —— 原始手簿解析（保留每行原文，导出才能逐字还原）
  · `rules`     —— 勾选式筛选条件栈（互差 / 观测时长 / 倾斜 / REJ …）
  · `colorder`  —— 列的显示与导出顺序
  · `exporter`  —— 原始格式 / 自定义列序 → xlsx
  · `plots`     —— 四种视图（与大软件一致）+ 理论固体潮公式
  · `window`    —— 界面组织
"""
from __future__ import annotations

import sys

__version__ = "1.0.0"


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--selftest" in argv:
        from .selftest import run_selftest

        return run_selftest(argv)

    from .window import run

    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
