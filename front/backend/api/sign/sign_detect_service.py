# sign_detect_service.py
"""交通标识检测服务：封装模型初始化、推理和绘制。"""

import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import cv2
import numpy as np

DEFAULT_SIGN_CLASS_IDS = (0, 1, 2)
DEFAULT_MODEL_IOU = 0.5
DEFAULT_MODEL_CONF = 0.3
SIGN_LABELS = {
    0: "warning",
    1: "prohibitory",
    2: "mandatory",
}

_sign_model = None
_model_inference_lock = threading.Lock()
_sign_class_ids = DEFAULT_SIGN_CLASS_IDS
_model_iou = DEFAULT_MODEL_IOU
_model_conf = DEFAULT_MODEL_CONF


def _parse_class_ids(raw_value: Optional[str]) -> Tuple[int, ...]:
    if not raw_value:
        return DEFAULT_SIGN_CLASS_IDS
    class_ids = []
    for item in raw_value.split(","):
        item = item.strip()
        if item:
            class_ids.append(int(item))
    return tuple(class_ids) or DEFAULT_SIGN_CLASS_IDS


def initialize_sign_detector(
    model=None,
    model_path: Optional[Path | str] = None,
    class_ids: Optional[Tuple[int, ...]] = None,
    iou: Optional[float] = None,
    conf: Optional[float] = None,
):
    """初始化交通标识检测服务。"""
    global _sign_model, _sign_class_ids, _model_iou, _model_conf

    if model is None and model_path is not None:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
    if model is None:
        raise ValueError("交通标识检测模型未初始化")

    env_class_ids = _parse_class_ids(os.getenv("SIGN_MODEL_CLASSES"))
    env_iou = os.getenv("SIGN_MODEL_IOU")
    env_conf = os.getenv("SIGN_MODEL_CONF")

    _sign_model = model
    _sign_class_ids = tuple(class_ids or env_class_ids)
    _model_iou = float(iou if iou is not None else (env_iou or DEFAULT_MODEL_IOU))
    _model_conf = float(conf if conf is not None else (env_conf or DEFAULT_MODEL_CONF))


def detect_signs(frame) -> List[Dict]:
    """YOLO 推理当前帧，返回交通标识检测列表。"""
    if _sign_model is None:
        raise RuntimeError("交通标识检测模型未初始化，请先调用 initialize_sign_detector")

    with _model_inference_lock:
        results = _sign_model(
            frame,
            classes=list(_sign_class_ids),
            verbose=False,
            iou=_model_iou,
            conf=_model_conf,
        )

    detections: List[Dict] = []
    if results and results[0].boxes is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        clss = results[0].boxes.cls.int().cpu().tolist()
        confs = results[0].boxes.conf.cpu().tolist()
        for box, cls_id, det_conf in zip(boxes, clss, confs):
            x1, y1, x2, y2 = map(int, box[:4])
            detections.append({
                "x1": int(x1), "y1": int(y1),
                "x2": int(x2), "y2": int(y2),
                "class_id": int(cls_id),
                "class_name": SIGN_LABELS.get(int(cls_id), f"sign_{int(cls_id)}"),
                "confidence": round(float(det_conf), 3),
            })
    return detections


def draw_sign_overlay(frame, detections: List[Dict]) -> np.ndarray:
    """在帧上绘制交通标识检测结果。"""
    annotated = frame.copy()
    color_map = {0: (0, 255, 255), 1: (0, 0, 255), 2: (255, 0, 255)}
    for det in detections:
        cls_id = det["class_id"]
        color = color_map.get(cls_id, (0, 255, 0))
        x1, y1, x2, y2 = det["x1"], det["y1"], det["x2"], det["y2"]
        cv2.rectangle(annotated, (x1, y1), (x2, y2), color, 2)
        label = f"{det['class_name']} {det['confidence']:.2f}"
        cv2.putText(annotated, label, (x1, max(y1 - 6, 15)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1)
    return annotated

