# line_detected.py
"""车道检测核心算法（由 line_detected_old.py 迁移）。"""

from __future__ import annotations

import math
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cv2
import numpy as np

OUTPUT_WIDTH = 1280
OUTPUT_HEIGHT = 720
CAR_CONF_THRESHOLD = 0.5
FOCAL_LENGTH = 1000.0
KNOWN_CAR_WIDTH_M = 2.0


_line_model = None
_model_inference_lock = threading.Lock()


def initialize_line_detector(model=None, model_path: Optional[Path | str] = None):
    """初始化车道检测所需的车辆检测模型。"""
    global _line_model

    if model is None and model_path is not None:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
    if model is None:
        raise ValueError("车道检测模型未初始化")
    _line_model = model


def _get_line_model():
    if _line_model is None:
        raise RuntimeError("车道检测模型未初始化，请先调用 initialize_line_detector")
    return _line_model


def region_of_interest(img: np.ndarray, vertices: np.ndarray) -> np.ndarray:
    mask = np.zeros_like(img)
    match_mask_color = 255
    cv2.fillPoly(mask, vertices, match_mask_color)
    return cv2.bitwise_and(img, mask)


def draw_lane_lines(
    img: np.ndarray,
    left_line: List[int],
    right_line: List[int],
    color: List[int] | None = None,
    thickness: int = 10,
) -> np.ndarray:
    if color is None:
        color = [0, 255, 0]

    line_img = np.zeros_like(img)
    poly_pts = np.array(
        [[
            (left_line[0], left_line[1]),
            (left_line[2], left_line[3]),
            (right_line[2], right_line[3]),
            (right_line[0], right_line[1]),
        ]],
        dtype=np.int32,
    )
    cv2.fillPoly(line_img, poly_pts, color)
    return cv2.addWeighted(img, 0.8, line_img, 0.5, 0.0)


def pipeline(image: np.ndarray) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    车道线检测流水线。

    返回 (标注后的 RGB 图像, 车道元数据)。
    """
    height = image.shape[0]
    width = image.shape[1]
    region_of_interest_vertices = [
        (0, height),
        (width / 2, height / 2),
        (width, height),
    ]

    gray_image = cv2.cvtColor(image, cv2.COLOR_RGB2GRAY)
    cannyed_image = cv2.Canny(gray_image, 100, 200)
    cropped_image = region_of_interest(
        cannyed_image,
        np.array([region_of_interest_vertices], np.int32),
    )

    lines = cv2.HoughLinesP(
        cropped_image,
        rho=6,
        theta=np.pi / 60,
        threshold=160,
        lines=np.array([]),
        minLineLength=40,
        maxLineGap=25,
    )

    left_line_x: List[int] = []
    left_line_y: List[int] = []
    right_line_x: List[int] = []
    right_line_y: List[int] = []

    if lines is not None:
        for line in lines:
            for x1, y1, x2, y2 in line:
                slope = (y2 - y1) / (x2 - x1) if (x2 - x1) != 0 else 0
                if math.fabs(slope) < 0.5:
                    continue
                if slope <= 0:
                    left_line_x.extend([x1, x2])
                    left_line_y.extend([y1, y2])
                else:
                    right_line_x.extend([x1, x2])
                    right_line_y.extend([y1, y2])

    min_y = int(image.shape[0] * (3 / 5))
    max_y = image.shape[0]

    left_detected = bool(left_line_x and left_line_y)
    right_detected = bool(right_line_x and right_line_y)

    if left_detected:
        poly_left = np.poly1d(np.polyfit(left_line_y, left_line_x, deg=1))
        left_x_start = int(poly_left(max_y))
        left_x_end = int(poly_left(min_y))
    else:
        left_x_start, left_x_end = 0, 0

    if right_detected:
        poly_right = np.poly1d(np.polyfit(right_line_y, right_line_x, deg=1))
        right_x_start = int(poly_right(max_y))
        right_x_end = int(poly_right(min_y))
    else:
        right_x_start, right_x_end = 0, 0

    lane_detected = left_detected and right_detected
    meta = {
        "lane_detected": lane_detected,
        "left_detected": left_detected,
        "right_detected": right_detected,
    }

    if not lane_detected:
        return image, meta

    lane_image = draw_lane_lines(
        image,
        [left_x_start, max_y, left_x_end, min_y],
        [right_x_start, max_y, right_x_end, min_y],
    )
    return lane_image, meta


def estimate_distance(bbox_width: float, bbox_height: float) -> float:
    """基于检测框宽度的简易距离估计（米）。"""
    if bbox_width <= 0:
        return 0.0
    return float((KNOWN_CAR_WIDTH_M * FOCAL_LENGTH) / bbox_width)


def overlay_vehicle_detections(
    frame_bgr: np.ndarray,
    conf_threshold: float = CAR_CONF_THRESHOLD,
) -> Tuple[np.ndarray, int, List[Dict[str, Any]]]:
    """在 BGR 帧上叠加车辆检测框与距离标注，返回 (frame, count, detections)。"""
    model = _get_line_model()
    with _model_inference_lock:
        results = model(frame_bgr, verbose=False)
    vehicle_count = 0
    detections: List[Dict[str, Any]] = []

    for result in results:
        boxes = result.boxes
        if boxes is None:
            continue
        for box in boxes:
            x1, y1, x2, y2 = map(int, box.xyxy[0])
            conf = float(box.conf[0])
            cls = int(box.cls[0])
            class_name = model.names[cls]
            if class_name != "car" or conf < conf_threshold:
                continue

            vehicle_count += 1
            bbox_width = x2 - x1
            bbox_height = y2 - y1
            distance_m = estimate_distance(bbox_width, bbox_height)
            label = f"{class_name} {conf:.2f}"
            distance_label = f"Distance: {distance_m:.2f}m"

            cv2.rectangle(frame_bgr, (x1, y1), (x2, y2), (0, 255, 255), 2)
            cv2.putText(
                frame_bgr,
                label,
                (x1, y1 - 10),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (0, 255, 255),
                2,
            )
            cv2.putText(
                frame_bgr,
                distance_label,
                (x1, y2 + 20),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.5,
                (255, 0, 0),
                2,
            )
            detections.append(
                {
                    "class_name": class_name,
                    "confidence": round(conf, 4),
                    "bbox": [x1, y1, x2, y2],
                    "distance_m": round(distance_m, 2),
                }
            )

    return frame_bgr, vehicle_count, detections


def process_frame(
    frame_bgr: np.ndarray,
    conf_threshold: float = CAR_CONF_THRESHOLD,
) -> Tuple[np.ndarray, Dict[str, Any]]:
    """
    处理单帧：车道检测 + 车辆检测叠加。

    输入/输出均为 BGR；输出尺寸固定为 1280x720。
    """
    resized_frame = cv2.resize(frame_bgr, (OUTPUT_WIDTH, OUTPUT_HEIGHT))
    rgb_frame = cv2.cvtColor(resized_frame, cv2.COLOR_BGR2RGB)

    lane_rgb, lane_meta = pipeline(rgb_frame)
    lane_bgr = cv2.cvtColor(lane_rgb, cv2.COLOR_RGB2BGR)

    lane_bgr, vehicle_count, vehicles = overlay_vehicle_detections(
        lane_bgr,
        conf_threshold=conf_threshold,
    )

    frame_meta = {
        "lane_detected": lane_meta["lane_detected"],
        "left_detected": lane_meta["left_detected"],
        "right_detected": lane_meta["right_detected"],
        "vehicle_count": vehicle_count,
        "vehicles": vehicles,
    }
    return lane_bgr, frame_meta
