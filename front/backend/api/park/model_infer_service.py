# model_infer_service.py
"""车位检测模型推理服务：封装车辆检测模型加载、配置和推理。"""

import os
import threading
from pathlib import Path
from typing import List, Optional, Tuple

DEFAULT_CAR_CLASS_IDS = (2, 3, 5, 7)  # COCO: car=2, motorcycle=3, bus=5, truck=7
DEFAULT_MODEL_IOU = 0.5
DEFAULT_MODEL_CONF = None

_vehicle_model = None
_model_inference_lock = threading.Lock()
_car_class_ids = DEFAULT_CAR_CLASS_IDS
_model_iou = DEFAULT_MODEL_IOU
_model_conf = DEFAULT_MODEL_CONF


def _parse_class_ids(raw_value: Optional[str]) -> Tuple[int, ...]:
    if not raw_value:
        return DEFAULT_CAR_CLASS_IDS
    class_ids = []
    for item in raw_value.split(","):
        item = item.strip()
        if item:
            class_ids.append(int(item))
    return tuple(class_ids) or DEFAULT_CAR_CLASS_IDS


def _parse_optional_float(raw_value: Optional[str]) -> Optional[float]:
    if raw_value is None or raw_value == "":
        return None
    return float(raw_value)


def initialize_vehicle_detector(
    model=None,
    model_path: Optional[Path | str] = None,
    class_ids: Optional[Tuple[int, ...]] = None,
    iou: Optional[float] = None,
    conf: Optional[float] = None,
):
    """初始化车辆检测服务。

    可传入已加载的 YOLO 模型，也可传入模型路径让服务自行加载。
    环境变量可覆盖默认配置：
        PARK_MODEL_CLASSES: 车辆类别 ID，如 "2,3,5,7"
        PARK_MODEL_IOU:     推理 IOU 阈值
        PARK_MODEL_CONF:    推理置信度阈值
    """
    global _vehicle_model, _car_class_ids, _model_iou, _model_conf

    if model is None and model_path is not None:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
    if model is None:
        raise ValueError("车辆检测模型未初始化")

    env_class_ids = _parse_class_ids(os.getenv("PARK_MODEL_CLASSES"))
    env_iou = os.getenv("PARK_MODEL_IOU")
    env_conf = os.getenv("PARK_MODEL_CONF")

    _vehicle_model = model
    _car_class_ids = tuple(class_ids or env_class_ids)
    _model_iou = float(iou if iou is not None else (env_iou or DEFAULT_MODEL_IOU))
    _model_conf = conf if conf is not None else _parse_optional_float(env_conf)


def detect_vehicles(frame) -> List[Tuple[int, int, int, int, str, float]]:
    """对当前帧执行车辆检测，返回 [(x1,y1,x2,y2,class_name,conf), ...]。"""
    if _vehicle_model is None:
        raise RuntimeError("车辆检测模型未初始化，请先调用 initialize_vehicle_detector")

    inference_kwargs = {
        "classes": list(_car_class_ids),
        "verbose": False,
        "iou": _model_iou,
    }
    if _model_conf is not None:
        inference_kwargs["conf"] = _model_conf

    with _model_inference_lock:
        results = _vehicle_model(frame, **inference_kwargs)

    detections: List[Tuple[int, int, int, int, str, float]] = []
    if results and results[0].boxes is not None:
        boxes = results[0].boxes.xyxy.cpu().numpy()
        clss = results[0].boxes.cls.int().cpu().tolist()
        confs = results[0].boxes.conf.cpu().tolist()
        names = results[0].names
        for box, cls_id, det_conf in zip(boxes, clss, confs):
            x1, y1, x2, y2 = map(int, box[:4])
            class_name = names.get(cls_id, str(cls_id))
            detections.append((x1, y1, x2, y2, class_name, float(det_conf)))
    return detections

