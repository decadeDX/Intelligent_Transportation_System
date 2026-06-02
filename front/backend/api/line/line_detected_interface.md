# line_detected_interface.py 文件解析

## 1. 文件概述

`line_detected_interface.py` 是车道线检测相关的 FastAPI 接口模块，主要提供图片车道线检测、视频车道线流式检测、实时最新帧查询和任务状态查询能力。

该文件使用传统计算机视觉算法完成车道线识别，核心流程为：

1. 图像灰度化。
2. 高斯模糊降噪。
3. Canny 边缘检测。
4. 构建梯形 ROI 掩膜，只保留道路下半部分的候选区域。
5. 使用 HoughLinesP 提取直线段。
6. 根据斜率和位置区分左车道线、右车道线。
7. 对左右车道线分别拟合平均线，并绘制到原图或视频帧上。

## 2. 主要依赖

| 依赖 | 作用 |
| --- | --- |
| `cv2` | 图像读取、视频读写、边缘检测、霍夫直线检测、绘制结果 |
| `numpy` | ROI 掩膜构造、线段拟合计算 |
| `fastapi` | 定义文件上传、表单参数、查询参数接口 |
| `JSONResponse` | 返回普通 JSON 响应 |
| `StreamingResponse` | 返回 NDJSON 流式视频检测结果 |
| `ThreadPoolExecutor` | 后台处理视频检测任务 |
| `threading.Lock` | 保护最新帧缓存的并发读写 |
| `utils.myutils.writ2json` | 将接口响应写入 `result.json` |

## 3. 全局配置与缓存

| 名称 | 类型 | 说明 |
| --- | --- | --- |
| `FRAME_DETECT_INTERVAL_DEFAULT` | `int` | 视频接口默认帧间隔参数，当前默认值为 `3` |
| `STREAM_JPEG_QUALITY` | `int` | 流式返回帧的 JPEG 编码质量，当前为 `50` |
| `latest_frames` | `dict` | 以 `task_id` 为键缓存最新一帧的 base64 JPEG |
| `latest_frame_meta` | `dict` | 以 `task_id` 为键缓存最新帧的元信息 |
| `processing_status` | `dict` | 记录视频任务状态，如 `processing`、`done`、`error` |
| `line_stream_results` | `dict` | 保存视频任务最终结果或错误信息 |
| `frame_lock` | `threading.Lock` | 保护帧缓存读写 |
| `executor` | `ThreadPoolExecutor` | 后台线程池，最大并发任务数为 `2` |

注意：`frame_interval` 参数会写入结果和开始事件，但当前视频处理逻辑仍然逐帧执行检测，并未按该参数跳帧。

## 4. 辅助函数说明

### `_ndjson_line(payload: dict) -> str`

将字典序列化为一行 NDJSON 字符串，末尾追加换行符。

### `_result_json_url(result_dir: Path) -> str`

返回检测结果目录下 `result.json` 的路径字符串，并将 Windows 反斜杠替换为 URL 更友好的 `/`。

### `_save_line_api_response(result_dir: Path, response_body: dict) -> str`

确保结果目录存在，将接口响应写入 `result.json`，并返回该 JSON 文件路径。

### `_encode_frame_jpeg_base64(frame) -> str`

将 OpenCV 图像帧编码为 JPEG，再转换为 base64 字符串，供前端实时显示视频检测帧。

### `_roi_mask(img_height: int, img_width: int) -> np.ndarray`

生成梯形 ROI 掩膜。梯形区域顶点为：

| 顶点 | 坐标含义 |
| --- | --- |
| 左下 | `(0, img_height)` |
| 左上 | `(0.4 * img_width, 0.6 * img_height)` |
| 右上 | `(0.6 * img_width, 0.6 * img_height)` |
| 右下 | `(img_width, img_height)` |

该掩膜用于过滤画面上半部分和非道路区域。

### `_separate_lines(lines, img_width: int) -> Tuple[List, List]`

根据霍夫变换得到的线段斜率和线段中点位置，将线段分为左车道线候选和右车道线候选：

| 条件 | 分类 |
| --- | --- |
| `abs(slope) < 0.3` | 过滤，认为过于水平 |
| `slope < 0` 且线段中点在画面左半边 | 左车道线 |
| `slope > 0` 且线段中点在画面右半边 | 右车道线 |

### `_avg_line(lines: List, img_height: int) -> Tuple[int, int, int, int] | None`

对同一侧的候选线段做拟合，得到一条平均车道线，并外推到 ROI 的上下边界：

- 下边界：`y = img_height`
- 上边界：`y = 0.6 * img_height`

返回格式为 `(x_bottom, y_bottom, x_top, y_top)`。

### `detect_lines(frame) -> Tuple[np.ndarray, bool, int]`

单帧车道线检测核心函数。

处理步骤：

1. 获取图像尺寸。
2. 转灰度图。
3. 高斯模糊。
4. Canny 边缘检测，阈值为 `50` 和 `150`。
5. 应用梯形 ROI 掩膜。
6. 使用 `cv2.HoughLinesP` 检测线段：
   - `rho = 1`
   - `theta = np.pi / 180`
   - `threshold = 50`
   - `minLineLength = 80`
   - `maxLineGap = 60`
7. 区分左右车道线。
8. 对左右车道线分别拟合平均线。
9. 使用绿色粗线绘制检测结果。
10. 将标注层和原图融合。

返回值：

| 返回值 | 类型 | 说明 |
| --- | --- | --- |
| `annotated_frame` | `np.ndarray` | 已绘制车道线的图像 |
| `lines_detected` | `bool` | 是否检测到至少一条车道线 |
| `line_count` | `int` | 检测到的平均车道线数量，范围通常为 `0` 到 `2` |

### `_read_video_metadata(video_path: Path) -> tuple`

读取上传视频的基础元数据，包括 FPS、宽度、高度和总帧数。如果视频无法打开，则抛出 `ValueError`。

### `process_line_video_stream_task(...)`

后台线程执行的视频检测任务。

主要职责：

1. 打开输入视频。
2. 创建输出 MP4 视频写入器。
3. 逐帧调用 `detect_lines`。
4. 将标注帧写入输出视频。
5. 更新检测统计信息。
6. 将最新标注帧编码为 base64 JPEG 并写入全局缓存。
7. 任务完成后写入 `result.json`。
8. 更新任务状态为 `done` 或 `error`。

最终统计字段：

| 字段 | 说明 |
| --- | --- |
| `session_id` | 当前视频检测任务 ID |
| `processed_frames` | 实际处理帧数 |
| `frame_interval` | 接口传入的帧间隔参数 |
| `fps` | 视频帧率 |
| `lines_detected_frames` | 检测到车道线的帧数量 |
| `max_lines` | 单帧最多检测到的平均车道线数量 |
| `avg_lines_per_detected_frame` | 有检测结果帧中的平均车道线数量 |
| `url` | 输出视频路径 |
| `result_dir` | 结果目录 |
| `result_json` | 结果 JSON 文件路径 |

### `_line_ndjson_generator(task_id: str, start_payload: dict)`

异步生成 NDJSON 流式响应。事件类型包括：

| event | 说明 |
| --- | --- |
| `start` | 任务已启动，返回任务 ID 和视频元信息 |
| `frame` | 推送最新处理帧，包含 base64 JPEG 和车道线数量 |
| `done` | 任务完成，返回最终统计结果 |
| `error` | 任务失败，返回错误信息 |

## 5. 路由注册函数

### `register_line_routes(app)`

向传入的 FastAPI 应用实例注册车道线检测相关接口。该文件本身不直接创建 `FastAPI()` 实例，需要在主程序中调用：

```python
from api.line.line_detected_interface import register_line_routes

register_line_routes(app)
```

## 6. API 接口说明

### 6.1 图片车道线检测

**接口**

```http
POST /lineDetected
```

**请求类型**

`multipart/form-data`

**参数**

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | `UploadFile` | 是 | 待检测图片 |

**处理流程**

1. 图片保存到 `upload/source/{filename}`。
2. 使用 OpenCV 读取图片。
3. 调用 `detect_lines` 检测车道线。
4. 标注图片保存到 `upload/detected/{uuid}/line_{filename}`。
5. 响应内容写入 `upload/detected/{uuid}/result.json`。

**成功响应示例**

```json
{
  "code": 200,
  "msg": "line Detected Success",
  "data": {
    "line_count": 2,
    "has_lines": true,
    "url": "upload/detected/{uuid}/line_image.jpg",
    "result_dir": "upload/detected/{uuid}",
    "result_json": "upload/detected/{uuid}/result.json"
  }
}
```

**失败响应示例**

```json
{
  "code": 500,
  "msg": "无法读取图像",
  "data": null
}
```

### 6.2 视频逐帧流式车道线检测

**接口**

```http
POST /lineVideoDetectedWithFrame
```

**请求类型**

`multipart/form-data`

**参数**

| 参数名 | 类型 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- | --- |
| `file` | `UploadFile` | 是 | 无 | 待检测视频 |
| `frame_interval` | `int` | 否 | `3` | 帧间隔参数，当前仅记录到结果中 |

**响应类型**

`application/x-ndjson`

**处理流程**

1. 视频保存到 `upload/source/{filename}`。
2. 读取视频 FPS、宽、高、总帧数。
3. 创建唯一 `task_id`。
4. 后台线程执行逐帧检测。
5. 接口立即返回 NDJSON 流。
6. 前端可持续读取 `start`、`frame`、`done` 或 `error` 事件。

**start 事件示例**

```json
{
  "event": "start",
  "code": 200,
  "msg": "Stream started",
  "data": {
    "session_id": "{task_id}",
    "fps": 25,
    "width": 1280,
    "height": 720,
    "total_frames": 300,
    "frame_interval": 3
  }
}
```

**frame 事件示例**

```json
{
  "event": "frame",
  "code": 200,
  "msg": "Frame processed",
  "data": {
    "frame_index": 12,
    "line_count": 2,
    "has_lines": true,
    "frame_jpeg_base64": "/9j/4AAQSkZJRgABAQ..."
  }
}
```

**done 事件示例**

```json
{
  "event": "done",
  "code": 200,
  "msg": "line video stream detected success",
  "data": {
    "session_id": "{task_id}",
    "processed_frames": 300,
    "frame_interval": 3,
    "fps": 25,
    "lines_detected_frames": 280,
    "max_lines": 2,
    "avg_lines_per_detected_frame": 1.95,
    "url": "upload/detected/{task_id}/line_video.mp4",
    "result_dir": "upload/detected/{task_id}",
    "result_json": "upload/detected/{task_id}/result.json"
  }
}
```

**error 事件示例**

```json
{
  "event": "error",
  "code": 500,
  "msg": "Task failed",
  "data": null
}
```

### 6.3 获取视频检测最新帧

**接口**

```http
GET /getlineLatestFrame
```

**查询参数**

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | `str` | 是 | 视频流式检测任务 ID |

**成功响应示例**

```json
{
  "frame": "/9j/4AAQSkZJRgABAQ..."
}
```

**未获取到帧时响应**

```json
{
  "frame": null,
  "msg": "Processing not started or frame not ready"
}
```

### 6.4 查询视频任务状态

**接口**

```http
GET /lineVideoStatus
```

**查询参数**

| 参数名 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `task_id` | `str` | 是 | 视频流式检测任务 ID |

**响应示例**

```json
{
  "task_id": "{task_id}",
  "status": "done",
  "result": {
    "session_id": "{task_id}",
    "processed_frames": 300,
    "frame_interval": 3,
    "fps": 25,
    "lines_detected_frames": 280,
    "max_lines": 2,
    "avg_lines_per_detected_frame": 1.95,
    "url": "upload/detected/{task_id}/line_video.mp4",
    "result_dir": "upload/detected/{task_id}",
    "result_json": "upload/detected/{task_id}/result.json"
  },
  "output_path": "upload/detected/{task_id}/line_video.mp4"
}
```

`status` 可能值：

| 状态 | 说明 |
| --- | --- |
| `processing` | 任务处理中 |
| `done` | 任务完成 |
| `error` | 任务失败 |
| `not_found` | 未找到任务 |

## 7. 文件输出位置

| 类型 | 路径 |
| --- | --- |
| 上传源文件 | `upload/source/{filename}` |
| 图片检测结果 | `upload/detected/{uuid}/line_{filename}` |
| 视频检测结果 | `upload/detected/{task_id}/line_{video_stem}.mp4` |
| JSON 结果文件 | `upload/detected/{uuid_or_task_id}/result.json` |

## 8. 算法特点

优点：

- 不依赖深度学习模型，部署成本较低。
- 单帧处理逻辑清晰，适合道路场景的基础车道线识别。
- 视频接口支持实时推送标注帧，便于前端做进度展示。

局限：

- 对摄像头角度、道路区域位置和光照比较敏感。
- ROI 区域是固定比例梯形，不适合所有道路视角。
- 只能拟合左、右两条主车道线，不支持复杂车道结构。
- 车道线颜色、阴影、遮挡、弯道等情况可能影响 Hough 检测效果。
- 全局字典缓存未做过期清理，长时间运行可能积累任务数据。

## 9. 可改进点

1. 让 `frame_interval` 真正参与视频检测，例如每隔 N 帧检测一次，其余帧复用最近结果或直接写原帧。
2. 为 `latest_frames`、`latest_frame_meta`、`processing_status` 和 `line_stream_results` 增加任务过期清理机制。
3. 对上传文件名做更严格的安全处理，避免同名覆盖和异常文件名问题。
4. 增加文件类型校验，区分图片接口和视频接口的可接受格式。
5. 将 Canny、Hough 和 ROI 参数配置化，便于不同摄像头场景调参。
6. 对输出视频编码格式增加兼容性处理，例如根据运行环境选择可用编码器。
7. 如果需要更强鲁棒性，可以引入深度学习分割模型或车道线检测模型。

