# line_detected_interface.py
"""车道检测 API：基于传统 CV（Canny + Hough）的车道线识别。"""

import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator

import cv2
from fastapi import File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from api.line.line_detect_service import detect_lines
from utils.myutils import writ2json

FRAME_DETECT_INTERVAL_DEFAULT = 3
STREAM_JPEG_QUALITY = 50

latest_frames = {}
latest_frame_meta = {}
processing_status = {}
line_stream_results = {}
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_line_api_response(result_dir: Path, response_body: dict) -> str:
    result_dir.mkdir(parents=True, exist_ok=True)
    writ2json(response_body, f"{result_dir}/")
    return _result_json_url(result_dir)


def _encode_frame_jpeg_base64(frame) -> str:
    ok, buf = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
    )
    if not ok:
        return ""
    return base64.b64encode(buf).decode("utf-8")


def _read_video_metadata(video_path: Path) -> tuple:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("无法打开上传的视频文件")
    fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, width, height, total_frames


def process_line_video_stream_task(
    task_id: str,
    input_path: str,
    output_path: str,
    output_url: str,
    detected_dir: Path,
    frame_interval: int,
):
    """后台线程：逐帧车道检测 → 写出标注视频 → 实时更新 latest_frames。"""
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
            raise RuntimeError("无法创建输出视频文件")

        processing_status[task_id] = "processing"
        frame_index = 0
        max_lines = 0
        total_lines_detected = 0
        lines_detected_frames = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            should_detect = frame_index % frame_interval == 0
            if should_detect:
                annotated, has_lines, line_count = detect_lines(frame)
            else:
                annotated, has_lines, line_count = frame, False, 0

            out.write(annotated)

            if should_detect and has_lines:
                lines_detected_frames += 1
                total_lines_detected += line_count
                max_lines = max(max_lines, line_count)

            if should_detect:
                jpg_as_text = _encode_frame_jpeg_base64(annotated)
                if jpg_as_text:
                    with frame_lock:
                        latest_frames[task_id] = jpg_as_text
                        latest_frame_meta[task_id] = {
                            "frame_index": frame_index,
                            "line_count": line_count,
                            "has_lines": has_lines,
                        }
            frame_index += 1

        if cap is not None:
            cap.release()
            cap = None
        if out is not None:
            out.release()
            out = None

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        data = {
            "session_id": task_id,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "fps": fps,
            "lines_detected_frames": lines_detected_frames,
            "max_lines": max_lines,
            "avg_lines_per_detected_frame": (
                round(total_lines_detected / lines_detected_frames, 2)
                if lines_detected_frames > 0 else 0
            ),
            "url": output_url,
            "result_dir": str(detected_dir).replace("\\", "/"),
        }
        data["result_json"] = _result_json_url(detected_dir)
        response_body = {"code": 200, "msg": "line video detected success", "data": data}
        _save_line_api_response(detected_dir, response_body)
        line_stream_results[task_id] = data
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"line Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        line_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _line_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
    yield _ndjson_line({"event": "start", "code": 200, "msg": "Stream started", "data": start_payload})
    last_sent_frame = None
    while True:
        with frame_lock:
            frame_data = latest_frames.get(task_id)
            frame_meta = latest_frame_meta.get(task_id, {})
            status = processing_status.get(task_id)
        if frame_data and frame_data != last_sent_frame:
            yield _ndjson_line({
                "event": "frame", "code": 200, "msg": "Frame processed",
                "data": {
                    "frame_index": frame_meta.get("frame_index", 0),
                    "line_count": frame_meta.get("line_count", 0),
                    "has_lines": frame_meta.get("has_lines", False),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data
        if status == "done":
            yield _ndjson_line({
                "event": "done", "code": 200,
                "msg": "line video stream detected success",
                "data": line_stream_results.get(task_id, {}),
            })
            break
        if status == "error":
            yield _ndjson_line({
                "event": "error", "code": 500,
                "msg": line_stream_results.get(task_id, {}).get("msg", "Task failed"),
                "data": None,
            })
            break
        await asyncio.sleep(0.01)


def register_line_routes(app):
    """向 FastAPI 注册车道检测路由。

    注册的路由:
        POST /lineDetected                 — 图片车道检测
        POST /lineVideoDetectedWithFrame   — 视频逐帧流式检测（NDJSON）
        GET  /getlineLatestFrame           — 获取实时检测最新帧
        GET  /lineVideoStatus              — 查询流式任务状态
    """

    @app.post("/lineDetected")
    async def line_detected(file: UploadFile = File(...)):
        """图片车道检测接口。"""
        try:
            request_id = str(uuid.uuid4())
            filename = Path(file.filename or "upload.jpg").name
            upload_dir = Path("upload/source") / request_id
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / filename
            file_path.write_bytes(await file.read())

            img = cv2.imread(str(file_path))
            if img is None:
                raise ValueError("无法读取图像")

            annotated, has_lines, line_count = detect_lines(img)

            detected_dir = Path("upload/detected") / request_id
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_path = detected_dir / f"line_{filename}"
            cv2.imwrite(str(output_path), annotated)

            data = {
                "line_count": line_count,
                "has_lines": has_lines,
                "url": str(output_path).replace("\\", "/"),
                "result_dir": str(detected_dir).replace("\\", "/"),
            }
            response_body = {"code": 200, "msg": "line Detected Success", "data": data}
            data["result_json"] = _result_json_url(detected_dir)
            _save_line_api_response(detected_dir, response_body)
            return JSONResponse(response_body)
        except Exception as e:
            import traceback
            print("line Image Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/lineVideoDetectedWithFrame")
    async def line_video_detected_with_frame(
        file: UploadFile = File(...),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """视频逐帧流式车道检测接口（NDJSON）。"""
        interval = max(1, int(frame_interval))
        task_id = str(uuid.uuid4())
        video_bytes = await file.read()
        filename = Path(file.filename or "upload.mp4").name
        upload_dir = Path("upload/source") / task_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / filename
        video_path.write_bytes(video_bytes)
        try:
            fps, width, height, total_frames = _read_video_metadata(video_path)
        except ValueError as e:
            return JSONResponse({"code": 400, "msg": str(e), "data": None})

        detected_dir = Path("upload/detected") / task_id
        detected_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = detected_dir / f"line_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        executor.submit(
            process_line_video_stream_task,
            task_id,
            str(video_path.resolve()),
            str(output_video_path.resolve()),
            output_url,
            detected_dir,
            interval,
        )
        return StreamingResponse(
            _line_ndjson_generator(task_id, {
                "session_id": task_id, "fps": fps,
                "width": width, "height": height,
                "total_frames": total_frames, "frame_interval": interval,
            }),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/getlineLatestFrame")
    async def get_line_latest_frame(task_id: str = Query(..., description="流式检测任务 ID")):
        with frame_lock:
            frame_data = latest_frames.get(task_id)
        if frame_data is None:
            return JSONResponse({"frame": None, "msg": "Processing not started or frame not ready"})
        return JSONResponse({"frame": frame_data})

    @app.get("/lineVideoStatus")
    async def line_video_status(task_id: str = Query(..., description="流式检测任务 ID")):
        status = processing_status.get(task_id, "not_found")
        result = line_stream_results.get(task_id, {})
        return JSONResponse({
            "task_id": task_id, "status": status,
            "result": result, "output_path": result.get("url", ""),
        })
