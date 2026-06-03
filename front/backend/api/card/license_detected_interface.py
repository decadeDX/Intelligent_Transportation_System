# license_detected_interface.py
"""驾驶证 OCR 识别 API：/driverLicenseDetected（图片）。"""

from __future__ import annotations

import asyncio
import uuid
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

from fastapi import File, Form, UploadFile
from fastapi.responses import JSONResponse

from utils.myutils import writ2json

from .license_detected import run_image_detection

executor = ThreadPoolExecutor(max_workers=2)


def _result_json_url(result_dir: Path) -> str:
    return str(result_dir / "result.json").replace("\\", "/")


def _save_license_api_response(result_dir: Path, response_body: dict) -> str:
    """将完整 API 响应写入 uuid 目录下的 result.json。"""
    result_dir.mkdir(parents=True, exist_ok=True)
    writ2json(response_body, f"{result_dir}/")
    return _result_json_url(result_dir)




def register_license_routes(app):
    """注册驾驶证 OCR 路由（/driverLicenseDetected）。"""
    @app.post("/driverLicenseDetected")
    async def driver_license_detected(
        file: UploadFile = File(...),
        recognition_type: str = Form("driver_license"),
    ):
        """
        图片文字识别（驾驶证等证件场景，基于 PP-OCRv5 ONNX + onnxruntime）。

        识别图中文字，解析姓名/性别/证号/住址/准驾车型等字段；
        完整响应写入 upload/detected/{uuid}/result.json。
        """
        try:
            upload_dir = Path("upload/source")
            upload_dir.mkdir(parents=True, exist_ok=True)
            filename = Path(file.filename or "upload.jpg").name
            file_path = upload_dir / filename

            content = await file.read()
            if not content:
                return JSONResponse({"code": 400, "msg": "上传图片为空", "data": None})
            file_path.write_bytes(content)

            detected_dir = Path("upload/detected") / str(uuid.uuid4())

            loop = asyncio.get_running_loop()
            data = await loop.run_in_executor(
                executor,
                partial(
                    run_image_detection,
                    file_path,
                    detected_dir,
                    recognition_type,
                ),
            )

            data["result_json"] = _result_json_url(detected_dir)
            response_body = {
                "code": 200,
                "msg": "Driver License OCR Success",
                "data": data,
            }
            _save_license_api_response(detected_dir, response_body)

            return JSONResponse(response_body)
        except Exception as e:
            import traceback

            print("Driver License OCR Error:", e)
            traceback.print_exc()
            return JSONResponse({"code": 500, "msg": str(e), "data": None})
