# yolo_interface.py
import logging

import cv2
import numpy as np
import uuid
from pathlib import Path
from fastapi import File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)

MODEL_TYPES = ["yolov8n", "yolov8s", "yolo11n", "yolo11s"]
CLASS_ALLSETS = {"全部" : "all"}
FRAME_DETECT_INTERVAL_DEFAULT = 5


def _normalize_class_name(class_name: str) -> tuple[str, bool]:
    """
    标准化类别名称
    :param class_name: 原始类别名
    :return: (标准化名称, 是否为原始名称(未做映射转换))
    """
    stripped_name = class_name.strip()
    norm_name = CLASS_ALLSETS.get(stripped_name, stripped_name)
    return norm_name, norm_name == stripped_name


def _annotate_plot_kwargs(image_shape: tuple) -> dict:
    height, width = image_shape[:2]
    base = (width + height) / 2
    return {
        "pil": True,
        "font_size": max(round(base * 0.017), 16),
        "line_width": max(round(base * 0.0015), 2)
    }


def _ndjson_line(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def register_yolo_routes(app, models):
    @app.post("/yoloDetected")
    async def yolo_detected(file: UploadFile = File(...),
                            class_name: str = Form(...),
                            model_type: str = Form(...)):
        try:
            logging.info("=== 图片检测请求 ===")
            logging.info("  模型: %s | 检测目标: %s | 文件: %s", model_type, class_name, file.filename)
            if model_type not in models:
                return JSONResponse({
                    "code": 400,
                    "msg": f"Model '{model_type}' not supported. Available: {list(models.values())}",
                    "data": None
                })
            model = models[model_type]
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            file_path = upload_dir / file.filename
            with open(file_path, "wb") as f:
                f.write(await file.read())

            # 使用传入的 model
            if class_name not in model.names.values():
                return JSONResponse(
                    {
                        "code": 400,
                        "msg": f"Class '{class_name}' not supported. Available: {list(model.names.values())}",
                        "data": None,
                    }
                )

            target_id = next(k for k, v in model.names.items() if v == class_name)
            results = model.predict(
                source=str(file_path), save=False, show=False, verbose=False
            )
            result = results[0]

            count = 0
            if result.boxes is not None and len(result.boxes) > 0:
                cls_array = result.boxes.cls.cpu().numpy()
                mask = cls_array == target_id
                count = int(mask.sum())
                result.boxes = result.boxes[mask]
            else:
                result.boxes = None

            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_path = detected_dir / f"yolo_{file.filename}"
            result.save(filename=str(output_path))

            logging.info("  检测完成: 检出 %d 个目标 [类别: %s]", count, class_name)
            logging.info("  结果路径: %s", output_path)

            return JSONResponse(
                {
                    "code": 200,
                    "msg": "Success",
                    "data": {
                        "numbers": count,
                        "class_name": class_name,
                        "url": str(output_path).replace("\\", "/"),
                    },
                }
            )
        except Exception as e:
            logging.exception("图片检测异常: %s", e)
            return JSONResponse({"code": 500, "msg": str(e), "data": None})

    @app.post("/yoloVideoDetected")
    async def yolo_video_detected(file: UploadFile = File(...),
                                  class_name: str = Form(...),
                                  model_type: str = Form(...)):
        try:
            logging.info("=== 视频检测请求 ===")
            logging.info("  模型: %s | 检测目标: %s | 文件: %s", model_type, class_name, file.filename)
            if model_type not in models:
                return JSONResponse({
                    "code": 400,
                    "msg": f"Model '{model_type}' not supported. Available: {list(models.values())}",
                    "data": None
                })
            model = models[model_type]
            # --- 1. 类别校验 ---
            if class_name not in model.names.values():
                return JSONResponse(
                    {
                        "code": 400,
                        "msg": f"Class '{class_name}' not supported. Available: {list(model.names.values())}",
                        "data": None,
                    }
                )
            target_id = next(k for k, v in model.names.items() if v == class_name)

            # --- 2. 保存上传视频 ---
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            video_path = upload_dir / file.filename
            with open(video_path, "wb") as f:
                f.write(await file.read())

            # --- 3. 创建输出目录 ---
            detected_dir = Path("upload/detected") / str(uuid.uuid4())
            detected_dir.mkdir(parents=True, exist_ok=True)
            output_video_path = detected_dir / f"yolo_{Path(file.filename).stem}.mp4"

            # --- 4. 打开视频读取器 ---
            cap = cv2.VideoCapture(str(video_path))
            if not cap.isOpened():
                raise ValueError("无法打开上传的视频文件")

            # 获取视频属性
            fps = int(cap.get(cv2.CAP_PROP_FPS))
            width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
            height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
            total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

            logging.info("  视频信息: %dx%d, %d FPS, %d 帧", width, height, fps, total_frames)

            # 初始化 VideoWriter（H.264 编码，.mp4 容器）
            fourcc = cv2.VideoWriter_fourcc(*"mp4v")  # 注意：有些系统需用 'avc1'
            out = cv2.VideoWriter(str(output_video_path), fourcc, fps, (width, height))
            if not out.isOpened():
                raise RuntimeError("无法创建输出视频文件，请检查 OpenCV 编解码器支持")

            total_count = 0

            # --- 5. 逐帧处理 ---
            while True:
                ret, frame = cap.read()
                if not ret:
                    break

                # YOLO 推理（仅指定类别）
                results = model.predict(
                    source=frame,
                    classes=[target_id],
                    verbose=False,
                    conf=0.25,  # 可选：置信度阈值
                )
                result = results[0]

                # 统计当前帧目标数
                if result.boxes is not None:
                    total_count += len(result.boxes)

                # 将带标注的帧写入输出视频
                annotated_frame = result.plot()  # 返回带框的 BGR 图像
                out.write(annotated_frame)

            # --- 6. 释放资源 ---
            cap.release()
            out.release()

            # --- 7. 验证输出文件是否存在 ---
            if not output_video_path.exists() or output_video_path.stat().st_size == 0:
                raise FileNotFoundError("输出视频未生成或为空")

            logging.info("  视频检测完成: 共检出 %d 个目标 [类别: %s]", total_count, class_name)
            logging.info("  结果路径: %s", output_video_path)

            return JSONResponse(
                {
                    "code": 200,
                    "msg": "Video Detected Success",
                    "data": {
                        "numbers": total_count,
                        "class_name": class_name,
                        "url": str(output_video_path).replace("\\", "/"),
                    },
                }
            )

        except Exception as e:
            logging.exception("视频检测异常: %s", e)
            return JSONResponse({"code": 500, "msg": str(e), "data": None})