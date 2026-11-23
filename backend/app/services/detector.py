"""检测推理引擎：多后端（ONNX Runtime CPU/CUDA/TensorRT-EP、.engine）+ 大图切片融合。

工程口径迁移说明（仅借鉴设计，不复制上游代码）：
- HIKONCam（GPL-3.0）：大图 512/1024/2048 切片 + 5%~50% 重叠 + 合并统一 NMS；
- Ultralytics 导出约定：(4+nc, N) 输出，letterbox 预处理；
- Frigate（MIT）：推理后端可插拔、provider 自动降级思路。
"""
from __future__ import annotations

from pathlib import Path

import numpy as np


class Detection:
    __slots__ = ("cls_id", "conf", "xyxy")

    def __init__(self, cls_id, conf, xyxy) -> None:
        self.cls_id = int(cls_id)
        self.conf = float(conf)
        self.xyxy = [float(v) for v in xyxy]


def _nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = (x2 - x1 + 1e-6) * (y2 - y1 + 1e-6)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        xx1 = np.maximum(x1[i], x1[order[1:]])
        yy1 = np.maximum(y1[i], y1[order[1:]])
        xx2 = np.minimum(x2[i], x2[order[1:]])
        yy2 = np.minimum(y2[i], y2[order[1:]])
        inter = (np.maximum(0.0, xx2 - xx1) *
                 np.maximum(0.0, yy2 - yy1))
        iou = inter / (areas[i] + areas[order[1:]] - inter + 1e-6)
        order = order[np.where(iou <= iou_thr)[0] + 1]
    return keep


def available_providers() -> list[str]:
    try:
        import onnxruntime as ort
        return list(ort.get_available_providers())
    except Exception:
        return []


def _ordered_providers(mode: str, fp16: bool):
    cands = []
    if mode in ("auto", "tensorrt"):
        cands.append(("TensorrtExecutionProvider",
                      {"trt_fp16_enable": bool(fp16)}))
    if mode in ("auto", "cuda"):
        cands.append(("CUDAExecutionProvider", {}))
    cands.append(("CPUExecutionProvider", {}))
    return cands


class Detector:
    """统一推理接口。backend ∈ {onnxruntime, tensorrt-engine, pt}。"""

    def __init__(self, model_path: str, conf: float = 0.25, iou: float = 0.45,
                 imgsz: int = 640, class_names=None, providers: str = "auto",
                 fp16: bool = False, tiling: dict | None = None) -> None:
        self.conf = float(conf)
        self.iou = float(iou)
        self.imgsz = int(imgsz)
        self.class_names = list(class_names or [])
        self.provider_mode = providers or "auto"
        self.fp16 = bool(fp16)
        self.tiling = dict(tiling or {})
        self.backend = ""
        self.provider = ""
        self.name = Path(str(model_path)).name or "未配置模型"
        self.model = None
        self.input_name = ""
        self.names: dict[int, str] = {}
        self._load(str(model_path))

    # ------------------------------------------------------------------ 加载
    def _load(self, path: str) -> None:
        if not path:
            raise FileNotFoundError("模型路径为空，请在『系统设置』中配置")
        lower = path.lower()
        if lower.endswith(".onnx"):
            self._load_onnx(path)
        elif lower.endswith(".engine"):
            self._load_engine(path)
        else:
            self._load_pt(path)
        if not self.names and self.class_names:
            self.names = {i: n for i, n in enumerate(self.class_names)}

    def _load_onnx(self, path: str) -> None:
        import onnxruntime as ort

        opts = ort.SessionOptions()
        opts.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        avail = ort.get_available_providers()
        providers = []
        for name, popts in _ordered_providers(self.provider_mode, self.fp16):
            if name not in avail:
                continue
            providers.append((name, popts) if popts else name)
        if not providers:
            providers = ["CPUExecutionProvider"]
        self.model = ort.InferenceSession(path, sess_options=opts,
                                          providers=providers)
        self.input_name = self.model.get_inputs()[0].name
        self.backend = "onnxruntime"
        self.provider = self.model.get_providers()[0]
        self.names = ({i: n for i, n in enumerate(self.class_names)}
                      if self.class_names else {})

    def _load_engine(self, path: str) -> None:
        try:
            import tensorrt as trt
            import pycuda.autoinit  # noqa: F401  初始化 CUDA 上下文
            import pycuda.driver as cuda  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "加载 .engine 需要 tensorrt 与 pycuda，且引擎与 GPU 型号/"
                "TensorRT 版本绑定（须在目标机器上用 trtexec 生成）。"
                "可改用 ONNX + TensorRT EP 方案（infer_providers=tensorrt）") from exc
        logger = trt.Logger(trt.Logger.WARNING)
        with open(path, "rb") as f:
            blob = f.read()
        self.model = trt.Runtime(logger).deserialize_cuda_engine(blob)
        if self.model is None:
            raise RuntimeError("TensorRT 引擎反序列化失败（版本/平台不匹配？）")
        self.backend = "tensorrt-engine"
        self.provider = "TensorRT"
        self.names = ({i: n for i, n in enumerate(self.class_names)}
                      if self.class_names else {})

    def _load_pt(self, path: str) -> None:
        from ultralytics import YOLO

        self.model = YOLO(path)
        self.backend = "pt"
        self.provider = "PyTorch-CPU"
        self.names = dict(self.model.names)

    # ------------------------------------------------------------------ 推理
    def infer(self, frame: np.ndarray) -> list[Detection]:
        if self._tiling_active(frame):
            return self._infer_tiled(frame)
        return self._infer_raw(frame, 0, 0)

    def _tiling_active(self, frame: np.ndarray) -> bool:
        t = self.tiling
        if not t.get("enabled"):
            return False
        return max(frame.shape[0], frame.shape[1]) > int(t.get("trigger_min_side", 1280))

    def _infer_tiled(self, frame: np.ndarray) -> list[Detection]:
        tile = max(int(self.tiling.get("tile_size", 1024)), 320)
        overlap = min(max(float(self.tiling.get("overlap", 0.1)), 0.05), 0.5)
        step = max(int(tile * (1.0 - overlap)), 64)
        h, w = frame.shape[:2]
        pool: list[Detection] = []
        for y0 in range(0, h, step):
            for x0 in range(0, w, step):
                if x0 >= w or y0 >= h:
                    continue
                crop = frame[y0:min(y0 + tile, h), x0:min(x0 + tile, w)]
                if crop.shape[0] < 32 or crop.shape[1] < 32:
                    continue
                pool.extend(self._infer_raw(crop, x0, y0))
        if not pool:
            return []
        boxes = np.array([d.xyxy for d in pool], dtype=np.float32)
        scores = np.array([d.conf for d in pool], dtype=np.float32)
        cls = np.array([d.cls_id for d in pool], dtype=np.float32)
        offset = cls[:, None] * (max(h, w) * 2.0)
        keep = _nms(boxes + offset, scores, self.iou)
        return [pool[i] for i in keep]

    def _infer_raw(self, frame: np.ndarray, ox: int, oy: int) -> list[Detection]:
        if self.backend == "onnxruntime":
            return self._infer_onnx(frame, ox, oy)
        if self.backend == "tensorrt-engine":
            return self._infer_trt(frame, ox, oy)
        return self._infer_pt(frame, ox, oy)

    # ------------------------------------------------------------------ 预处理
    def _letterbox(self, frame: np.ndarray):
        import cv2

        h, w = frame.shape[:2]
        r = min(self.imgsz / max(h, 1), self.imgsz / max(w, 1))
        nh, nw = int(round(h * r)), int(round(w * r))
        resized = cv2.resize(frame, (nw, nh), interpolation=cv2.INTER_LINEAR)
        dw, dh = self.imgsz - nw, self.imgsz - nh
        top, left = dh // 2, dw // 2
        padded = cv2.copyMakeBorder(resized, top, dh - top, left, dw - left,
                                    cv2.BORDER_CONSTANT, value=(114, 114, 114))
        return padded, r, left, top

    # ------------------------------------------------------------------ 后处理
    def _decode_yolo(self, out: np.ndarray, r: float, pl: int, pt: int,
                     ox: int, oy: int, frame_hw) -> list[Detection]:
        if out.ndim == 3:
            out = out[0]
        if out.shape[0] < out.shape[1]:
            out = out.T
        if out.shape[1] < 5:
            return []
        boxes = out[:, :4]
        scores_all = out[:, 4:]
        cls = scores_all.argmax(1)
        conf = scores_all.max(1)
        mask = conf >= self.conf
        if not mask.any():
            return []
        boxes, conf, cls = boxes[mask], conf[mask], cls[mask]
        cx, cy, bw, bh = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
        xyxy = np.stack([
            (cx - bw / 2 - pl) / r + ox,
            (cy - bh / 2 - pt) / r + oy,
            (cx + bw / 2 - pl) / r + ox,
            (cy + bh / 2 - pt) / r + oy,
        ], axis=1)
        h, w = frame_hw
        xyxy[:, [0, 2]] = np.clip(xyxy[:, [0, 2]], 0, w)
        xyxy[:, [1, 3]] = np.clip(xyxy[:, [1, 3]], 0, h)
        off = cls.astype(np.float32)[:, None] * (max(h, w) * 2.0)
        keep = _nms(xyxy + off, conf, self.iou)
        return [Detection(int(cls[i]), float(conf[i]), xyxy[i]) for i in keep]

    # ------------------------------------------------------------------ ONNX
    def _infer_onnx(self, frame: np.ndarray, ox: int, oy: int) -> list[Detection]:
        import cv2

        padded, r, pl, pt = self._letterbox(frame)
        x = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        out = self.model.run(None, {self.input_name: x})[0]
        return self._decode_yolo(np.asarray(out), r, pl, pt, ox, oy,
                                 frame.shape[:2])

    # ------------------------------------------------------------------ TensorRT engine
    def _infer_trt(self, frame: np.ndarray, ox: int, oy: int) -> list[Detection]:
        import cv2
        import tensorrt as trt
        import pycuda.driver as cuda

        padded, r, pl, pt = self._letterbox(frame)
        x = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
        x = np.ascontiguousarray(x.transpose(2, 0, 1)[None])
        engine = self.model
        ctx = engine.create_execution_context()
        input_name = ""
        for i in range(engine.num_io_tensors):
            name = engine.get_tensor_name(i)
            if engine.get_tensor_mode(name) == trt.TensorIOMode.INPUT:
                input_name = name
        d_in = cuda.mem_alloc(x.nbytes)
        outputs: list[tuple[np.ndarray, int]] = []
        stream = cuda.Stream()
        try:
            cuda.memcpy_htod(d_in, x)
            ctx.set_tensor_address(input_name, int(d_in))
            for i in range(engine.num_io_tensors):
                name = engine.get_tensor_name(i)
                if name == input_name:
                    continue
                shape = tuple(engine.get_tensor_shape(name))
                buf = np.zeros(shape, dtype=np.float32)
                mem = cuda.mem_alloc(buf.nbytes)
                ctx.set_tensor_address(name, int(mem))
                outputs.append((buf, mem))
            if hasattr(ctx, "execute_async_v3"):
                ctx.execute_async_v3(stream_handle=stream.handle)
            else:
                ctx.execute_async_v2(
                    bindings=[int(d_in)] + [int(m) for _, m in outputs],
                    stream_handle=stream.handle)
            stream.synchronize()
            for buf, mem in outputs:
                cuda.memcpy_dtoh(buf, mem)
            return self._decode_yolo(outputs[0][0], r, pl, pt, ox, oy,
                                     frame.shape[:2])
        finally:
            for _, mem in outputs:
                cuda.mem_free(mem)
            cuda.mem_free(d_in)

    # ------------------------------------------------------------------ PyTorch CPU
    def _infer_pt(self, frame: np.ndarray, ox: int, oy: int) -> list[Detection]:
        result = self.model.predict(
            frame, conf=self.conf, iou=self.iou, imgsz=self.imgsz,
            device="cpu", verbose=False)[0]
        dets = []
        for box in result.boxes:
            xy = [float(v) for v in box.xyxy[0].tolist()]
            dets.append(Detection(int(box.cls[0]), float(box.conf[0]),
                                  [xy[0] + ox, xy[1] + oy, xy[2] + ox, xy[3] + oy]))
        return dets
