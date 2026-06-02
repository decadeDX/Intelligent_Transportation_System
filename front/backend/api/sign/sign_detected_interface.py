# sign_detected_interface.py
"""交通标识检测 API：基于 YOLO 的交通标志、信号灯等道路标识识别。"""

import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator, Dict, List

import cv2
from fastapi import File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from api.sign.sign_detect_service import detect_signs, draw_sign_overlay
from utils.myutils import writ2json

FRAME_DETECT_INTERVAL_DEFAULT = 3
STREAM_JPEG_QUALITY = 50
latest_frames: Dict[str, str] = {}
latest_frame_meta: Dict[str, dict] = {}
processing_status: Dict[str, str] = {}
sign_stream_results: Dict[str, dict] = {}
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_sign_api_response(result_dir: Path, response_body: dict) -> str:
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


def process_sign_video_stream_task(
    task_id: str, input_path: str, output_path: str, output_url: str,
    detected_dir: Path, frame_interval: int,
):
    """后台线程：逐帧交通标识检测 → 写出标注视频 → 实时更新 latest_frames。"""
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
        total_signs = 0
        sign_class_counter: Dict[str, int] = {}

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detections = detect_signs(frame)
            for det in detections:
                name = det["class_name"]
                sign_class_counter[name] = sign_class_counter.get(name, 0) + 1
                total_signs += 1
            annotated = draw_sign_overlay(frame, detections)
            out.write(annotated)

            jpg_as_text = _encode_frame_jpeg_base64(annotated)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "sign_count": len(detections),
                        "detections": detections,
                    }
            frame_index += 1

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        data = {
            "session_id": task_id,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "fps": fps,
            "total_signs_detected": total_signs,
            "sign_class_counts": sign_class_counter,
            "unique_sign_types": len(sign_class_counter),
            "url": output_url,
            "result_dir": str(detected_dir).replace("\\", "/"),
        }
        response_body = {"code": 200, "msg": "Sign video detected success", "data": data}
        data["result_json"] = _save_sign_api_response(detected_dir, response_body)
        sign_stream_results[task_id] = data
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"Sign Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        sign_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _sign_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
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
                    "sign_count": frame_meta.get("sign_count", 0),
                    "detections": frame_meta.get("detections", []),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data
        if status == "done":
            yield _ndjson_line({
                "event": "done", "code": 200,
                "msg": "Sign video stream detected success",
                "data": sign_stream_results.get(task_id, {}),
            })
            break
        if status == "error":
            yield _ndjson_line({
                "event": "error", "code": 500,
                "msg": sign_stream_results.get(task_id, {}).get("msg", "Task failed"),
                "data": None,
            })
            break
        await asyncio.sleep(0.01)


def register_sign_routes(app):
    """向 FastAPI 注册交通标识检测路由。

    参数:
        app:   FastAPI 应用实例
    注册的路由:
        POST /signDetected                 — 图片交通标识检测
        POST /signVideoDetectedWithFrame   — 视频逐帧流式检测（NDJSON）
        GET  /getSignLatestFrame           — 获取实时检测最新帧
        GET  /signVideoStatus              — 查询流式任务状态
    """
    @app.post("/signDetected")
    async def sign_detected(file: UploadFile = File(...)):
        """图片交通标识检测接口。"""
        try:
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file.filename
            file_path.write_bytes(await file.read())

            img = cv2.imread(str(file_path))
            if img is None:
                raise ValueError("无法读取图像")

            detections = detect_signs(img)
            annotated = draw_sign_overlay(img, detections)

            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_path = detected_dir / f"sign_{file_path.name}"
            cv2.imwrite(str(output_path), annotated)

            sign_types = list(set(d["class_name"] for d in detections))
            data = {
                "sign_count": len(detections),
                "sign_types": sign_types,
                "unique_sign_types": len(sign_types),
                "detections": detections,
                "url": str(output_path).replace("\\", "/"),
                "result_dir": str(detected_dir).replace("\\", "/"),
            }
            data["result_json"] = _result_json_url(detected_dir)
            response_body = {"code": 200, "msg": "Sign Detected Success", "data": data}
            _save_sign_api_response(detected_dir, response_body)
            return JSONResponse(response_body)
        except Exception as e:
            import traceback
            print("Sign Image Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/signVideoDetectedWithFrame")
    async def sign_video_detected_with_frame(
        file: UploadFile = File(...),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """视频逐帧流式交通标识检测接口（NDJSON）。"""
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
        output_video_path = detected_dir / f"sign_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        executor.submit(
            process_sign_video_stream_task,
            task_id, str(video_path.resolve()),
            str(output_video_path.resolve()), output_url,
            detected_dir, interval,
        )
        return StreamingResponse(
            _sign_ndjson_generator(task_id, {
                "session_id": task_id, "fps": fps,
                "width": width, "height": height,
                "total_frames": total_frames, "frame_interval": interval,
            }),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/getSignLatestFrame")
    async def get_sign_latest_frame(task_id: str = Query(...)):
        with frame_lock:
            frame_data = latest_frames.get(task_id)
        if frame_data is None:
            return JSONResponse({"frame": None, "msg": "Processing not started or frame not ready"})
        return JSONResponse({"frame": frame_data})

    @app.get("/signVideoStatus")
    async def sign_video_status(task_id: str = Query(...)):
        status = processing_status.get(task_id, "not_found")
        result = sign_stream_results.get(task_id, {})
        return JSONResponse({
            "task_id": task_id, "status": status,
            "result": result, "output_path": result.get("url", ""),
        })
