# speed_detected_interface.py
"""车速检测 API：/speedVideoDetected（NDJSON 逐帧实时流式）。"""

import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator, Dict, List

import cv2
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from api.speed.speed_detect_service import (
    DEFAULT_METERS_PER_PIXEL,
    build_final_speed_list,
    create_speed_estimator,
    estimate_frame_speeds,
    finalize_all_track_speeds,
    resolve_meters_per_pixel,
)
from utils.myutils import writ2json

FRAME_DETECT_INTERVAL_DEFAULT = 1
STREAM_JPEG_QUALITY = 50

latest_frames: Dict[str, str] = {}
latest_frame_meta: Dict[str, dict] = {}
processing_status: Dict[str, str] = {}
speed_stream_results: Dict[str, dict] = {}
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_speed_api_response(result_dir: Path, response_body: dict) -> str:
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


def process_speed_video_stream_task(
    task_id: str,
    input_path: str,
    output_path: str,
    output_url: str,
    result_dir: Path,
    frame_interval: int,
    meters_per_pixel: float,
):
    """后台线程任务：逐帧车速估计 → 写出标注视频 → 实时更新 latest_frames。"""
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

        speed_obj = create_speed_estimator(width, height)
        processing_status[task_id] = "processing"
        track_class_map: Dict[int, str] = {}
        track_state: Dict[int, dict] = {}
        frame_count = 0
        frame_index = 0
        max_speed_kmh = 0.0
        mpp = meters_per_pixel

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            run_detect = frame_count == 1 or frame_count % frame_interval == 0
            vehicle_count = 0
            frame_speed_samples: List[dict] = []

            if run_detect:
                processed_frame, vehicle_count, frame_speed_samples = estimate_frame_speeds(
                    frame,
                    frame_index,
                    float(fps),
                    width,
                    height,
                    mpp,
                    track_state,
                    track_class_map,
                    speed_obj,
                )
                for sample in frame_speed_samples:
                    max_speed_kmh = max(max_speed_kmh, sample["speed_kmh"])
            else:
                processed_frame = frame.copy()

            out.write(processed_frame)

            jpg_as_text = _encode_frame_jpeg_base64(processed_frame)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "vehicle_count": vehicle_count,
                        "speed_samples": frame_speed_samples,
                        "detected": run_detect,
                    }

            frame_index += 1

        finalize_all_track_speeds(track_state, speed_obj, float(fps), mpp)

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        speed_list = build_final_speed_list(track_state, track_class_map, float(fps), mpp)
        reliable_speed_list = [item for item in speed_list if item.get("reliable")]
        result_dir_str = str(result_dir).replace("\\", "/")
        max_reliable = (
            max((item["speed_kmh"] for item in reliable_speed_list), default=0.0)
        )

        data = {
            "session_id": task_id,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "fps": fps,
            "meters_per_pixel": round(mpp, 6),
            "vehicle_count": len(speed_list),
            "reliable_vehicle_count": len(reliable_speed_list),
            "max_speed_kmh": round(max_reliable, 2),
            "speed_list": speed_list,
            "reliable_speed_list": reliable_speed_list,
            "url": output_url,
            "result_dir": result_dir_str,
        }
        data["result_json"] = _result_json_url(result_dir)

        response_body = {
            "code": 200,
            "msg": "Speed video detected success",
            "data": data,
        }
        _save_speed_api_response(result_dir, response_body)

        speed_stream_results[task_id] = data
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"Speed Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        speed_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _speed_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
    """异步生成器：轮询 latest_frames，仅在帧变化时推送 NDJSON 事件。"""
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
                    "vehicle_count": frame_meta.get("vehicle_count", 0),
                    "speed_samples": frame_meta.get("speed_samples", []),
                    "detected": frame_meta.get("detected", False),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data

        if status == "done":
            result = speed_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "done",
                "code": 200,
                "msg": "Speed video stream detected success",
                "data": result,
            })
            break

        if status == "error":
            result = speed_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "error",
                "code": 500,
                "msg": result.get("msg", "Speed video stream task failed"),
                "data": None,
            })
            break

        await asyncio.sleep(0.01)


def register_speed_routes(app):
    """向 FastAPI 注册车速检测路由。"""

    @app.post("/speedVideoDetected")
    async def speed_video_detected(
        file: UploadFile = File(...),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
        meters_per_pixel: float = Form(DEFAULT_METERS_PER_PIXEL),
        reference_distance_m: float = Form(0.0),
        reference_pixels: float = Form(0.0),
    ):
        """视频车速检测接口（NDJSON 逐帧实时流）。"""
        interval = max(1, int(frame_interval))
        mpp = resolve_meters_per_pixel(
            float(meters_per_pixel),
            float(reference_distance_m),
            float(reference_pixels),
        )
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
        output_video_path = detected_dir / f"speed_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        start_payload = {
            "session_id": task_id,
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "frame_interval": interval,
            "meters_per_pixel": round(mpp, 6),
        }

        executor.submit(
            process_speed_video_stream_task,
            task_id,
            str(video_path.resolve()),
            str(output_video_path.resolve()),
            output_url,
            detected_dir,
            interval,
            mpp,
        )

        return StreamingResponse(
            _speed_ndjson_generator(task_id, start_payload),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

