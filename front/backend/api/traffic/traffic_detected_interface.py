# traffic_detected_interface.py
"""车流量检测 API：/trafficVideoDetected（NDJSON 逐帧实时流式）。"""

from __future__ import annotations

import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator, Dict, Set

import cv2
from deep_sort_realtime.deepsort_tracker import DeepSort
from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from utils.myutils import writ2json

from .traffic_detected import compute_traffic_summary, process_frame

FRAME_DETECT_INTERVAL_DEFAULT = 3
STREAM_JPEG_QUALITY = 50

latest_frames: Dict[str, str] = {}
latest_frame_meta: Dict[str, dict] = {}
processing_status: Dict[str, str] = {}
traffic_stream_results: Dict[str, dict] = {}
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_traffic_api_response(result_dir: Path, response_body: dict) -> str:
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


def _read_video_metadata(video_path: Path) -> tuple[int, int, int, int, float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("无法打开上传的视频文件")
    fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    duration_sec = total_frames / fps if fps > 0 else 0.0
    cap.release()
    return fps, width, height, total_frames, duration_sec


def process_traffic_video_stream_task(
    task_id: str,
    input_path: str,
    output_path: str,
    output_url: str,
    result_dir: Path,
    frame_interval: int,
    num_lanes: int,
    duration_sec: float,
):
    """后台线程：DeepSort 追踪统计车流量，更新 latest_frames。"""
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

        tracker = DeepSort(max_age=5)
        counter_set: Set[int] = set()
        current_tracks: list = []
        processing_status[task_id] = "processing"

        frame_count = 0
        frame_index = 0
        max_unique_count = 0

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            run_detect = frame_count == 1 or frame_count % frame_interval == 0

            if run_detect:
                processed_frame, frame_meta, current_tracks = process_frame(
                    frame,
                    tracker,
                    counter_set,
                    current_tracks,
                    run_detect=True,
                )
            else:
                processed_frame, frame_meta, current_tracks = process_frame(
                    frame,
                    tracker,
                    counter_set,
                    current_tracks,
                    run_detect=False,
                )

            unique_count = frame_meta["unique_vehicle_count"]
            max_unique_count = max(max_unique_count, unique_count)

            out.write(processed_frame)

            jpg_as_text = _encode_frame_jpeg_base64(processed_frame)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "unique_vehicle_count": unique_count,
                        "active_tracks": frame_meta["active_tracks"],
                        "detected": run_detect,
                    }

            frame_index += 1

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        summary = compute_traffic_summary(
            len(counter_set),
            duration_sec,
            num_lanes,
        )

        result_dir_str = str(result_dir).replace("\\", "/")
        data = {
            "session_id": task_id,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "fps": fps,
            "width": width,
            "height": height,
            "num_lanes": max(1, int(num_lanes)),
            "unique_vehicle_count": summary["unique_vehicle_count"],
            "max_unique_vehicle_count": max_unique_count,
            "duration_sec": summary["duration_sec"],
            "hourly_traffic_ratio": summary["hourly_traffic_ratio"],
            "road_condition": summary["road_condition"],
            "url": output_url,
            "result_dir": result_dir_str,
        }

        response_body = {
            "code": 200,
            "msg": "Traffic video detected success",
            "data": data,
        }
        data["result_json"] = _save_traffic_api_response(result_dir, response_body)
        traffic_stream_results[task_id] = data
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"Traffic Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        traffic_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _traffic_ndjson_generator(
    task_id: str, start_payload: dict
) -> AsyncGenerator[str, None]:
    """轮询 latest_frames，仅在帧变化时推送 NDJSON 事件。"""
    yield _ndjson_line({
        "event": "start",
        "code": 200,
        "msg": "Traffic stream started",
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
                    "unique_vehicle_count": frame_meta.get("unique_vehicle_count", 0),
                    "active_tracks": frame_meta.get("active_tracks", 0),
                    "detected": frame_meta.get("detected", False),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data

        if status == "done":
            result = traffic_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "done",
                "code": 200,
                "msg": "Traffic video stream detected success",
                "data": result,
            })
            break

        if status == "error":
            result = traffic_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "error",
                "code": 500,
                "msg": result.get("msg", "Traffic video stream task failed"),
                "data": None,
            })
            break

        await asyncio.sleep(0.01)


def register_traffic_routes(app):
    """注册车流量检测路由（仅 /trafficVideoDetected）。"""
    @app.post("/trafficVideoDetected")
    async def traffic_video_detected(
        file: UploadFile = File(...),
        num_lanes: int = Form(1, description="车道数量"),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """
        视频车流量检测（NDJSON 逐帧实时流）。

        使用 YOLO + DeepSort 追踪统计唯一车辆数，估算小时流量与道路状况；
        完整响应写入 upload/detected/{uuid}/result.json。
        """
        interval = max(1, int(frame_interval))
        lanes = max(1, int(num_lanes))
        video_bytes = await file.read()
        filename = Path(file.filename or "upload.mp4").name

        if not video_bytes:
            return JSONResponse({"code": 400, "msg": "上传视频为空", "data": None})

        upload_dir = Path("upload/source")
        upload_dir.mkdir(parents=True, exist_ok=True)
        video_path = upload_dir / filename
        video_path.write_bytes(video_bytes)

        try:
            fps, width, height, total_frames, duration_sec = _read_video_metadata(
                video_path
            )
        except ValueError as e:
            return JSONResponse({"code": 400, "msg": str(e), "data": None})

        task_id = str(uuid.uuid4())
        detected_dir = Path("upload/detected") / task_id
        detected_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = detected_dir / f"traffic_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        start_payload = {
            "session_id": task_id,
            "fps": fps,
            "source_width": width,
            "source_height": height,
            "total_frames": total_frames,
            "duration_sec": round(duration_sec, 3),
            "frame_interval": interval,
            "num_lanes": lanes,
        }

        executor.submit(
            process_traffic_video_stream_task,
            task_id,
            str(video_path.resolve()),
            str(output_video_path.resolve()),
            output_url,
            detected_dir,
            interval,
            lanes,
            duration_sec,
        )

        return StreamingResponse(
            _traffic_ndjson_generator(task_id, start_payload),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )
