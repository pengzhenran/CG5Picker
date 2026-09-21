"""CG5 数据挑选 —— 启动入口（被 启动_CG5数据挑选.bat 调用）。

支持：
    python main.py                      # 打开界面
    python main.py <CG5手簿>            # 打开界面并直接载入该文件
    python main.py --selftest <手簿>    # 无界面自检

依赖：PySide6 / numpy / matplotlib / openpyxl（缺哪个就报清楚）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _missing_deps() -> list[str]:
    import importlib.util

    need = {"PySide6": "PySide6", "numpy": "numpy",
            "matplotlib": "matplotlib", "openpyxl": "openpyxl"}
    return [pip for mod, pip in need.items()
            if importlib.util.find_spec(mod) is None]


def main() -> int:
    missing = _missing_deps()
    if missing:
        print("[错误] 缺少依赖：" + "、".join(missing), file=sys.stderr)
        print(f"\n当前解释器：{sys.executable}", file=sys.stderr)
        print("请在该解释器下安装：\n  "
              f'"{sys.executable}" -m pip install ' + " ".join(missing),
              file=sys.stderr)
        return 2

    from pickersrc import main as _main

    return _main(sys.argv[1:])


if __name__ == "__main__":
    raise SystemExit(main())
