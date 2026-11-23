"""录屏视频 → GIF 转换（cv2 解码 + PIL 调色板压缩，无需 ffmpeg）。

用法：
    py -3.12 scripts/video_to_gif.py docs/rec/demo.mp4
    py -3.12 scripts/video_to_gif.py in.webm -o out.gif --fps 10 --width 960 --start 3 --end 45
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import cv2
from PIL import Image


def convert(video: str, out: str, fps: float = 10.0, width: int = 960,
            start: float = 0.0, end: float = 0.0, colors: int = 128) -> Path:
    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise FileNotFoundError(f"无法打开视频: {video}")
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 15.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    t_end = end if end > 0 else (total / src_fps if total else float("inf"))
    step = max(1, round(src_fps / fps))
    scale = min(1.0, width / src_w) if src_w else 1.0
    size = (max(1, round(src_w * scale)), max(1, round(src_h * scale)))

    frames: list[Image.Image] = []
    idx = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        t = idx / src_fps
        idx += 1
        if t < start:
            continue
        if t > t_end:
            break
        if idx % step:
            continue
        img = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        if size != (src_w, src_h):
            img = img.resize(size, Image.LANCZOS)
        frames.append(img.convert("P", palette=Image.ADAPTIVE, colors=colors))
    cap.release()
    if not frames:
        raise RuntimeError("未采集到任何帧（检查 start/end 参数）")

    out_path = Path(out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    frames[0].save(out_path, save_all=True, append_images=frames[1:],
                   duration=round(1000 / fps), loop=0, optimize=True)
    return out_path


def main() -> int:
    ap = argparse.ArgumentParser(description="录屏视频转 GIF")
    ap.add_argument("video")
    ap.add_argument("-o", "--out", default="",
                    help="输出 gif 路径（默认与视频同目录同名 .gif）")
    ap.add_argument("--fps", type=float, default=10.0)
    ap.add_argument("--width", type=int, default=960)
    ap.add_argument("--start", type=float, default=0.0, help="起始秒（剪辑）")
    ap.add_argument("--end", type=float, default=0.0, help="结束秒（0=到结尾）")
    args = ap.parse_args()

    out = args.out or str(Path(args.video).with_suffix(".gif"))
    path = convert(args.video, out, args.fps, args.width,
                   args.start, args.end)
    size_mb = path.stat().st_size / 1e6
    print(f"GIF 已生成: {path}（{size_mb:.2f} MB）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
