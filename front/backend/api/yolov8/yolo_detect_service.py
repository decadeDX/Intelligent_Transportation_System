# yolo_detect_service.py
"""通用 YOLO 检测服务：封装模型注册、推理、绘制和后处理。"""

import threading
import uuid
from pathlib import Path
from typing import Dict, Optional

MODEL_TYPES = ["yolov8n", "yolov8s", "yolo11n", "yolo11s"]
CLASS_ALIASES = {"全部": "all"}

_models: Dict[str, object] = {}
_model_inference_lock = threading.Lock()


def initialize_yolo_detectors(
    models: Optional[Dict[str, object]] = None,
    model_paths: Optional[Dict[str, Path | str]] = None,
):
    """初始化通用 YOLO 检测模型，可传入已加载模型或模型路径。"""
    global _models

    if models is not None:
        _models = dict(models)
        return

    if not model_paths:
        raise ValueError("YOLO 检测模型未初始化")

    from ultralytics import YOLO

    loaded = {}
    for model_type, model_path in model_paths.items():
        loaded[model_type] = YOLO(model_path, task="detect")
    _models = loaded


def get_available_model_types() -> list[str]:
    return list(_models.keys()) or MODEL_TYPES


def get_model_names(model_type: str) -> dict:
    model = _get_model(model_type)
    return getattr(model, "names", {}) or {}


def normalize_class_name(class_name: str) -> tuple[str, bool]:
    normalized = CLASS_ALIASES.get(class_name.strip(), class_name.strip())
    return normalized, normalized == "all"


def resolve_target_id(model_type: str, class_name: str, detect_all: bool) -> Optional[int]:
    if detect_all:
        return None
    names = get_model_names(model_type)
    if class_name not in names.values():
        raise ValueError(f"Class '{class_name}' not supported. Available: {list(names.values())}")
    return next(k for k, v in names.items() if v == class_name)


def _get_model(model_type: str):
    if model_type not in _models:
        raise ValueError(
            f"Model type '{model_type}' not supported. Available: {get_available_model_types()}"
        )
    return _models[model_type]


def annotate_plot_kwargs(image_shape: tuple) -> dict:
    """生成 YOLO 标注参数。"""
    height, width = image_shape[:2]
    base = (width + height) / 2
    return {
        "pil": True,
        "font_size": max(round(base * 0.017), 16),
        "line_width": max(round(base * 0.0015), 2),
    }


def predict_frame(model_type: str, frame, detect_all: bool, target_id: Optional[int]):
    """执行单帧 YOLO 推理，返回 result 与当前帧目标数量。"""
    model = _get_model(model_type)
    predict_kwargs = {"source": frame, "verbose": False, "conf": 0.25}
    if not detect_all:
        predict_kwargs["classes"] = [target_id]
    with _model_inference_lock:
        result = model.predict(**predict_kwargs)[0]
    count = len(result.boxes) if result.boxes is not None else 0
    return result, count


def plot_yolo_frame(frame, plot_kwargs: dict, result, cached_result=None):
    """使用 YOLO result.plot 绘制检测帧。"""
    if cached_result is not None:
        return cached_result.plot(**plot_kwargs, img=frame)
    return result.plot(**plot_kwargs)


def run_image_detection(file_path: Path, class_name: str, detect_all: bool, model_type: str):
    """执行图片检测并保存标注图片。"""
    model = _get_model(model_type)
    with _model_inference_lock:
        results = model.predict(source=str(file_path), save=False, show=False, verbose=False)
    result = results[0]

    count = 0
    if detect_all:
        if result.boxes is not None and len(result.boxes) > 0:
            count = len(result.boxes)
    else:
        target_id = resolve_target_id(model_type, class_name, detect_all)
        if result.boxes is not None and len(result.boxes) > 0:
            cls_array = result.boxes.cls.cpu().numpy()
            mask = cls_array == target_id
            count = int(mask.sum())
            result.boxes = result.boxes[mask]
        else:
            result.boxes = None

    detected_dir = Path("upload/detected") / str(uuid.uuid4())
    detected_dir.mkdir(parents=True, exist_ok=True)
    output_path = detected_dir / f"yolo_{file_path.name}"
    plot_kwargs = annotate_plot_kwargs(result.orig_img.shape)
    result.save(filename=str(output_path), **plot_kwargs)

    return {
        "numbers": count,
        "class_name": class_name,
        "model_type": model_type,
        "url": str(output_path).replace("\\", "/"),
    }


def predict_video_frame(model_type: str, frame, detect_all: bool, target_id: Optional[int]):
    """普通视频检测单帧推理。"""
    result, count = predict_frame(model_type, frame, detect_all, target_id)
    return result, count, result.plot(**annotate_plot_kwargs(result.orig_img.shape))

