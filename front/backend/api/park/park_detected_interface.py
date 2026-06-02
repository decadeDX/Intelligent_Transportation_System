# park_detected_interface.py
"""车位检测 API：基于 YOLO 车辆检测的停车位占用分析。"""

import asyncio
import base64
import json
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import AsyncGenerator, Dict, List, Tuple

import cv2
import numpy as np
from fastapi import File, Form, Query, UploadFile
from fastapi.responses import JSONResponse, StreamingResponse

from api.park.model_infer_service import detect_vehicles
from utils.myutils import writ2json

FRAME_DETECT_INTERVAL_DEFAULT = 5
STREAM_JPEG_QUALITY = 50
PARKING_SPOT_IOU_THRESHOLD = 0.3

latest_frames = {}
latest_frame_meta = {}
processing_status = {}
park_stream_results = {}
frame_lock = threading.Lock()
executor = ThreadPoolExecutor(max_workers=2)


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_park_api_response(result_dir: Path, response_body: dict) -> str:
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


def _box_iou(box1:Tuple[int,int,int,int], box2:Tuple[int,int,int,int])->float:
    """计算两个框IOU (x1,y1,x2,y2)"""
    x1 = max(box1[0], box2[0])
    y1 = max(box1[1], box2[1])
    x2 = min(box1[2], box2[2])
    y2 = min(box1[3], box2[3])
    inter_w = max(0, x2 - x1)
    inter_h = max(0, y2 - y1)
    inter = inter_w * inter_h

    area1 = (box1[2]-box1[0])*(box1[3]-box1[1])
    area2 = (box2[2]-box2[0])*(box2[3]-box2[1])
    union = area1 + area2 - inter
    if union == 0:
        return 0.0
    return inter / union


def _box_to_polygon(box: Tuple[int, int, int, int]) -> List[List[int]]:
    x1, y1, x2, y2 = box
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def _polygon_bounds(points: List[List[int]]) -> Tuple[int, int, int, int]:
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    return min(xs), min(ys), max(xs), max(ys)


def _normalize_spot_coordinates(coords) -> List[List[int]] | None:
    """兼容矩形 [x1,y1,x2,y2]、扁平四点和 [[x,y], ...] 四点坐标。"""
    if not isinstance(coords, list):
        return None

    if len(coords) == 4 and all(isinstance(v, (int, float)) for v in coords):
        x1, y1, x2, y2 = [int(v) for v in coords]
        if x2 <= x1 or y2 <= y1:
            return None
        return _box_to_polygon((x1, y1, x2, y2))

    if len(coords) == 8 and all(isinstance(v, (int, float)) for v in coords):
        return [[int(coords[i]), int(coords[i + 1])] for i in range(0, 8, 2)]

    if len(coords) == 4 and all(isinstance(p, list) and len(p) == 2 for p in coords):
        try:
            return [[int(p[0]), int(p[1])] for p in coords]
        except (TypeError, ValueError):
            return None

    return None


def _is_valid_spot_polygon(points: List[List[int]], frame_shape: Tuple[int, int]) -> bool:
    h, w = frame_shape[:2]
    if len(points) != 4:
        return False
    for x, y in points:
        if x < 0 or y < 0 or x > w or y > h:
            return False
    contour = np.array(points, dtype=np.float32)
    return cv2.contourArea(contour) > 0


def _polygon_iou(poly1: List[List[int]], poly2: List[List[int]]) -> float:
    """计算两个凸多边形 IoU，支持倾斜四边形车位。"""
    p1 = np.array(poly1, dtype=np.float32)
    p2 = np.array(poly2, dtype=np.float32)
    area1 = abs(cv2.contourArea(p1))
    area2 = abs(cv2.contourArea(p2))
    if area1 <= 0 or area2 <= 0:
        return 0.0

    inter_area, _ = cv2.intersectConvexConvex(p1, p2)
    union = area1 + area2 - inter_area
    if union <= 0:
        return 0.0
    return float(inter_area / union)


def _parse_parking_spots_json(content: bytes,
                              frame_shape: Tuple[int, int]) -> Tuple[dict, List[dict]]:
    """解析车位 JSON，过滤维修、无效和越界车位。"""
    try:
        payload = json.loads(content.decode("utf-8"))
    except Exception as e:
        raise ValueError(f"车位 JSON 格式错误: {e}") from e

    if not isinstance(payload, dict):
        raise ValueError("车位 JSON 根节点必须是对象")

    h, w = frame_shape[:2]
    parking_lot_info = payload.get("parking_lot_info") or {}
    raw_spots = payload.get("parking_spots")
    if not isinstance(raw_spots, list):
        raise ValueError("车位 JSON 缺少 parking_spots 数组")

    spots = []
    for index, spot in enumerate(raw_spots):
        if not isinstance(spot, dict):
            continue
        attributes = spot.get("attributes") or {}
        if attributes.get("status", "normal") != "normal":
            continue
        coords = spot.get("coordinates")
        points = _normalize_spot_coordinates(coords)
        if points is None or not _is_valid_spot_polygon(points, frame_shape):
            continue
        x1, y1, x2, y2 = _polygon_bounds(points)
        spots.append({
            "spot_id": str(spot.get("spot_id") or f"spot_{index + 1}"),
            "spot_name": str(spot.get("spot_name") or spot.get("spot_id") or f"车位{index + 1}"),
            "points": points,
            "x": x1,
            "y": y1,
            "width": x2 - x1,
            "height": y2 - y1,
        })

    return parking_lot_info, spots


def _estimate_parking_spots(frame_shape: Tuple[int, int],
                            detections: List,
                            custom_spots: List[dict] | None = None) -> Tuple[int, int, List]:
    """基于车辆检测结果估算车位占用情况。
    优先使用自定义车位；未传入时将画面下半部分网格化划分虚拟车位。
    IOU>0.3 判定车位被占。
    返回: (occupied_count, estimated_total, spot_regions)
    """
    h, w = frame_shape[:2]
    car_boxes = []
    # 修复：boxes_list → detections
    for box in detections:
        x1, y1, x2, y2, *_ = box
        area = (x2 - x1) * (y2 - y1)
        if area > 500:  # 过滤过小误检框
            car_boxes.append((x1, y1, x2, y2))

    if custom_spots is not None:
        spot_regions = []
        occupied = 0
        for spot in custom_spots:
            spot_points = spot["points"]
            is_occupied = False
            for car_box in car_boxes:
                car_points = _box_to_polygon(car_box)
                if _polygon_iou(spot_points, car_points) > PARKING_SPOT_IOU_THRESHOLD:
                    is_occupied = True
                    break
            if is_occupied:
                occupied += 1
            spot_regions.append({
                "spot_id": spot.get("spot_id", ""),
                "spot_name": spot.get("spot_name", ""),
                "points": spot_points,
                "x": int(spot["x"]),
                "y": int(spot["y"]),
                "width": int(spot["width"]),
                "height": int(spot["height"]),
                "occupied": is_occupied,
            })
        return occupied, len(spot_regions), spot_regions

    # 网格划分：画面下半区域(h//2往下)自动分块生成虚拟车位
    grid_cols = max(2, w // 300)       # 列：每300像素一个车位宽，最少2列
    grid_rows = max(1, (h // 2) // 200)# 行：每200像素一个车位高，最少1行
    spot_width = w // grid_cols
    spot_height = (h // 2) // grid_rows
    y_offset = h // 2                  # 车位从图像下半部分起始

    spot_regions = []
    occupied = 0
    # 遍历所有网格=虚拟车位
    for row in range(grid_rows):
        for col in range(grid_cols):
            sx1 = col * spot_width
            sy1 = y_offset + row * spot_height
            sx2 = sx1 + spot_width
            sy2 = sy1 + spot_height
            is_occupied = False

            # 和所有车辆框算IOU
            for cx1, cy1, cx2, cy2 in car_boxes:
                iou = _box_iou((sx1, sy1, sx2, sy2), (cx1, cy1, cx2, cy2))
                if iou > 0.3:
                    is_occupied = True
                    break
            if is_occupied:
                occupied += 1

            spot_regions.append({
                "x": int(sx1), "y": int(sy1),
                "width": int(spot_width), "height": int(spot_height),
                "points": _box_to_polygon((int(sx1), int(sy1), int(sx2), int(sy2))),
                "occupied": is_occupied,
            })
    total_spots = len(spot_regions)
    return occupied, total_spots, spot_regions


def _draw_parking_overlay(frame, detections: List, spot_regions: List) -> np.ndarray:
    """在帧上绘制车位区域和车辆检测框。"""
    annotated = frame.copy()
    # 绘制车位
    for spot in spot_regions:
        color = (0, 0, 255) if spot["occupied"] else (0, 255, 0)
        if "points" in spot:
            pts = np.array(spot["points"], dtype=np.int32)
            cv2.polylines(annotated, [pts], isClosed=True, color=color, thickness=2)
        else:
            cv2.rectangle(annotated,
                          (spot["x"], spot["y"]),
                          (spot["x"] + spot["width"], spot["y"] + spot["height"]),
                          color, 2)
        label = "占用" if spot["occupied"] else "空闲"
        cv2.putText(annotated, label,
                    (spot["x"] + 4, spot["y"] + 20),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    # 绘制车辆
    for x1, y1, x2, y2, cls_name, conf in detections:
        cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 255, 0), 2)
        cv2.putText(annotated, f"{cls_name} {conf:.2f}",
                    (x1, y1 - 6), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (255, 255, 0), 1)
    return annotated


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


def process_park_video_stream_task(
    task_id: str, input_path: str, output_path: str, output_url: str,
    detected_dir: Path, frame_interval: int,
    parking_lot_info: dict | None = None,
    custom_spots: List[dict] | None = None,
):
    """后台线程：逐帧车位检测 → 写出标注视频 → 实时更新 latest_frames。"""
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
        max_occupied = 0
        max_total = 0
        last_occupied = 0
        last_total_spots = 0
        last_spot_regions = []

        while True:
            ret, frame = cap.read()
            if not ret:
                break

            detections = detect_vehicles(frame)
            occupied, total_spots, spot_regions = _estimate_parking_spots(
                frame.shape, detections, custom_spots)
            max_occupied = max(max_occupied, occupied)
            max_total = max(max_total, total_spots)
            last_occupied = occupied
            last_total_spots = total_spots
            last_spot_regions = spot_regions
            annotated = _draw_parking_overlay(frame, detections, spot_regions)
            out.write(annotated)

            jpg_as_text = _encode_frame_jpeg_base64(annotated)
            if jpg_as_text:
                with frame_lock:
                    latest_frames[task_id] = jpg_as_text
                    latest_frame_meta[task_id] = {
                        "frame_index": frame_index,
                        "vehicle_count": len(detections),
                        "occupied_spots": occupied,
                        "total_spots": total_spots,
                        "free_spots": total_spots - occupied,
                        "parking_lot_info": parking_lot_info or {},
                        "spot_regions": spot_regions,
                    }
            frame_index += 1

        if not Path(output_path).exists() or Path(output_path).stat().st_size == 0:
            raise FileNotFoundError("输出视频未生成或为空")

        data = {
            "session_id": task_id,
            "processed_frames": frame_index,
            "frame_interval": frame_interval,
            "fps": fps,
            "max_total_spots": max_total,
            "max_occupied": max_occupied,
            "total_spots": last_total_spots,
            "occupied_spots": last_occupied,
            "free_spots": last_total_spots - last_occupied,
            "occupancy_rate": (
                round(last_occupied / last_total_spots, 2)
                if last_total_spots > 0 else 0
            ),
            "parking_lot_info": parking_lot_info or {},
            "spot_regions": last_spot_regions,
            "url": output_url,
            "result_dir": str(detected_dir).replace("\\", "/"),
        }
        data["result_json"] = _result_json_url(detected_dir)
        response_body = {"code": 200, "msg": "Park video detected success", "data": data}
        _save_park_api_response(detected_dir, response_body)
        park_stream_results[task_id] = data
        processing_status[task_id] = "done"

    except Exception as e:
        print(f"Park Video Stream Task Error: {e}")
        processing_status[task_id] = "error"
        park_stream_results[task_id] = {"msg": str(e)}
    finally:
        if cap is not None:
            cap.release()
        if out is not None:
            out.release()


async def _park_ndjson_generator(task_id: str, start_payload: dict) -> AsyncGenerator[str, None]:
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
                    "vehicle_count": frame_meta.get("vehicle_count", 0),
                    "occupied_spots": frame_meta.get("occupied_spots", 0),
                    "total_spots": frame_meta.get("total_spots", 0),
                    "free_spots": frame_meta.get("free_spots", 0),
                    "parking_lot_info": frame_meta.get("parking_lot_info", {}),
                    "spot_regions": frame_meta.get("spot_regions", []),
                    "frame_jpeg_base64": frame_data,
                },
            })
            last_sent_frame = frame_data
        if status == "done":
            yield _ndjson_line({
                "event": "done", "code": 200,
                "msg": "Park video stream detected success",
                "data": park_stream_results.get(task_id, {}),
            })
            break
        if status == "error":
            yield _ndjson_line({
                "event": "error", "code": 500,
                "msg": park_stream_results.get(task_id, {}).get("msg", "Task failed"),
                "data": None,
            })
            break
        await asyncio.sleep(0.01)


def register_park_routes(app):
    """向 FastAPI 注册车位检测路由。

    参数:
        app:   FastAPI 应用实例
    注册的路由:
        POST /parkDetected                 — 图片车位检测
        POST /parkVideoDetectedWithFrame   — 视频逐帧流式检测（NDJSON）
        GET  /getParkLatestFrame           — 获取实时检测最新帧
        GET  /parkVideoStatus              — 查询流式任务状态
    """
    @app.post("/parkDetected")
    async def park_detected(
        file: UploadFile = File(...),
        parking_spots_file: UploadFile = File(None),
    ):
        """图片车位检测接口。"""
        try:
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file.filename
            file_path.write_bytes(await file.read())

            img = cv2.imread(str(file_path))
            if img is None:
                raise ValueError("无法读取图像")

            parking_lot_info = {}
            custom_spots = None
            if parking_spots_file is not None:
                try:
                    parking_lot_info, custom_spots = _parse_parking_spots_json(
                        await parking_spots_file.read(), img.shape)
                except ValueError as e:
                    return JSONResponse({"code": 400, "msg": str(e), "data": None})

            detections = detect_vehicles(img)
            occupied, total_spots, spot_regions = _estimate_parking_spots(
                img.shape, detections, custom_spots)
            annotated = _draw_parking_overlay(img, detections, spot_regions)

            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_path = detected_dir / f"park_{file_path.name}"
            cv2.imwrite(str(output_path), annotated)

            data = {
                "vehicle_count": len(detections),
                "total_spots": total_spots,
                "occupied_spots": occupied,
                "free_spots": total_spots - occupied,
                "occupancy_rate": round(occupied / total_spots, 2) if total_spots > 0 else 0,
                "parking_lot_info": parking_lot_info,
                "spot_regions": spot_regions,
                "url": str(output_path).replace("\\", "/"),
                "result_dir": str(detected_dir).replace("\\", "/"),
            }
            data["result_json"] = _result_json_url(detected_dir)
            response_body = {"code": 200, "msg": "Park Detected Success", "data": data}
            _save_park_api_response(detected_dir, response_body)
            return JSONResponse(response_body)
        except Exception as e:
            import traceback
            print("Park Image Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/parkVideoDetectedWithFrame")
    async def park_video_detected_with_frame(
        file: UploadFile = File(...),
        parking_spots_file: UploadFile = File(None),
        frame_interval: int = Form(FRAME_DETECT_INTERVAL_DEFAULT),
    ):
        """视频逐帧流式车位检测接口（NDJSON）。"""
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

        parking_lot_info = {}
        custom_spots = None
        if parking_spots_file is not None:
            try:
                parking_lot_info, custom_spots = _parse_parking_spots_json(
                    await parking_spots_file.read(), (height, width))
            except ValueError as e:
                return JSONResponse({"code": 400, "msg": str(e), "data": None})

        task_id = str(uuid.uuid4())
        detected_dir = Path("upload/detected") / task_id
        detected_dir.mkdir(parents=True, exist_ok=True)
        output_video_path = detected_dir / f"park_{Path(filename).stem}.mp4"
        output_url = str(output_video_path).replace("\\", "/")

        processing_status[task_id] = "processing"
        executor.submit(
            process_park_video_stream_task,
            task_id, str(video_path.resolve()),
            str(output_video_path.resolve()), output_url,
            detected_dir, interval, parking_lot_info, custom_spots,
        )
        return StreamingResponse(
            _park_ndjson_generator(task_id, {
                "session_id": task_id, "fps": fps,
                "width": width, "height": height,
                "total_frames": total_frames, "frame_interval": interval,
            }),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/getParkLatestFrame")
    async def get_park_latest_frame(task_id: str = Query(...)):
        with frame_lock:
            frame_data = latest_frames.get(task_id)
        if frame_data is None:
            return JSONResponse({"frame": None, "msg": "Processing not started or frame not ready"})
        return JSONResponse({"frame": frame_data})

    @app.get("/parkVideoStatus")
    async def park_video_status(task_id: str = Query(...)):
        status = processing_status.get(task_id, "not_found")
        result = park_stream_results.get(task_id, {})
        return JSONResponse({
            "task_id": task_id, "status": status,
            "result": result, "output_path": result.get("url", ""),
        })
