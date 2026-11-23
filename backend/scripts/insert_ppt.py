"""把 GIF 插入 PPT 指定页（默认第 11 页右侧空位）。

用法：
    py -3.12 scripts/insert_ppt.py demo.gif --ppt 你的演示文稿.pptx
    py -3.12 scripts/insert_ppt.py demo.gif --slide 11 --out test-copy.pptx
"""
from __future__ import annotations

import argparse
import shutil
import sys
import time
from pathlib import Path

from PIL import Image
from pptx import Presentation
from pptx.util import Inches


def insert(gif: str, ppt: str, slide_no: int = 11,
           left: float = 9.62, top: float = 1.78, width: float = 3.24,
           out: str = "") -> Path:
    gif_path = Path(gif)
    if not gif_path.exists():
        raise FileNotFoundError(f"GIF 不存在: {gif}")
    prs = Presentation(ppt)
    if not 1 <= slide_no <= len(prs.slides):
        raise ValueError(f"页码越界: {slide_no}（共 {len(prs.slides)} 页）")
    slide = prs.slides[slide_no - 1]
    slide_w = prs.slide_width / 914400
    slide_h = prs.slide_height / 914400

    with Image.open(gif_path) as im:
        w_px, h_px = im.size
    height = width * h_px / w_px
    if top + height > slide_h - 0.4:          # 超出页底则等比缩减
        height = slide_h - 0.4 - top
        width = height * w_px / h_px
    if left + width > slide_w - 0.3:          # 超出页右则左移
        left = slide_w - 0.3 - width

    slide.shapes.add_picture(str(gif_path), Inches(left), Inches(top),
                             width=Inches(width), height=Inches(height))

    out_path = Path(out) if out else Path(ppt)
    if out_path == Path(ppt):
        bak = Path(ppt).with_name(
            f"{Path(ppt).stem}.bak-{time.strftime('%Y%m%d-%H%M%S')}.pptx")
        shutil.copy2(ppt, bak)
        print(f"原 PPT 已备份: {bak}")
    prs.save(out_path)
    print(f"已插入 {gif_path.name} → 第 {slide_no} 页 "
          f"({left:.2f},{top:.2f}) {width:.2f}x{height:.2f} in → {out_path}")
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="GIF 插入 PPT")
    ap.add_argument("gif")
    ap.add_argument("--ppt", required=True, help="目标演示文稿 .pptx")
    ap.add_argument("--slide", type=int, default=11)
    ap.add_argument("--left", type=float, default=9.62)
    ap.add_argument("--top", type=float, default=1.78)
    ap.add_argument("--width", type=float, default=3.24)
    ap.add_argument("--out", default="", help="输出 pptx（默认原地+自动备份）")
    args = ap.parse_args()
    insert(args.gif, args.ppt, args.slide, args.left, args.top,
           args.width, args.out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
