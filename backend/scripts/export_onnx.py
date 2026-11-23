"""模型部署导出：ONNX（供 CPU / CUDA / TensorRT-EP）与 TensorRT engine。

用法：
    # 1) 导出 ONNX（任意机器，不需要 GPU；本系统推荐默认路径）
    python scripts/export_onnx.py --weights <best.pt> --out <best.onnx>

    # 2) 导出 ONNX FP16（onnxruntime CPU 不支持 FP16，仅 GPU/TensorRT-EP 使用）
    python scripts/export_onnx.py --weights <best.pt> --half

    # 3) 直接导出 TensorRT engine（必须在目标机器执行，GPU 型号 + TensorRT
    #    版本绑定，与 HIKONCam 的 .engine 工程口径一致）
    python scripts/export_onnx.py --weights <best.pt> --engine

说明：
- 本系统的推理后端选择见『系统设置 → infer_providers』：
  auto / tensorrt / cuda / cpu，onnxruntime 会自动降级到可用 provider；
- 加载 .engine 还需 tensorrt + pycuda（pip install tensorrt pycuda）。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(description="模型部署导出（ONNX / TensorRT engine）")
    ap.add_argument("--weights", required=True, help="训练产出的 best.pt 路径")
    ap.add_argument("--out", default="", help="输出路径（默认 ultralytics 自动命名）")
    ap.add_argument("--imgsz", type=int, default=640)
    ap.add_argument("--half", action="store_true", help="导出 FP16（供 GPU/TensorRT-EP）")
    ap.add_argument("--engine", action="store_true", help="导出 TensorRT engine（需 GPU + tensorrt）")
    args = ap.parse_args()

    if not Path(args.weights).exists():
        print(f"权重不存在: {args.weights}")
        return 1

    from ultralytics import YOLO

    model = YOLO(args.weights)
    fmt = "engine" if args.engine else "onnx"
    kwargs = dict(format=fmt, imgsz=args.imgsz, dynamic=False,
                  simplify=True, half=args.half)
    if fmt == "engine":
        kwargs["device"] = 0
        print("正在导出 TensorRT engine（首次编译可能耗时数分钟）…")
    else:
        print("正在导出静态形状 ONNX…")

    path = model.export(**kwargs)
    path = Path(str(path))
    out = Path(args.out) if args.out else path
    if args.out and str(out) != str(path):
        shutil.copy(path, out)

    print(f"导出完成: {out}")
    if fmt == "onnx":
        print("组装完成。在部署机安装 onnxruntime（或 onnxruntime-gpu）后，")
        print("把 config.json 的 model_path 指向该 .onnx，infer_providers 选 auto 即可。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
