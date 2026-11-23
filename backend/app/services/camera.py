"""相机 SDK 适配层：opencv 通用相机 / 海康 MVS 接入点 / Basler pypylon 接入点。

适配器协议：open() / read()->frame(BGR ndarray)|None / release()。
新增相机只需 @register 一个类，source.py 与界面（设置页 camera.adapter）即自动可用。
"""
from __future__ import annotations

import threading

import cv2
import numpy as np

_ADAPTERS: dict = {}


def register(name: str):
    def deco(cls):
        _ADAPTERS[name] = cls
        return cls
    return deco


def adapters() -> list[str]:
    return sorted(_ADAPTERS)


def create(name: str, **kwargs):
    cls = _ADAPTERS.get(name)
    if cls is None:
        raise ValueError(f"未知相机适配器: {name}（可用: {', '.join(adapters())}）")
    return cls(**kwargs)


# ------------------------------------------------------------------ 通用 CV 相机
@register("opencv")
class OpenCvCamera:
    """通用 USB/GigE 相机（DirectShow 优先，回退默认后端）。"""

    def __init__(self, index: int = 0, width: int = 0, height: int = 0,
                 **_ignore) -> None:
        self.index = int(index)
        self.width = int(width)
        self.height = int(height)
        self._cap = None

    def open(self) -> None:
        backend = getattr(cv2, "CAP_DSHOW", cv2.CAP_ANY)
        self._cap = cv2.VideoCapture(self.index, backend)
        if not self._cap.isOpened():
            self._cap = cv2.VideoCapture(self.index)
        if not self._cap.isOpened():
            raise RuntimeError(
                f"无法打开相机 index={self.index}（检查驱动/占用/权限）")
        if self.width:
            self._cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
        if self.height:
            self._cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

    def read(self):
        if self._cap is None:
            return None
        ok, frame = self._cap.read()
        return frame if ok else None

    def release(self) -> None:
        if self._cap is not None:
            self._cap.release()
            self._cap = None


# ------------------------------------------------------------------ 海康 MVS 接入点
@register("hikrobot")
class HikRobotCamera:
    """海康线阵/面阵相机接入点（MVS SDK，MvCameraControl_class）。

    接线步骤（参考 HIKONCam 的 MvCamera 封装路线，仅借鉴流程）：
    1. 安装海康 MVS 客户端；将其 Development/Includes 与 win64 库目录加入环境；
       把 MVS 的 Python 示例包（MvImport 目录）加入 PYTHONPATH；
    2. 本适配器已实现：枚举设备（序列号匹配优先）→ 取流（MV_CC_GetImageBuffer
       轮询）→ MV_CC_ConvertPixelType 转 BGR8 → numpy 帧；释放时停流关设备；
    3. 线阵参数（触发模式/行频/曝光/UserSet1 保存）在实机联调阶段用 MVS 客户端
       预设，或按需在 open() 后追加 MV_CC_Set* 调用。
    未安装 SDK 时将抛出带指引的 RuntimeError，不影响其余功能。
    """

    def __init__(self, serial: str = "", **_ignore) -> None:
        self.serial = str(serial or "")
        self._cam = None
        self._mv = None
        self._lock = threading.Lock()

    def open(self) -> None:
        try:
            import MvCameraControl_class as mv  # type: ignore
        except ImportError as exc:
            raise RuntimeError(
                "未找到海康 MVS SDK（MvCameraControl_class）。请安装 MVS 客户端，"
                "并将 MVS Python 示例 MvImport 目录加入 PYTHONPATH") from exc
        self._mv = mv
        dev_list = mv.MV_CC_DEVICE_INFO_LIST()
        ret = mv.MvCamera.MV_CC_EnumDevices(
            mv.MV_GIGE_DEVICE | mv.MV_USB_DEVICE, dev_list)
        if ret != 0 or dev_list.nDeviceNum == 0:
            raise RuntimeError(f"未枚举到海康相机（ret=0x{ret:x}）")
        cam = mv.MvCamera()
        for i in range(dev_list.nDeviceNum):
            info = dev_list.pDeviceInfo[i]
            ret = cam.MV_CC_CreateHandle(info)
            if ret != 0:
                raise RuntimeError(f"MV_CC_CreateHandle 失败（ret=0x{ret:x}）")
            if self.serial:
                st_param = mv.MVCC_INTVALUE()
                cam.MV_CC_GetIntValue("DeviceSerialNumber", st_param)
                if getattr(st_param, "nCurValue", 0) != int(self.serial or 0):
                    cam.MV_CC_DestroyHandle()
                    continue
            ret = cam.MV_CC_OpenDevice(mv.MV_ACCESS_Exclusive, 0)
            if ret != 0:
                cam.MV_CC_DestroyHandle()
                continue
            ret = cam.MV_CC_StartGrabbing()
            if ret != 0:
                cam.MV_CC_CloseDevice()
                cam.MV_CC_DestroyHandle()
                continue
            self._cam = cam
            return
        raise RuntimeError("海康相机打开失败（序列号不匹配或均被占用）")

    def read(self):
        with self._lock:
            if self._cam is None:
                return None
            mv = self._mv
            st_frame = mv.MV_FRAME_OUT()
            ret = self._cam.MV_CC_GetImageBuffer(st_frame, 1000)
            if ret != 0:
                return None
            try:
                w = int(st_frame.stFrameInfo.nWidth)
                h = int(st_frame.stFrameInfo.nHeight)
                src_type = st_frame.stFrameInfo.enPixelType
                param = mv.MV_CC_PIXEL_CONVERT_PARAM()
                dst_size = w * h * 3
                dst_buf = (bytes(dst_size))
                param.nWidth = w
                param.nHeight = h
                param.pSrcData = st_frame.pBufAddr
                param.nSrcDataLen = int(st_frame.stFrameInfo.nFrameLen)
                param.enSrcPixelType = src_type
                param.enDstPixelType = mv.PixelType_Gvsp_BGR8_Packed
                param.pDstBuffer = dst_buf
                param.nDstBufferSize = dst_size
                ret = self._cam.MV_CC_ConvertPixelType(param)
                if ret != 0:
                    return None
                frame = np.frombuffer(dst_buf, dtype=np.uint8, count=dst_size)
                return frame.reshape(h, w, 3).copy()
            finally:
                self._cam.MV_CC_FreeImageBuffer(st_frame)

    def release(self) -> None:
        with self._lock:
            if self._cam is None:
                return
            self._cam.MV_CC_StopGrabbing()
            self._cam.MV_CC_CloseDevice()
            self._cam.MV_CC_DestroyHandle()
            self._cam = None


# ------------------------------------------------------------------ Basler pypylon 接入点
@register("pypylon")
class PypylonCamera:
    """Basler 相机接入点（pip install pypylon）。"""

    def __init__(self, serial: str = "", **_ignore) -> None:
        self.serial = str(serial or "")
        self._cam = None
        self._pylon = None

    def open(self) -> None:
        try:
            from pypylon import pylon
        except ImportError as exc:
            raise RuntimeError("未安装 pypylon（pip install pypylon）") from exc
        self._pylon = pylon
        factory = pylon.TlFactory.GetInstance()
        devices = factory.EnumerateDevices()
        if not devices:
            raise RuntimeError("未发现 Basler 相机")
        dev = devices[0]
        if self.serial:
            for d in devices:
                if d.GetSerialNumber() == self.serial:
                    dev = d
                    break
        self._cam = pylon.InstantCamera(factory.CreateDevice(dev))
        self._cam.Open()

    def read(self):
        if self._cam is None:
            return None
        grab = self._cam.RetrieveResult(
            1000, self._pylon.TimeoutHandling_Return)
        if grab is None or not grab.IsGrabbed():
            return None
        try:
            arr = grab.GetArray()
            if arr is not None and arr.ndim == 3 and arr.shape[2] == 4:
                return cv2.cvtColor(arr, cv2.COLOR_BGRA2BGR)
            return arr
        finally:
            grab.Release()

    def release(self) -> None:
        if self._cam is not None:
            if self._cam.IsOpen():
                self._cam.Close()
            self._cam = None
