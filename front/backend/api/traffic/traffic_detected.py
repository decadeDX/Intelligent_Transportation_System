# traffic_detected.py
"""车流量检测核心算法（由 traffic_interface_old.py 迁移）。"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

import cv2
import numpy as np

from utils.myutils import cv2AddChineseText

VEHICLE_CLASS_IDS = {2, 5, 7}  # COCO: car, bus, truck
CONF_THRESHOLD = 0.4
IMGSZ = 640
TEXT_COLOR = (250, 242, 131)
TEXT_SIZE = 40
BOX_COLOR = (167, 146, 11)

_traffic_model = None
_model_inference_lock = threading.Lock()


def initialize_traffic_detector(model=None, model_path: Optional[Path | str] = None):
    """初始化车流量检测模型。"""
    global _traffic_model

    if model is None and model_path is not None:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
    if model is None:
        raise ValueError("车流量检测模型未初始化")
    _traffic_model = model


def _get_traffic_model():
    if _traffic_model is None:
        raise RuntimeError("车流量检测模型未初始化，请先调用 initialize_traffic_detector")
    return _traffic_model


def traffic_ratio_cal(ratio: float, lanes: int) -> str:
    """根据小时流量与车道数判定道路状况。"""
    lanes = max(1, int(lanes))
    per_lane = ratio / lanes
    if per_lane < 200:
        return "畅通"
    if per_lane < 500:
        return "正常"
    return "拥堵"


def box_label(
    image: np.ndarray,
    box: Tuple[float, float, float, float],
    label: str = "",
    color: Tuple[int, int, int] = BOX_COLOR,
    txt_color: Tuple[int, int, int] = (255, 255, 255),
) -> None:
    p1 = (int(box[0]), int(box[1]))
    p2 = (int(box[2]), int(box[3]))
    cv2.rectangle(image, p1, p2, color, thickness=1, lineType=cv2.LINE_AA)
    if not label:
        return

    w, h = cv2.getTextSize(label, 0, fontScale=2 / 3, thickness=1)[0]
    outside = p1[1] - h >= 3
    p2_text = (p1[0] + w, p1[1] - h - 3 if outside else p1[1] + h + 3)
    cv2.rectangle(image, p1, p2_text, color, -1, cv2.LINE_AA)
    cv2.putText(
        image,
        label,
        (p1[0], p1[1] - 2 if outside else p1[1] + h + 2),
        0,
        2 / 3,
        txt_color,
        thickness=1,
        lineType=cv2.LINE_AA,
    )


def extract_vehicle_detections(
    frame_bgr: np.ndarray,
    conf_threshold: float = CONF_THRESHOLD,
) -> List[Tuple[List[int], float, str]]:
    """YOLO 推理，返回 DeepSort 所需 detections 列表。"""
    model = _get_traffic_model()
    with _model_inference_lock:
        results = model(frame_bgr, conf=conf_threshold, imgsz=IMGSZ, verbose=False)
    detections: List[Tuple[List[int], float, str]] = []

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            cls = int(box.cls[0])
            if cls not in VEHICLE_CLASS_IDS:
                continue
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            label = model.names[cls]
            detections.append(
                ([x1, y1, x2 - x1, y2 - y1], conf, label)
            )

    return detections


def process_frame(
    frame_bgr: np.ndarray,
    tracker,
    counter_set: Set[int],
    current_tracks: list,
    run_detect: bool,
) -> Tuple[np.ndarray, Dict[str, Any], list]:
    """
    处理单帧：可选推理 + DeepSort 追踪 + 标注。

    返回 (标注帧, 帧元数据, 更新后的 tracks 缓存)。
    """
    tracks = current_tracks

    if run_detect:
        detections = extract_vehicle_detections(frame_bgr)
        tracks = tracker.update_tracks(detections, frame=frame_bgr)

    annotated = frame_bgr.copy()
    active_tracks = 0

    for track in tracks:
        if not track.is_confirmed():
            continue
        counter_set.add(track.track_id)
        active_tracks += 1
        bbox = track.to_ltrb()
        box_label(
            annotated,
            bbox,
            f"ID:{track.track_id} {track.det_class}",
        )

    unique_count = len(counter_set)
    annotated = cv2AddChineseText(
        annotated,
        f"当前车流量: {unique_count}",
        (25, 50),
        TEXT_COLOR,
        TEXT_SIZE,
    )

    frame_meta = {
        "unique_vehicle_count": unique_count,
        "active_tracks": active_tracks,
        "detected": run_detect,
    }
    return annotated, frame_meta, tracks


def compute_traffic_summary(
    unique_vehicle_count: int,
    duration_sec: float,
    num_lanes: int,
) -> Dict[str, Any]:
    """计算小时流量与道路状况。"""
    hourly_ratio = (
        (unique_vehicle_count / duration_sec) * 3600 if duration_sec > 0 else 0.0
    )
    road_condition = traffic_ratio_cal(hourly_ratio, num_lanes)
    return {
        "unique_vehicle_count": unique_vehicle_count,
        "duration_sec": round(duration_sec, 3),
        "hourly_traffic_ratio": round(hourly_ratio, 2),
        "road_condition": road_condition,
        "num_lanes": max(1, int(num_lanes)),
    }
