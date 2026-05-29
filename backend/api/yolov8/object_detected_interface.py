# yolo_interface.py
import cv2
import numpy as np
import uuid
from pathlib import Path
from fastapi import File, UploadFile, Form, HTTPException
from fastapi.responses import JSONResponse

def register_yolo_routes(app, model):
    @app.post("/yoloDetected")
    async def yolo_detected(file: UploadFile = File(...), class_name: str = Form(...)):
        try:
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
            import traceback

            print("YOLO Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})
        
    @app.post("/yoloVideoDetected")
    async def yolo_video_detected(file: UploadFile = File(...), class_name: str = Form(...)):
        try:
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
            import traceback

            print("YOLO Video Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})