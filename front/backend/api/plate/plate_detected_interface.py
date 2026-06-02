# plate_detected_interface.py
import asyncio
import base64
import json
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path
from typing import AsyncGenerator, List, Optional, Tuple

import cv2
import requests
from fastapi import File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from utils.myutils import normalize_plateno, query_chinese_plate, writ2json

from .onnx_infer import (
    detect_pre_precessing,
    draw_result,
    post_precessing,
    rec_plate,
)

FRAME_DETECT_INTERVAL_DEFAULT = 5
STREAM_JPEG_QUALITY = 50
IMG_SIZE = (640, 640)
PLATE_VIDEO_MIN_OCCURRENCES = 5

pattern_str = (
    r"([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]"
    r"{1}(([A-HJ-Z]{1}[A-HJ-NP-Z0-9]{5})|([A-HJ-Z]{1}(([DF]{1}[A-HJ-NP-Z0-9]{1}[0-9]{4})|([0-9]{5}[DF]"
    r"{1})))|([A-HJ-Z]{1}[A-D0-9]{1}[0-9]{3}警)))|([0-9]{6}使)|((([沪粤川云桂鄂陕蒙藏黑辽渝]{1}A)|鲁B|闽D|蒙E|蒙H)"
    r"[0-9]{4}领)|(WJ[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼·•]{1}[0-9]{4}[TDSHBXJ0-9]{1})"
    r"|([VKHBSLJNGCE]{1}[A-DJ-PR-TVY]{1}[0-9]{5})"
)

# ====== 实时流式检测：后台线程 + 共享最新帧 ======
latest_frames = {}
latest_frame_meta = {}
processing_status = {}
plate_stream_results = {}
frame_lock = threading.Lock()
model_inference_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)

_detect_session = None
_rec_session = None


def _resolve_plate_detect_model_path(weights_dir: Path) -> Path:
    """解析车牌检测模型文件路径，优先查找 plate_detected.onnx，其次 plate_detect.onnx。

    参数:
        weights_dir: 模型权重目录

    返回:
        Path: 模型文件的完整路径
    """
    for name in ("plate_detected.onnx", "plate_detect.onnx"):
        path = weights_dir / name
        if path.exists():
            return path
    return weights_dir / "plate_detected.onnx"


def _ndjson_line(payload: dict) -> str:
    """将字典序列化为一行 NDJSON 字符串（末尾带换行符）。

    参数:
        payload: 要序列化的字典

    返回:
        str: JSON 字符串 + "\n"
    """
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    """返回 result.json 的文件路径（URL 友好格式）。

    参数:
        result_dir: 结果目录

    返回:
        str: 如 "upload/detected/<uuid>/result.json"
    """
    return str(result_dir / "result.json").replace("\\", "/")


def _save_plate_api_response(result_dir: Path, response_body: dict) -> str:
    """将完整 API 响应写入 uuid 目录下的 result.json。

    参数:
        result_dir:    结果保存目录
        response_body: API 响应体字典

    返回:
        str: result.json 文件路径
    """
    result_dir.mkdir(parents=True, exist_ok=True)
    writ2json(response_body, f"{result_dir}/")
    return _result_json_url(result_dir)


def is_chinese_plate(plateno: str) -> bool:
    """判断给定字符串是否为合法的中国大陆车牌号格式。

    参数:
        plateno: 待校验的车牌号字符串

    返回:
        bool: True 表示格式合法
    """
    return bool(re.findall(pattern_str, normalize_plateno(plateno)))


def _build_plate_list(filtered_result_list: list) -> list:
    """将过滤后的检测结果转换为 API 返回的车牌列表，附带归属地查询。

    参数:
        filtered_result_list: rec_plate 返回的、已经 is_chinese_plate 过滤的结果列表

    返回:
        list[dict]: 每项包含 plateno, platecolor, city（归属地）
    """
    raw_plates = [
        {"plateno": res["plate_no"], "platecolor": res["plate_color"]}
        for res in filtered_result_list
    ]
    unique_plates = {item["plateno"] for item in raw_plates}
    plate_to_city = {plateno: query_chinese_plate(plateno) for plateno in unique_plates}
    return [
        {
            "plateno": item["plateno"],
            "platecolor": item["platecolor"],
            "city": plate_to_city[item["plateno"]],
        }
        for item in raw_plates
    ]


def _detect_plates_on_frame(
    frame,
    detect_session,
    rec_session,
) -> Tuple[list, list]:
    """对单帧图像执行完整的车牌检测+识别流程。

    参数:
        frame:          输入帧 (H, W, C)，BGR 格式
        detect_session: 检测模型的 onnxruntime.InferenceSession
        rec_session:    识别模型的 onnxruntime.InferenceSession

    返回:
        (filtered, result_list):
            filtered:    只包含合法中国车牌的检测结果列表
            result_list: 全部识别结果（含不合法的）
    """
    img, r, left, top = detect_pre_precessing(frame, IMG_SIZE)
    with model_inference_lock:
        y_onnx = detect_session.run(
            [detect_session.get_outputs()[0].name],
            {detect_session.get_inputs()[0].name: img},
        )[0]
    outputs = post_precessing(y_onnx, r, left, top)
    result_list = rec_plate(outputs, frame, rec_session)
    filtered = [res for res in result_list if is_chinese_plate(res["plate_no"])]
    return filtered, result_list


def _encode_frame_jpeg_base64(frame) -> str:
    """将帧编码为 JPEG 后转为 base64 字符串。

    参数:
        frame: numpy 数组，BGR 图像

    返回:
        str: base64 编码的 JPEG 字符串，失败时返回空字符串
    """
    ok, buf = cv2.imencode(
        ".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), STREAM_JPEG_QUALITY]
    )
    if not ok:
        return ""
    return base64.b64encode(buf).decode("utf-8")


def _run_image_detection(
    detect_session,
    rec_session,
    file_path: Path,
    detected_dir: Path,
) -> dict:
    """在线程池中执行单张图片的车牌检测（供 run_in_executor 调用）。

    参数:
        detect_session: 检测模型的 InferenceSession
        rec_session:    识别模型的 InferenceSession
        file_path:      输入图片路径
        detected_dir:   检测结果图片输出目录

    返回:
        dict: {plate_number, plate_list, url, result_dir}
    """
    img0 = cv2.imread(str(file_path))
    if img0 is None:
        raise ValueError("无法读取图像，请检查图片格式")

    filtered, result_list = _detect_plates_on_frame(img0, detect_session, rec_session)
    result_img = draw_result(img0.copy(), result_list)

    detected_dir.mkdir(parents=True, exist_ok=True)
    output_path = detected_dir / f"plate_{file_path.name}"
    cv2.imwrite(str(output_path), result_img)

    plate_list = _build_plate_list(filtered)
    return {
        "plate_number": len(plate_list),
        "plate_list": plate_list,
        "url": str(output_path).replace("\\", "/"),
        "result_dir": str(detected_dir).replace("\\", "/"),
    }


def _read_video_metadata(video_path: Path) -> tuple:
    """读取视频文件的元数据：帧率、宽高、总帧数。

    参数:
        video_path: 视频文件路径

    返回:
        (fps, width, height, total_frames): 帧率(int)、宽度(int)、高度(int)、总帧数(int)

    异常:
        ValueError: 无法打开视频文件
    """
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise ValueError("无法打开上传的视频文件")
    fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    cap.release()
    return fps, width, height, total_frames


def _aggregate_video_plates(plate_counter: dict) -> list:
    """聚合视频中所有帧的检测结果：过滤低频出现（<5 次）的车牌，添加归属地。

    参数:
        plate_counter: {(plate_no, plate_color): count} 计数字典

    返回:
        list[dict]: 每项包含 plateno, platecolor, city，按车牌号排序
    """
    final_plate_items = [
        {"plateno": plateno, "platecolor": platecolor}
        for (plateno, platecolor), count in plate_counter.items()
        if count >= PLATE_VIDEO_MIN_OCCURRENCES
    ]
    unique_plates = {item["plateno"] for item in final_plate_items}
    plate_to_city = {plateno: query_chinese_plate(plateno) for plateno in unique_plates}
    final_plate_list = [
        {
            "plateno": item["plateno"],
            "platecolor": item["platecolor"],
            "city": plate_to_city[item["plateno"]],
        }
        for item in final_plate_items
    ]
    final_plate_list.sort(key=lambda x: x["plateno"])
    return final_plate_list


def process_plate_video_stream_task(
    task_id: str,
    input_path: str,
    output_path: str,
    output_url: str,
    detect_session,
    rec_session,
    frame_interval: int,
):
    """后台线程任务：逐帧处理视频，跳帧推理，缓存检测框，实时更新 latest_frames。

    参数:
        task_id:         任务唯一 ID
        input_path:      输入视频文件路径
        output_path:     输出标注视频文件路径
        output_url:      输出视频的访问 URL
        detect_session:  检测模型的 InferenceSession
        rec_session:     识别模型的 InferenceSession
        frame_interval:  检测间隔帧数（每 N 帧执行一次推理，中间帧复用缓存结果）

    返回:
        None（结果写入 plate_stream_results[task_id]，状态写入 processing_status[task_id]）
    """
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
        frame_plate_total = 0
        plate_counter = {}
        cached_filtered: Optional[List] = None

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            frame_count += 1
            run_detect = frame_count == 1 or frame_count % frame_interval == 0
            frame_plate_count = 0

            if run_detect:
                filtered, _ = _detect_plates_on_frame(frame, detect_session, rec_session)
                cached_filtered = filtered
                frame_plate_count = len(filtered)
                frame_plate_total += frame_plate_count
                for res in filtered:
                    key = (res["plate_no"], res["plate_color"])
                    plate_counter[key] = plate_counter.get(key, 0) + 1
                annotated = draw_result(frame.copy(), filtered, include_city=False)
            elif cached_filtered is not None:
                annotated = draw_result(frame.copy(), cached_filtered, include_city=False)
            else:
                annotated = frame
            out.write(annotated)

            jpg_as_text = _encode_frame_jpeg_base64(annotated)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "plate_number": frame_plate_count,
                        "detected": run_detect,
                    }

            frame_index += 1

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        final_plate_list = _aggregate_video_plates(plate_counter)
        plate_stream_results[task_id] = {
            "plate_number": len(final_plate_list),
            "plate_list": final_plate_list,
            "frame_plate_total": frame_plate_total,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "url": output_url,
        }
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"Plate Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        plate_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _plate_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
    """异步生成器：轮询 latest_frames，仅在帧数据变化时推送 NDJSON 事件。

    参数:
        task_id:       任务唯一 ID
        start_payload: 启动事件中携带的元数据（fps、尺寸等）

    生成:
        NDJSON 行字符串，事件类型: "start" → "frame"* → "done"/"error"
    """
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
                    "plate_number": frame_meta.get("plate_number", 0),
                    "detected": frame_meta.get("detected", False),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data

        if status == "done":
            result = plate_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "done",
                "code": 200,
                "msg": "Video stream detected success",
                "data": result,
            })
            break

        if status == "error":
            result = plate_stream_results.get(task_id, {})
            yield _ndjson_line({
                "event": "error",
                "code": 500,
                "msg": result.get("msg", "Video stream task failed"),
                "data": None,
            })
            break

        await asyncio.sleep(0.01)


async def _plate_mjpeg_generator(task_id: str) -> AsyncGenerator[bytes, None]:
    """异步生成器：轮询 latest_frames，推流 MJPEG 格式的帧数据。

    参数:
        task_id: 任务唯一 ID

    生成:
        MJPEG multipart 字节流（--frame + Content-Type + JPEG 数据）
    """
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


def register_plate_routes(app, detect_session, rec_session):
    """向 FastAPI 应用注册所有车牌检测相关的 API 路由。

    参数:
        app:            FastAPI 应用实例
        detect_session: 车牌检测模型的 onnxruntime.InferenceSession
        rec_session:    车牌识别模型的 onnxruntime.InferenceSession

    注册的路由:
        POST /plateDetected                 — 图片车牌检测
        POST /plateVideoDetected            — 视频车牌检测（处理完成后返回结果）
        POST /plateVideoDetectedWithFrame   — 视频逐帧流式检测（NDJSON）
        GET  /getPlateLatestFrame           — 获取实时检测最新帧
        GET  /plateVideoStatus              — 查询流式任务状态
        GET  /plateVideoStream              — MJPEG 流式传输检测帧
    """
    global _detect_session, _rec_session
    _detect_session = detect_session
    _rec_session = rec_session

    @app.post("/plateDetected")
    async def plate_detected(file: UploadFile = File(...)):
        """图片车牌检测接口。

        请求: multipart/form-data, 字段 file: 图片文件
        返回: JSON {code, msg, data: {plate_number, plate_list, url, result_dir, result_json}}
        """
        try:
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as f:
                f.write(await file.read())

            detected_dir = Path("upload/detected") / str(uuid.uuid4())

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                executor,
                partial(
                    _run_image_detection,
                    detect_session,
                    rec_session,
                    file_path,
                    detected_dir,
                ),
            )

            data["result_json"] = _result_json_url(detected_dir)
            response_body = {
                "code": 200,
                "msg": "Plate Detected Success",
                "data": data,
            }
            _save_plate_api_response(detected_dir, response_body)

            return JSONResponse(response_body)
        except Exception as e:
            import traceback
            print("Plate Image Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/plateVideoDetected")
    async def plate_video_detected(file: UploadFile = File(...)):
        """视频车牌检测接口（非流式，处理完成后一次性返回结果）。

        请求: multipart/form-data, 字段 file: 视频文件
        返回: JSON {code, msg, data: {plate_number, plate_list, url, result_dir, result_json}}
        """
        try:
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            video_path = upload_dir / file.filename
            with open(video_path, "wb") as f:
                f.write(await file.read())

            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_video_path = detected_dir / f"plate_{Path(file.filename).stem}.mp4"

            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError("无法打开上传的视频文件")

            fps = max(1, int(cap.get(cv2.CAP_PROP_FPS)) or 25)
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

            fourcc = cv2.VideoWriter_fourcc(*"mp4v")
            out = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
            if not out.isOpened():
                raise RuntimeError("无法创建输出视频文件，请检查 OpenCV 编解码器支持")

            plate_counter = {}
            frame_count = 0
            frame_interval = FRAME_DETECT_INTERVAL_DEFAULT

            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                frame_count += 1
                if frame_count % frame_interval != 0:
                    out.write(frame)
                    continue

                filtered, _ = _detect_plates_on_frame(frame, detect_session, rec_session)
                for res in filtered:
                    key = (res["plate_no"], res["plate_color"])
                    plate_counter[key] = plate_counter.get(key, 0) + 1

                drawn_frame = draw_result(frame.copy(), filtered, include_city=False)
                out.write(drawn_frame)

            cap.release()
            out.release()

            if not output_video_path.exists() or output_video_path.stat().st_size == 0:
                raise FileNotFoundError("输出视频未生成或为空")

            final_plate_list = _aggregate_video_plates(plate_counter)

            data = {
                "plate_number": len(final_plate_list),
                "plate_list": final_plate_list,
                "url": str(output_video_path).replace("\\", "/"),
                "result_dir": str(detected_dir).replace("\\", "/"),
            }
            data["result_json"] = _result_json_url(detected_dir)
            response_body = {
                "code": 200,
                "msg": "Video Plate Detected Success",
                "data": data,
            }
            _save_plate_api_response(detected_dir, response_body)

            return JSONResponse(response_body)
        except Exception as e:
            import traceback
            print("Plate Video Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/plateVideoDetectedWithFrame")
    async def plate_video_detected_with_frame(
        file: UploadFile = File(...),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """视频逐帧流式车牌检测接口（NDJSON SSE 风格）。

        请求: multipart/form-data
            file:           视频文件
            frame_interval: 检测间隔帧数（默认 5）

        返回: StreamingResponse (application/x-ndjson)
            事件流: start → frame* → done/error
        """
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
        output_video_path = detected_dir / f"plate_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        executor.submit(
            process_plate_video_stream_task,
            task_id,
            str(video_path.resolve()),
            str(output_video_path.resolve()),
            output_url,
            detect_session,
            rec_session,
            interval,
        )

        start_payload = {
            "session_id": task_id,
            "fps": fps,
            "width": width,
            "height": height,
            "total_frames": total_frames,
            "frame_interval": interval,
        }

        return StreamingResponse(
            _plate_ndjson_generator(task_id, start_payload),
            media_type="application/x-ndjson",
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/getPlateLatestFrame")
    async def get_plate_latest_frame(task_id: str = Query(..., description="流式检测任务 ID")):
        """获取车牌实时检测的最新帧（base64 JPEG）。

        参数:
            task_id: 流式检测任务 ID

        返回:
            JSON {frame: base64_jpeg_string | None, msg: str}
        """
        with frame_lock:
            frame_data = latest_frames.get(task_id)

        if frame_data is None:
            return JSONResponse({"frame": None, "msg": "Processing not started or frame not ready"})
        return JSONResponse({"frame": frame_data})

    @app.get("/plateVideoStatus")
    async def plate_video_status(task_id: str = Query(..., description="流式检测任务 ID")):
        """查询车牌流式检测任务的当前状态及结果。

        参数:
            task_id: 流式检测任务 ID

        返回:
            JSON {task_id, status: "processing"|"done"|"error"|"not_found", result, output_path}
        """
        status = processing_status.get(task_id, "not_found")
        result = plate_stream_results.get(task_id, {})

        return JSONResponse({
            "task_id": task_id,
            "status": status,
            "result": result,
            "output_path": result.get("url", ""),
        })

    @app.get("/plateVideoStream")
    async def plate_video_stream(task_id: str = Query(..., description="流式检测任务 ID")):
        """MJPEG 流式传输车牌检测标注帧，可直接在 <img> 标签中使用。

        参数:
            task_id: 流式检测任务 ID

        返回:
            StreamingResponse (multipart/x-mixed-replace; boundary=frame)
        """
        if task_id not in processing_status:
            return JSONResponse({"msg": "Task not found"}, status_code=404)

        return StreamingResponse(
            _plate_mjpeg_generator(task_id),
            media_type="multipart/x-mixed-replace; boundary=frame",
        )
