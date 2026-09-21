# -*- coding: utf-8 -*-
"""生成 CG5 数据挑选的图标（纯 Pillow，可重复跑）。

风格与课题组其它小软件（SHKit / SHSynth）一致：**深藏青圆环 + 浅色内盘**，
里面画这件工具干的事 —— 一排读数点里"挑出"的那一个（琥珀色高亮）。

用法：
    python resources/make_icon.py          # 生成 cg5picker.ico / cg5picker_256.png
"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent

RING = (22, 39, 63, 255)          # 深藏青圆环（与 SHSynth 图标同一族）
DISC = (244, 247, 251, 255)       # 内盘浅色
AXIS = (147, 163, 184, 255)       # 坐标轴
DROP = (154, 168, 187, 255)       # 被剔除的读数（灰）
KEEP = (242, 211, 74, 255)        # 保留（淡黄，与表格底纹同色系）
PICK = (255, 196, 0, 255)         # 最终取值（琥珀高亮，与"选中行"同色）
CURVE = (31, 111, 208, 255)       # 读数曲线（蓝）

S = 4                             # 先画 4 倍再缩，边缘才干净
N = 256


def _pts() -> list[tuple[float, float]]:
    """一排读数点（x, y 为 0~1 归一化，y 向上为正）。"""
    return [(0.10, 0.42), (0.26, 0.50), (0.42, 0.46),
            (0.58, 0.62), (0.74, 0.58), (0.90, 0.72)]


def draw(size: int = N * S) -> Image.Image:
    u = size / 256.0                       # 把 256 基准坐标换算到当前画布
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)

    cx = cy = size / 2
    d.ellipse([cx - 126 * u, cy - 126 * u, cx + 126 * u, cy + 126 * u], fill=RING)
    d.ellipse([cx - 112 * u, cy - 112 * u, cx + 112 * u, cy + 112 * u], fill=DISC)

    def px(x: float, y: float) -> tuple[float, float]:
        """归一化坐标 → 像素（内盘范围内留边）。"""
        return (cx + (x - 0.5) * 168 * u, cy + (0.5 - y) * 168 * u)

    # 坐标轴：一条横轴 + 一条竖轴
    x0, yb = px(0.04, 0.0)
    x1, _ = px(0.96, 0.0)
    _, yt = px(0.0, 0.96)
    d.line([x0, yb, x1, yb], fill=AXIS, width=int(5 * u))
    d.line([x0, yb, x0, yt], fill=AXIS, width=int(5 * u))

    # 读数曲线（平滑折线：相邻点插值）
    pts = [px(x, y) for x, y in _pts()]
    smooth: list[tuple[float, float]] = []
    for i in range(len(pts) - 1):
        (ax, ay), (bx, by) = pts[i], pts[i + 1]
        for k in range(21):
            t = k / 20
            smooth.append((ax + (bx - ax) * t, ay + (by - ay) * t))
    d.line(smooth, fill=CURVE, width=int(6 * u), joint="curve")

    # 读数点：剔除=灰、保留=淡黄、"最终取值"=琥珀（大一点，一眼看到"挑出来的那个"）
    for i, (x, y) in enumerate(_pts()):
        cxp, cyp = px(x, y)
        if i == 3:                                   # 挑中的那一个
            r = 17 * u
            d.ellipse([cxp - r, cyp - r, cxp + r, cyp + r], fill=PICK,
                      outline=RING, width=int(4 * u))
        else:
            r = 12 * u
            d.ellipse([cxp - r, cyp - r, cxp + r, cyp + r],
                      fill=KEEP if i in (4, 5) else DROP)
    return im


def main() -> int:
    big = draw()
    icon_png = big.resize((N, N), Image.LANCZOS)
    png = HERE / "cg5picker_256.png"
    icon_png.save(png)
    ico = HERE / "cg5picker.ico"
    icon_png.save(ico, sizes=[(16, 16), (24, 24), (32, 32), (48, 48),
                              (64, 64), (128, 128), (256, 256)])
    print(f"已写出：{png.name}（{os.path.getsize(png)} 字节）、"
          f"{ico.name}（{os.path.getsize(ico)} 字节）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
