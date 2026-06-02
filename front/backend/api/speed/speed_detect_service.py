# speed_detect_service.py
"""车速检测服务：封装模型跟踪、速度估计和后处理。"""

import math
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ultralytics.solutions import speed_estimation

DEFAULT_METERS_PER_PIXEL = 0.1
SPEED_LINE_Y_TOLERANCE = 15
VEHICLE_TRACK_CLASS_IDS = (2, 3, 5, 7)
VEHICLE_CLASS_NAMES = frozenset({"car", "motorcycle", "bus", "truck"})
MIN_REPORT_SPEED_KMH = 3.0
MIN_REGRESSION_PX_PER_SEC = 1.0
MIN_ZONE_POSITION_SAMPLES = 2
MIN_RELIABLE_SAMPLE_COUNT = 6
MIN_ZONE_FRAME_SPAN = 5
MAX_PLAUSIBLE_SPEED_KMH = 120.0
MIN_SEGMENT_PIXEL_DIST = 0.5

_speed_model = None
_model_inference_lock = threading.Lock()


def ensure_track_dependencies() -> None:
    """确保 YOLO tracking 所需依赖 lap 已安装；缺失时通过 lapx 满足。"""
    try:
        import lap  # noqa: F401
    except ImportError:
        from ultralytics.utils.checks import check_requirements

        check_requirements("lapx>=0.5.2")
        import lap  # noqa: F401


def initialize_speed_detector(model=None, model_path: Optional[Path | str] = None):
    """初始化车速检测模型。"""
    global _speed_model
    ensure_track_dependencies()

    if model is None and model_path is not None:
        from ultralytics import YOLO

        model = YOLO(model_path, task="detect")
    if model is None:
        raise ValueError("车速检测模型未初始化")
    _speed_model = model


def resolve_meters_per_pixel(
    meters_per_pixel: float,
    reference_distance_m: float,
    reference_pixels: float,
) -> float:
    """标定换算系数：优先用参考距离计算，否则用直接传入的 mpp。"""
    if reference_distance_m > 0 and reference_pixels > 0:
        return reference_distance_m / reference_pixels
    if meters_per_pixel > 0:
        return meters_per_pixel
    return DEFAULT_METERS_PER_PIXEL


def create_speed_estimator(frame_width: int, frame_height: int):
    """创建 Ultralytics SpeedEstimator。"""
    if _speed_model is None:
        raise RuntimeError("车速检测模型未初始化，请先调用 initialize_speed_detector")
    line_pts = [(0, frame_height // 2), (frame_width, frame_height // 2)]
    return speed_estimation.SpeedEstimator(
        reg_pts=line_pts,
        names=_speed_model.names,
        view_img=False,
    )


def estimate_frame_speeds(
    frame,
    frame_index: int,
    fps: float,
    frame_width: int,
    frame_height: int,
    meters_per_pixel: float,
    track_state: Dict[int, dict],
    track_class_map: Dict[int, str],
    speed_obj,
) -> tuple:
    """执行单帧跟踪和速度更新，返回标注帧、车辆数、速度样本。"""
    if _speed_model is None:
        raise RuntimeError("车速检测模型未初始化，请先调用 initialize_speed_detector")

    with _model_inference_lock:
        tracks = _speed_model.track(
            frame,
            persist=True,
            show=False,
            verbose=False,
            classes=list(VEHICLE_TRACK_CLASS_IDS),
        )

    if (
        tracks
        and tracks[0].boxes is not None
        and tracks[0].boxes.id is not None
    ):
        try:
            processed_frame = speed_obj.estimate_speed(frame, tracks)
        except Exception:
            processed_frame = frame.copy()
        vehicle_count = len(tracks[0].boxes.id)
        frame_speed_samples = _update_calibrated_speeds(
            tracks,
            frame_index,
            float(fps),
            frame_width,
            frame_height,
            meters_per_pixel,
            track_state,
            track_class_map,
            speed_obj,
        )
        return processed_frame, vehicle_count, frame_speed_samples

    return frame.copy(), 0, _collect_frame_speed_samples(track_state, track_class_map)


def finalize_all_track_speeds(
    track_state: Dict[int, dict],
    speed_obj,
    fps: float,
    meters_per_pixel: float,
) -> None:
    """视频结束时，对所有 track 做最终速度结算，写入 speed_obj.dist_data。"""
    speed_obj.dist_data.clear()
    for tid_int, state in track_state.items():
        final_speed = _finalize_track_speed(state, fps, meters_per_pixel)
        if final_speed is not None:
            speed_obj.dist_data[tid_int] = final_speed


def build_final_speed_list(
    track_state: Dict[int, dict],
    track_class_map: dict,
    fps: float,
    meters_per_pixel: float,
) -> List[dict]:
    """视频处理完成后，生成所有车辆的最终速度列表。"""
    items = []
    for tid_int, state in track_state.items():
        class_name = track_class_map.get(tid_int, "unknown")
        if not _is_vehicle_class(class_name):
            continue
        zone_positions: List[Tuple[int, float, float]] = state.get("zone_positions") or []
        kmh = _robust_zone_speed_kmh(zone_positions, fps, meters_per_pixel)
        if kmh is None:
            kmh = state.get("speed_kmh")
        if kmh is None or kmh < MIN_REPORT_SPEED_KMH:
            continue
        reliable = _is_speed_reliable(zone_positions, float(kmh))
        items.append({
            "track_id": tid_int,
            "speed_kmh": round(float(kmh), 2),
            "class_name": class_name,
            "sample_count": len(zone_positions),
            "zone_frame_span": _zone_frame_span(zone_positions),
            "reliable": reliable,
        })
    items.sort(key=lambda x: x["track_id"])
    return items


def _px_per_sec_to_kmh(px_per_sec: float, meters_per_pixel: float) -> float:
    meters_per_sec = px_per_sec * meters_per_pixel
    return meters_per_sec * 3.6


def _is_near_speed_line(cy: float, line_y: float, tolerance: float) -> bool:
    return (line_y - tolerance) < cy < (line_y + tolerance)


def _is_vehicle_class(class_name: str) -> bool:
    return class_name in VEHICLE_CLASS_NAMES


def _track_ground_point(box) -> Tuple[float, float]:
    x1, y1, x2, y2 = box
    return float((x1 + x2) / 2), float(y2)


def _median(values: List[float]) -> float:
    ordered = sorted(values)
    n = len(ordered)
    mid = n // 2
    if n % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def _zone_frame_span(zone_positions: List[Tuple[int, float, float]]) -> int:
    if len(zone_positions) < 2:
        return 0
    return int(zone_positions[-1][0] - zone_positions[0][0])


def _segment_speeds_kmh(
    zone_positions: List[Tuple[int, float, float]],
    fps: float,
    meters_per_pixel: float,
) -> List[float]:
    speeds: List[float] = []
    for i in range(1, len(zone_positions)):
        f0, x0, y0 = zone_positions[i - 1]
        f1, x1, y1 = zone_positions[i]
        frame_delta = max(int(f1) - int(f0), 1)
        dt = frame_delta / fps
        dist = math.hypot(x1 - x0, y1 - y0)
        if dist < MIN_SEGMENT_PIXEL_DIST or dt <= 0:
            continue
        kmh = _px_per_sec_to_kmh(dist / dt, meters_per_pixel)
        if kmh >= MIN_REPORT_SPEED_KMH:
            speeds.append(kmh)
    return speeds


def _filter_segment_speeds(speeds: List[float]) -> List[float]:
    if not speeds:
        return []

    capped = [min(s, MAX_PLAUSIBLE_SPEED_KMH) for s in speeds]
    if len(capped) == 1:
        return capped
    if len(capped) == 2:
        lo, hi = sorted(capped)
        if hi > 2.5 * max(lo, 1.0) and hi > 60.0:
            return [lo]
        return capped

    ordered = sorted(capped)
    n = len(ordered)
    q1 = ordered[max(n // 4, 0)]
    q3 = ordered[min((3 * n) // 4, n - 1)]
    iqr = max(q3 - q1, 1.0)
    lo_bound = q1 - 1.5 * iqr
    hi_bound = min(q3 + 1.5 * iqr, MAX_PLAUSIBLE_SPEED_KMH)
    filtered = [s for s in capped if lo_bound <= s <= hi_bound]
    return filtered if filtered else [round(_median(capped), 2)]


def _is_speed_reliable(
    zone_positions: List[Tuple[int, float, float]],
    speed_kmh: float | None,
) -> bool:
    if speed_kmh is None:
        return False
    if speed_kmh < MIN_REPORT_SPEED_KMH or speed_kmh > MAX_PLAUSIBLE_SPEED_KMH:
        return False
    if len(zone_positions) < MIN_RELIABLE_SAMPLE_COUNT:
        return False
    if _zone_frame_span(zone_positions) < MIN_ZONE_FRAME_SPAN:
        return False
    return True


def _robust_zone_speed_kmh(
    zone_positions: List[Tuple[int, float, float]],
    fps: float,
    meters_per_pixel: float,
) -> float | None:
    if len(zone_positions) < MIN_ZONE_POSITION_SAMPLES or fps <= 0:
        return None

    segments = _filter_segment_speeds(
        _segment_speeds_kmh(zone_positions, fps, meters_per_pixel)
    )
    if len(segments) >= 2:
        return round(_median(segments), 2)
    if len(segments) == 1:
        return round(segments[0], 2)

    return _regression_speed_kmh(zone_positions, fps, meters_per_pixel)


def _regression_speed_kmh(
    zone_positions: List[Tuple[int, float, float]],
    fps: float,
    meters_per_pixel: float,
) -> float | None:
    if len(zone_positions) < MIN_ZONE_POSITION_SAMPLES or fps <= 0:
        return None

    ts = [idx / fps for idx, _, _ in zone_positions]
    pxs = [px for _, px, _ in zone_positions]
    pys = [py for _, _, py in zone_positions]
    n = len(ts)
    t_mean = sum(ts) / n

    def _slope(values: List[float]) -> float:
        v_mean = sum(values) / n
        var_t = sum((t - t_mean) ** 2 for t in ts)
        if var_t < 1e-12:
            return 0.0
        cov = sum((t - t_mean) * (v - v_mean) for t, v in zip(ts, values))
        return cov / var_t

    vx = _slope(pxs)
    vy = _slope(pys)
    px_per_sec = math.hypot(vx, vy)
    if px_per_sec < MIN_REGRESSION_PX_PER_SEC:
        return None
    return round(_px_per_sec_to_kmh(px_per_sec, meters_per_pixel), 2)


def _finalize_track_speed(state: dict, fps: float, meters_per_pixel: float) -> float | None:
    zone_positions: List[Tuple[int, float, float]] = state.get("zone_positions") or []
    if len(zone_positions) >= MIN_ZONE_POSITION_SAMPLES:
        final_speed = _robust_zone_speed_kmh(zone_positions, fps, meters_per_pixel)
        if final_speed is not None:
            state["speed_kmh"] = final_speed
            state["speed_reliable"] = _is_speed_reliable(zone_positions, final_speed)
            return final_speed
    return state.get("speed_kmh")


def _collect_frame_speed_samples(track_state: Dict[int, dict], track_class_map: dict) -> List[dict]:
    samples: List[dict] = []
    for tid_int, state in track_state.items():
        kmh = state.get("speed_kmh")
        if kmh is None:
            continue
        class_name = track_class_map.get(tid_int, "unknown")
        if not _is_vehicle_class(class_name):
            continue
        samples.append({
            "track_id": tid_int,
            "speed_kmh": float(kmh),
            "class_name": class_name,
        })
    samples.sort(key=lambda x: x["track_id"])
    return samples


def _update_calibrated_speeds(
    tracks,
    frame_index: int,
    fps: float,
    frame_width: int,
    frame_height: int,
    meters_per_pixel: float,
    track_state: Dict[int, dict],
    track_class_map: Dict[int, str],
    speed_obj,
) -> List[dict]:
    line_y = frame_height / 2.0
    names = getattr(_speed_model, "names", {}) or {}

    if not tracks or tracks[0].boxes is None or tracks[0].boxes.id is None:
        return _collect_frame_speed_samples(track_state, track_class_map)

    boxes = tracks[0].boxes.xyxy.cpu().numpy()
    ids = tracks[0].boxes.id.int().cpu().tolist()
    clss = tracks[0].boxes.cls.int().cpu().tolist()

    for box, tid, cls_id in zip(boxes, ids, clss):
        tid_int = int(tid)
        class_name = names.get(int(cls_id), str(int(cls_id)))
        if not _is_vehicle_class(class_name):
            continue

        px, py = _track_ground_point(box)
        if not (0 < px < frame_width):
            continue

        track_class_map[tid_int] = class_name
        in_zone = _is_near_speed_line(py, line_y, SPEED_LINE_Y_TOLERANCE)
        state = track_state.setdefault(
            tid_int,
            {"zone_positions": [], "in_zone": False},
        )

        was_in_zone = state.get("in_zone", False)
        if was_in_zone and not in_zone:
            _finalize_track_speed(state, fps, meters_per_pixel)

        if in_zone:
            if not was_in_zone:
                state["zone_positions"] = []

            zone_positions: List[Tuple[int, float, float]] = state.setdefault(
                "zone_positions", []
            )
            if not zone_positions or zone_positions[-1][0] != frame_index:
                zone_positions.append((frame_index, px, py))

            robust_kmh = _robust_zone_speed_kmh(zone_positions, fps, meters_per_pixel)
            if robust_kmh is not None and robust_kmh >= MIN_REPORT_SPEED_KMH:
                state["speed_kmh"] = robust_kmh
                state["speed_reliable"] = _is_speed_reliable(zone_positions, robust_kmh)
                speed_obj.dist_data[tid_int] = robust_kmh

            state["in_zone"] = True
        else:
            state["in_zone"] = False

    return _collect_frame_speed_samples(track_state, track_class_map)

