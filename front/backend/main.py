# main.py

import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from ultralytics import YOLO
import numpy as np

# ===== 路径设置 =====
BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_DIR = BASE_DIR / "models"
MODEL_TYPES = ["yolov8n", "yolov8s", "yolo11n", "yolo11s"]

# ===== 目录设置 =====
UPLOAD_SOURCE_DIR = BASE_DIR / "upload" / "source"
UPLOAD_DETECTED_DIR = BASE_DIR / "upload" / "detected"
RESULTS_DIR = BASE_DIR / "results"
UPLOAD_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DETECTED_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)



# ===== Lifespan =====
@asynccontextmanager
async def lifespan(app: FastAPI):

    print("正在加载项目所有模型...")
    yolo_models = {}
    for model_type in MODEL_TYPES:
        model_path = WEIGHTS_DIR / f"{model_type}.onnx"
        print(f"正在加载 YOLO 目标检测模型: {model_type} ({model_path})")
        yolo_models[model_type] = YOLO(model_path, task="detect")

    from api.plate.onnx_infer import load_models
    from api.plate.plate_detected_interface import (
        register_plate_routes,
        _resolve_plate_detect_model_path,
    )

    plate_detect_path = _resolve_plate_detect_model_path(WEIGHTS_DIR)
    plate_rec_path = WEIGHTS_DIR / "plate_rec_color.onnx"
    print(f"正在加载车牌检测模型: {plate_detect_path}")
    print(f"正在加载车牌识别模型: {plate_rec_path}")
    detect_session, rec_session = load_models(
        str(plate_detect_path),
        str(plate_rec_path),
    )

    # 注册路由
    from api.yolov8.object_detected_interface import register_yolo_routes
    print("正在注册 YOLO 目标检测路由...")
    register_yolo_routes(app, yolo_models)
    print("正在注册车牌检测路由...")
    register_plate_routes(app, detect_session, rec_session)
    print("所有模型与路由初始化完成，服务已就绪！")
    yield

    print("应用正在关闭...")

# 创建 FastAPI 实例
app = FastAPI(title="多模态检测 API", version="1.0", lifespan=lifespan)

# CORS：allow_credentials=True 不能与 allow_origins=["*"] 同时使用，否则浏览器会 Failed to fetch
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)


@app.get("/")
async def root():
    return FileResponse(BASE_DIR / "yolov8_detected.html")


@app.get("/yolov8_detected.html")
async def yolov8_detected_page():
    return FileResponse(BASE_DIR / "yolov8_detected.html")


@app.get("/plate_detected.html")
async def plate_detected_page():
    return FileResponse(BASE_DIR / "plate_detected.html")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)