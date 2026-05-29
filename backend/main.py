import os
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from onnxruntime.transformers.optimizer import MODEL_TYPES
from ultralytics import YOLO
import numpy as np

# ====路径设置===
BASE_DIR = Path(__file__).resolve().parent
WEIGHTS_DIR = BASE_DIR / "models"
MODEL_TYPES = ["yolov8n", "yolov8s", "yolo11n", "yolo11s"]

UPLOAD_SOURCE_DIR = BASE_DIR / "upload" / "source"
UPLOAD_DETECTED_DIR = BASE_DIR / "upload" / "detected"
RESULTS_DIR = BASE_DIR / "results"

# 启动前确保目录存在
UPLOAD_SOURCE_DIR.mkdir(parents=True, exist_ok=True)
UPLOAD_DETECTED_DIR.mkdir(parents=True, exist_ok=True)
RESULTS_DIR.mkdir(exist_ok=True)

# ===Lifespan====
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("正在加载项目所有模型...")
    yolo_model = {}
    select_model = YOLO(WEIGHTS_DIR/ "yolov8n.onnx")
    for model_type in MODEL_TYPES:
        model_path = WEIGHTS_DIR / f"{model_type}.onnx"
        print(f"正在加载YOLO目标检测模型：{model_type} ({model_path})")
        yolo_model[model_type] = YOLO(model_path, task="detect")

    from api.yolov8.object_detected_interface import register_yolo_routes
    print("正在注册 YOLO 目标检测路由...")
    # register_yolo_routes(app, yolo_model)
    register_yolo_routes(app, select_model)
    print("所有模型与路由初始化完成，服务已就绪！")
    yield
    print("应用正在关闭...")


#创建fastapi实例
app = FastAPI(title="多模态检测 API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],        # 允许所有来源（开发阶段）
    allow_credentials=True,
    allow_methods=["*"],        # 允许 GET、POST、PUT、DELETE 等所有方法
    allow_headers=["*"],        # 允许所有请求头（含 Authorization、Content-Type 等）
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8000)