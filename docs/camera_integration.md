# 相机接入指南（services/camera.py）

系统帧源支持四种形态：`相机 / 视频文件 / 图像目录 / 合成帧`。相机走
`services/camera.py` 的可插拔适配器，在 `系统设置 → 相机` 中启用并选择适配器，
或在 `config.json` 中配置：

```json
"camera": {"enabled": true, "adapter": "opencv", "index": 0, "serial": ""}
```

已内置适配器：

| adapter | 说明 | 依赖 |
|---|---|---|
| `opencv` | 通用 USB/GigE 相机（DirectShow 优先） | opencv-python（必有） |
| `hikrobot` | 海康 MVS SDK 接线（轮询取流 + BGR8 转换） | 海康 MVS 客户端 + MvImport |
| `pypylon` | Basler 相机 | `pip install pypylon` |

## 海康 MVS 接线步骤

1. 安装海康 **MVS 客户端**（官方）。
2. 把 MVS 安装目录下 `Development\Includes` 与 `win64` 库目录加入环境变量
   （或拷贝 `MvCameraControl.dll` 到运行目录）。
3. 把 MVS 自带 Python 示例包 `MvImport/MvCameraControl_class.py` 所在目录加入
   `PYTHONPATH`（该模块由海康官方提供，本工程不分发）。
4. 本工程已实现：`MV_CC_EnumDevices`（GigE+USB）→ `MV_CC_CreateHandle`
   → `MV_CC_OpenDevice` → `MV_CC_StartGrabbing` → 轮询 `MV_CC_GetImageBuffer`
   → `MV_CC_ConvertPixelType`（BGR8）→ numpy 帧；释放时停流关设备。
5. 线阵相机参数（触发模式 / 行频 / 曝光 / UserSet0 保存）建议先用 MVS 客户端
   预设；联调接口在 `HikRobotCamera.open()` 之后，可追加 `MV_CC_Set*` 调用，
   工程口径与 HIKONCam 的相机参数页一致。

> 说明：`hikrobot` 适配器在无 SDK 环境会以带指引的 `RuntimeError` 退出，
> 不影响视频/目录/合成帧等其它数据源。实机联调时按现场相机补位少量参数设置即可。
> 若 `MvImport` 中字段命名有版本差异（如 `MV_CC_PIXEL_CONVERT_PARAM_EX`），
> 按 SDK 头文件同步调整字段名——逻辑不变。

## Basler pypylon

```powershell
pip install pypylon
```

适配器自动枚举第一台相机；`serial` 填写后按序列号匹配。取帧为
`RetrieveResult` 轮询，BGRA 自动转 BGR。

## 常见问题

- **相机被占用**：MVS / MVS Viewer 等软件独占设备时打开会失败，先关闭它们。
- **帧率不对**：相机帧率由硬件设置决定，界面 fps 只控制消费节奏。
- **多相机**：当前为单相机；多相机可扩展为多卷并行，`FrameSource` 已是独立实例。
