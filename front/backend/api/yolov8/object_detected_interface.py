# yolo_interface.py
import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import AsyncGenerator, Optional

import cv2
from fastapi import File, Query, UploadFile, Form
from fastapi.responses import JSONResponse, StreamingResponse

from api.yolov8.yolo_detect_service import (
    MODEL_TYPES,
    annotate_plot_kwargs,
    get_available_model_types,
    get_model_names,
    normalize_class_name,
    plot_yolo_frame,
    predict_frame,
    predict_video_frame,
    resolve_target_id,
    run_image_detection,
)

FRAME_DETECT_INTERVAL_DEFAULT = 5
STREAM_JPEG_QUALITY = 50

# ====== 实时流式检测：后台线程 + 共享最新帧（对齐 traffic_interface_bak.py） ======
latest_frames = {}  # task_id -> base64 jpeg
latest_frame_meta = {}  # task_id -> {frame_index, numbers, detected}
processing_status = {}  # task_id -> "processing" | "done" | "error"
yolo_stream_results = {}  # task_id -> done 事件数据
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _encode_frame_jpeg_base64(frame) -> str:
    ok, buf = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
    )
    if not ok:
        return ""
    return base64.b64encode(buf).decode("utf-8")


def _read_video_metadata(video_path: Path) -> tuple[int, int, int, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("无法打开上传的视频文件")
    fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, width, height, total_frames


def process_yolo_video_stream_task(
    task_id: str,
    input_path: str,
    output_path: str,
    output_url: str,
    model_type: str,
    class_name: str,
    detect_all: bool,
    target_id: Optional[int],
    frame_interval: int,
):
    """后台线程：跳帧推理 + 缓存检测框 + YOLO 标准标注 + 更新 latest_frames。"""
    cap = None
    out = None

    try:
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            raise ValueError(f"无法打开视频: {input_path}")

        fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
        out = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
        if not out.isOpened():
            raise RuntimeError("无法创建输出视频文件，请检查 OpenCV 编解码器支持")

        processing_status[task_id] = "processing"

        frame_count = 0
        frame_index = 0
        total_count = 0
        cached_result = None
        plot_kwargs = annotate_plot_kwargs((height, width, 3))

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            run_detect = frame_count == 1 or frame_count % frame_interval == 0
            frame_numbers = 0

            if run_detect:
                cached_result, frame_numbers = predict_frame(
                    model_type, frame, detect_all, target_id
                )
                total_count += frame_numbers
                annotated = plot_yolo_frame(frame, plot_kwargs, cached_result)
            elif cached_result is not None:
                annotated = plot_yolo_frame(frame, plot_kwargs, cached_result, cached_result)
            else:
                annotated = frame
            out.write(annotated)

            jpg_as_text = _encode_frame_jpeg_base64(annotated)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "numbers": frame_numbers,
                        "detected": run_detect,
                    }

            frame_index += 1

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        yolo_stream_results[task_id] = {
            "numbers": total_count,
            "class_name": class_name,
            "model_type": model_type,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "url": output_url,
        }
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"YOLO Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        yolo_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _yolo_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
    """轮询 latest_frames，仅在帧变化时推送 NDJSON 事件。"""
    yield _ndjson_line({
        "event": "start",
        "code": 200,
        "msg": "Stream started",
        "data": start_payload,
    })

    last_sent_frame = None

    while True:
        with frame_lock:
            frame_data = latest_frames.get(task_id)
            frame_meta = latest_frame_meta.get(task_id, {})
            status = processing_status.get(task_id)

        if frame_data and frame_data != last_sent_frame:
            yield _ndjson_line({
                "event": "frame",
                "code": 200,
                "msg": "Frame processed",
                "data": {
                    "frame_index": frame_meta.get("frame_index", 0),
                    "numbers": frame_meta.get("numbers", 0),
                    "detected": frame_meta.get("detected", False),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data

        if status == "done":
            result = yolo_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "done",
                "code": 200,
                "msg": "Video stream detected success",
                "data": result,
            })
            break

        if status == "error":
            result = yolo_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "error",
                "code": 500,
                "msg": result.get("msg", "Video stream task failed"),
                "data": None,
            })
            break

        await asyncio.sleep(0.01)


async def _yolo_mjpeg_generator(task_id: str) -> AsyncGenerator[bytes, None]:
    """MJPEG 帧生成器，对齐 traffic_interface_bak.py 的 frame_generator。"""
    last_sent_frame = None

    while True:
        with frame_lock:
            frame_data = latest_frames.get(task_id)

        if frame_data and frame_data != last_sent_frame:
            jpeg_bytes = base64.b64decode(frame_data)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n\r\n" + jpeg_bytes + b"\r\n"
            )
            last_sent_frame = frame_data

        status = processing_status.get(task_id)
        if status in ("done", "error"):
            break

        await asyncio.sleep(0.01)


def register_yolo_routes(app):
    @app.post("/yoloDetected")
    async def yolo_detected(
        file: UploadFile = File(...),
        class_name: str = Form(...),
        model_type: str = Form(...),
    ):
        try:
            if model_type not in get_available_model_types():
                return JSONResponse({
                    "code": 400,
                    "msg": f"Model type '{model_type}' not supported. Available: {get_available_model_types()}",
                    "data": None
                })

            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as f:
                f.write(await file.read())

            class_name, detect_all = normalize_class_name(class_name)
            names = get_model_names(model_type)
            if not detect_all and class_name not in names.values():
                return JSONResponse({
                    "code": 400,
                    "msg": f"Class '{class_name}' not supported. Available: {list(names.values())}",
                    "data": None
                })

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                executor,
                partial(run_image_detection, file_path, class_name, detect_all, model_type),
            )

            return JSONResponse({
                "code": 200,
                "msg": "Success",
                "data": data,
            })
        except Exception as e:
            import traceback
            print("YOLO Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/yoloVideoDetected")
    async def yolo_video_detected(
        file: UploadFile = File(...),
        class_name: str = Form(...),
        model_type: str = Form(...),
    ):
        try:
            if model_type not in get_available_model_types():
                return JSONResponse({
                    "code": 400,
                    "msg": f"Model type '{model_type}' not supported. Available: {get_available_model_types()}",
                    "data": None
                })

            # --- 1. 类别校验 ---
            class_name, detect_all = normalize_class_name(class_name)
            names = get_model_names(model_type)
            if not detect_all and class_name not in names.values():
                return JSONResponse({
                    "code": 400,
                    "msg": f"Class '{class_name}' not supported. Available: {list(names.values())}",
                    "data": None
                })
            target_id = resolve_target_id(model_type, class_name, detect_all)

            # --- 2. 保存上传视频 ---
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            video_path = upload_dir / file.filename
            with open(video_path, "wb") as f:
                f.write(await file.read())

            # --- 3. 创建输出目录 ---
            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_video_path = detected_dir / f"yolo_{Path(file.filename).stem}.mp4"

            # --- 4. 打开视频读取器 ---
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError("无法打开上传的视频文件")

            # 获取视频属性
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            # 初始化 VideoWriter（H.264 编码，.mp4 容器）
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')  # 注意：有些系统需用 'avc1'
            out = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
            if not out.isOpened():
                raise RuntimeError("无法创建输出视频文件，请检查 OpenCV 编解码器支持")

            total_count = 0
            # --- 5. 逐帧处理 ---
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                _, frame_count, annotated_frame = predict_video_frame(
                    model_type, frame, detect_all, target_id
                )
                total_count += frame_count
                out.write(annotated_frame)

            # --- 6. 释放资源 ---
            cap.release()
            out.release()

            # --- 7. 验证输出文件是否存在 ---
            if not output_video_path.exists() or output_video_path.stat().st_size == 0:
                raise FileNotFoundError("输出视频未生成或为空")

            return JSONResponse({
                "code": 200,
                "msg": "Video Detected Success",
                "data": {
                    "numbers": total_count,
                    "class_name": class_name,
                    "model_type": model_type,
                    "url": str(output_video_path).replace("\\", "/")
                }
            })

        except Exception as e:
            import traceback
            print("YOLO Video Error:", e)
            traceback.print_exc()
            return JSONResponse({
                "code": 500,
                "msg": str(e),
                "data": None
            })

    @app.post("/yoloVideoDetectedWithFrame")
    async def yolo_video_detected_with_frame(
        file: UploadFile = File(...),
        class_name: str = Form(...),
        model_type: str = Form(...),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """
        视频逐帧流式检测（NDJSON）。

        实现方式对齐 traffic_interface_bak.py：
        - 后台线程处理视频，主线程轮询 latest_frames 推送帧
        - 跳帧 YOLO 推理，中间帧复用缓存检测框
        - 标注样式与 /yoloVideoDetected 一致（result.plot + Annotator）
        - JPEG 质量 50，仅在帧变化时推送，避免阻塞与冗余传输
        """
        if model_type not in get_available_model_types():
            return JSONResponse({
                "code": 400,
                "msg": f"Model type '{model_type}' not supported. Available: {get_available_model_types()}",
                "data": None,
            })

        class_name, detect_all = normalize_class_name(class_name)
        names = get_model_names(model_type)
        if not detect_all and class_name not in names.values():
            return JSONResponse({
                "code": 400,
                "msg": f"Class '{class_name}' not supported. Available: {list(names.values())}",
                "data": None,
            })

        target_id = resolve_target_id(model_type, class_name, detect_all)

        interval = max(1, int(frame_interval))
        video_bytes = await file.read()
        filename = Path(file.filename or "upload.mp4").name

        upload_dir = Path("upload/source")
        upload_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / filename
        video_path.write_bytes(video_bytes)

        try:
            fps, width, height, total_frames = _read_video_metadata(video_path)
        except ValueError as e:
            return JSONResponse({"code": 400, "msg": str(e), "data": None})

        task_id = str(uuid.uuid4())
        detected_dir = Path("upload/detected") / task_id
        detected_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = detected_dir / f"yolo_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        executor.submit(
            process_yolo_video_stream_task,
            task_id,
            str(video_path.resolve()),
            str(output_video_path.resolve()),
            output_url,
            model_type,
            class_name,
            detect_all,
            target_id,
            interval,
        )

        start_payload = {
            "session_id": task_id,
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "frame_interval": interval,
            "class_name": class_name,
            "model_type": model_type,
        }

        return StreamingResponse(
            _yolo_ndjson_generator(task_id, start_payload),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/getYoloLatestFrame")
    async def get_yolo_latest_frame(task_id: str = Query(..., description="流式检测任务 ID")):
        """获取 YOLO 实时检测最新帧（base64 JPEG）。"""
        with frame_lock:
            frame_data = latest_frames.get(task_id)

        if frame_data is None:
            return JSONResponse({"frame": None, "msg": "Processing not started or frame not ready"})
        return JSONResponse({"frame": frame_data})

    @app.get("/yoloVideoStatus")
    async def yolo_video_status(task_id: str = Query(..., description="流式检测任务 ID")):
        """查询 YOLO 流式检测任务状态及结果。"""
        status = processing_status.get(task_id, "not_found")
        result = yolo_stream_results.get(task_id, {})

        return JSONResponse({
            "task_id": task_id,
            "status": status,
            "result": result,
            "output_path": result.get("url", ""),
        })

    @app.get("/yoloVideoStream")
    async def yolo_video_stream(task_id: str = Query(..., description="流式检测任务 ID")):
        """使用 MJPEG 流式传输 YOLO 检测帧。"""
        if task_id not in processing_status:
            return JSONResponse({"msg": "Task not found"}, status_code=404)

        return StreamingResponse(
            _yolo_mjpeg_generator(task_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
