# -*- coding: utf-8 -*-
"""生成使用说明里的配图（与 `使用说明.html` 配套，可重复跑）。

用法：
    python docs/make_help_img.py            # 写出 docs/使用说明_img/*.png

说明：这些图是"随包的说明书配图"，跟自检脚本无关 —— 自检的截图另有一套。
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication                     # noqa: E402

from pickersrc.about_dialog import AboutDialog                 # noqa: E402
from pickersrc.plots import ensure_cjk_font                    # noqa: E402
from pickersrc.window import MainWindow, _create_app           # noqa: E402

SRC = (ROOT.parent / "GravProc" / "examples" / "示例数据" / "宁夏"
       / "01_每日导出的重力仪原始数据" / "0701" / "914" / "914_20250701.txt")
OUT = HERE / "使用说明_img"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = _create_app() or QApplication.instance()
    ensure_cjk_font()

    win = MainWindow(settings_path=OUT / "_tmp_settings.json")
    win.resize(1680, 980)
    win.show()
    if SRC.exists():
        win.load_file(str(SRC))
    for _ in range(10):
        app.processEvents()

    shots = []
    p = OUT / "screenshot_main.png"
    win.grab().save(str(p))
    shots.append(p)

    # ② 条件面板特写（从主界面裁）+ ④ 结果表特写
    from PIL import Image

    big = Image.open(p)
    sx = big.width / max(win.width(), 1)
    sy = big.height / max(win.height(), 1)

    def crop(widget, name: str) -> Path:
        g = widget.geometry()
        tl = widget.mapTo(win, g.topLeft() - g.topLeft())        # 窗口内位置
        box = (int(tl.x() * sx), int(tl.y() * sy),
               int((tl.x() + g.width()) * sx), int((tl.y() + g.height()) * sy))
        out = OUT / name
        big.crop(box).save(out)
        return out

    shots.append(crop(win.tbl_cond.parentWidget(), "screenshot_conditions.png"))
    shots.append(crop(win.table.parentWidget(), "screenshot_table.png"))

    # 独立窗口：表格 + 图形
    win.btn_float_both.click()
    for _ in range(10):
        app.processEvents()
    fw = win._float_wins.get("both")
    if fw is not None:
        p2 = OUT / "screenshot_float.png"
        fw.grab().save(str(p2))
        shots.append(p2)
        fw.close()
        for _ in range(6):
            app.processEvents()

    # 关于 / 作者信息
    dlg = AboutDialog(None, win.settings)
    dlg.resize(860, 720)
    dlg.show()
    for _ in range(6):
        app.processEvents()
    p3 = OUT / "screenshot_about.png"
    dlg.grab().save(str(p3))
    shots.append(p3)
    dlg.close()
    win.close()

    # 公众号二维码也放一份在说明书目录里（HTML 用相对路径引用）
    from pickersrc import appinfo

    qr = appinfo.qr_image_path()
    if qr is not None:
        import shutil
        dst = OUT / appinfo.WECHAT_QR_FILENAME
        if Path(qr).resolve() != dst.resolve():
            shutil.copyfile(qr, dst)
        shots.append(dst)

    for s in shots:
        print(f"  {s.relative_to(HERE)}  {s.stat().st_size} 字节")
    tmp = OUT / "_tmp_settings.json"
    if tmp.exists():
        tmp.unlink()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
