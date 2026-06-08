"""Gradio Web 端共用：API 调用、资源路径、主题样式。"""

from __future__ import annotations

import base64
import io
import json
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Generator, Iterable

import numpy as np
import requests
import gradio as gr
from PIL import Image

API_BASE = "http://127.0.0.1:8000"

# 实时预览：限制 UI 刷新率并缩小帧图，减轻 Gradio 每帧全量重绘卡顿
PREVIEW_MAX_WIDTH = 960
UI_MAX_FPS = 10.0
_SKIP_OUTPUT = gr.update()
# 右侧实时帧：numpy 预览 + 保持宽高比（配合 THEME_CSS .stream-frame）
STREAM_FRAME_IMAGE_KWARGS = {
    "type": "numpy",
    "format": "jpeg",
    "elem_classes": ["stream-frame"],
}
BACKEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_ROOT.parent

TARGET_LABEL_MAP = {
    "全部": "all",
    "行人": "person",
    "汽车": "car",
    "自行车": "bicycle",
    "摩托车": "motorcycle",
    "公交车": "bus",
    "交通信号灯": "traffic light",
}

THEME_CSS = """
/* 对齐 Main.qml / AppTheme.qml */
.gradio-container { max-width: 100% !important; }
#main-title { text-align: center; margin: 8px 0 12px 0; }
#main-title h1,
#main-title .md h1,
#main-title p {
    color: #1565c0 !important;
    font-weight: 700 !important;
}
.tab-nav button {
    background: #333333 !important;
    color: #ffffff !important;
    border: 1px solid #555555 !important;
}
.tab-nav button.selected {
    background: #ffffff !important;
    color: #000000 !important;
}
.btn-upload {
    background: #4CAF50 !important;
    border-color: #4CAF50 !important;
    color: #fff !important;
}
.btn-detect {
    background: #2196F3 !important;
    border-color: #2196F3 !important;
    color: #fff !important;
}
/* 左侧：展示类组件保持通栏；仅按钮类不拉伸、固定合理尺寸 */
.left-panel {
    align-self: flex-start !important;
}
.left-panel .gr-image,
.left-panel .gr-video,
.left-panel .gr-file,
.left-panel .gr-gallery,
.left-panel .gr-audio {
    width: 100% !important;
    max-width: 100% !important;
    align-self: stretch !important;
}
.left-panel .gr-dropdown,
.left-panel .gr-slider,
.left-panel .gr-checkbox,
.left-panel .gr-radio,
.left-panel .gr-number,
.left-panel .gr-textbox,
.left-panel .gr-markdown {
    width: 100% !important;
    max-width: 100% !important;
    align-self: stretch !important;
}
/* 仅操作按钮（gr.Button）；不含 Image/Video 内原生上传 button */
.left-panel .gr-button {
    width: auto !important;
    min-width: 110px !important;
    max-width: none !important;
    height: 32px !important;
    min-height: 32px !important;
    max-height: 36px !important;
    flex: 0 0 auto !important;
    align-self: flex-start !important;
}
.left-panel .btn-detect,
.left-panel .gr-button.btn-detect {
    width: 110px !important;
    min-width: 110px !important;
    max-width: 110px !important;
}
/* Image/Video 上传区：占满组件高度，占位提示水平垂直居中 */
.left-panel [data-testid="image"],
.left-panel [data-testid="video"] {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    width: 100% !important;
    height: 100% !important;
    flex: 1 1 auto !important;
}
.left-panel [data-testid="image"] .upload-container,
.left-panel [data-testid="video"] .upload-container {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    width: 100% !important;
    height: 100% !important;
    flex: 1 1 auto !important;
}
.left-panel [data-testid="image"] button.center,
.left-panel [data-testid="image"] button.flex,
.left-panel [data-testid="video"] button.center,
.left-panel [data-testid="video"] button.flex {
    width: 100% !important;
    min-width: 100% !important;
    max-width: 100% !important;
    height: 100% !important;
    min-height: 100% !important;
    max-height: none !important;
    flex: 1 1 auto !important;
    align-self: stretch !important;
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
}
.left-panel [data-testid="image"] button .wrap,
.left-panel [data-testid="video"] button .wrap {
    display: flex !important;
    flex-direction: column !important;
    justify-content: center !important;
    align-items: center !important;
    text-align: center !important;
    width: 100% !important;
    height: auto !important;
    min-height: unset !important;
    margin: auto !important;
    padding-top: 0 !important;
}
/* 实时帧：contain 自适应，与结果视频一致，避免 cover/100% 拉伸 */
.stream-frame .image-container,
.stream-frame [data-testid="image"] {
    display: flex !important;
    flex-direction: column !important;
    align-items: center !important;
    justify-content: center !important;
}
.stream-frame .upload-container {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
}
.stream-frame .image-container > button {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
    min-height: unset !important;
    max-height: none !important;
}
.stream-frame .image-frame {
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    width: 100% !important;
    height: 100% !important;
}
.stream-frame .image-frame img,
.stream-frame [data-testid="image"] img {
    object-fit: contain !important;
    width: auto !important;
    height: auto !important;
    max-width: 100% !important;
    max-height: 100% !important;
}
.panel-divider {
    border-left: 1px solid #cccccc;
    padding-left: 12px;
    align-self: flex-start !important;
}
.license-table-wrap {
    width: 100%;
    max-width: 100%;
    overflow-x: auto;
}
.license-table {
    border-collapse: collapse;
    width: 100%;
    max-width: 720px;
    min-width: 560px;
    margin: 0 auto;
    table-layout: fixed;
    background: #fff;
}
.license-table td {
    border: 1px solid #000;
    padding: 8px 10px;
    text-align: center;
    font-size: 14px;
    color: #000;
    height: 36px;
    vertical-align: middle;
}
.license-table .label-col {
    width: 22%;
    min-width: 88px;
    font-weight: bold;
}
.license-table .value-col {
    width: 78%;
    white-space: nowrap;
}
"""


def resolve_asset(relative_path: str) -> str | None:
    """解析样例图片/视频路径（与 Qt resolveBackendResourceUrl 逻辑一致）。"""
    rel = Path(relative_path)
    file_name = rel.name
    candidates = [
        PROJECT_ROOT / rel,
        BACKEND_ROOT / rel,
        BACKEND_ROOT / "imgs" / file_name,
        PROJECT_ROOT / "images" / file_name,
        PROJECT_ROOT / "video" / file_name,
        BACKEND_ROOT / "videos" / file_name,
    ]
    for candidate in candidates:
        path = candidate.resolve()
        if path.is_file():
            return str(path)
    return None


def get_launch_allowed_paths() -> list[str]:
    """
    Gradio 仅允许访问 cwd、系统 temp 或 allowed_paths 下的文件。
    app.py 在 backend/ 目录运行，样例与检测结果在 front/video、upload 等目录。
    """
    candidates = [
        PROJECT_ROOT,
        PROJECT_ROOT / "video",
        PROJECT_ROOT / "images",
        BACKEND_ROOT,
        BACKEND_ROOT / "videos",
        BACKEND_ROOT / "imgs",
        BACKEND_ROOT / "upload",
    ]
    allowed: list[str] = []
    seen: set[str] = set()
    for directory in candidates:
        resolved = directory.resolve()
        key = str(resolved)
        if key in seen:
            continue
        if resolved.exists():
            allowed.append(key)
            seen.add(key)
    return allowed


def load_sample_asset(relative_path: str) -> str:
    """加载样例资源供 Gradio 组件使用（路径须在 launch allowed_paths 内）。"""
    path = resolve_asset(relative_path)
    if not path:
        raise FileNotFoundError(
            f"样例文件不存在：{relative_path}（已搜索 front/video、front/images、backend/videos 等目录）"
        )
    return path


def resolve_result_path(relative_url: str) -> str | None:
    if not relative_url:
        return None
    path = (BACKEND_ROOT / relative_url.replace("\\", "/")).resolve()
    return str(path) if path.is_file() else None


def format_json(data: Any) -> str:
    if data is None:
        return ""
    if isinstance(data, str):
        text = data.strip()
        if not text:
            return ""
        try:
            return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            return text
    return json.dumps(data, ensure_ascii=False, indent=2)


def decode_b64_jpeg(b64_text: str) -> Image.Image | None:
    if not b64_text:
        return None
    try:
        raw = base64.b64decode(b64_text)
        return Image.open(io.BytesIO(raw)).convert("RGB")
    except Exception:
        return None


def resize_for_preview(image: Image.Image, max_width: int = PREVIEW_MAX_WIDTH) -> Image.Image:
    """缩小实时预览图，降低浏览器端渲染与传输开销。"""
    if image.width <= max_width:
        return image
    ratio = max_width / float(image.width)
    height = max(1, int(image.height * ratio))
    return image.resize((max_width, height), Image.Resampling.BILINEAR)


def decode_b64_jpeg_preview(
    b64_text: str,
    max_width: int = PREVIEW_MAX_WIDTH,
) -> Image.Image | None:
    frame = decode_b64_jpeg(b64_text)
    if frame is None:
        return None
    return resize_for_preview(frame, max_width)


def image_for_gradio(image: Image.Image | None) -> np.ndarray | None:
    """PIL → numpy，配合 Gradio Image(type='numpy') 降低实时预览开销。"""
    if image is None:
        return None
    return np.asarray(image, dtype=np.uint8)


def check_api_health() -> tuple[bool, str]:
    try:
        resp = requests.get(f"{API_BASE}/docs", timeout=3)
        if resp.status_code == 200:
            return True, "推理服务器启动成功!"
        return False, f"推理服务器响应异常 (HTTP {resp.status_code})"
    except requests.RequestException as exc:
        return False, f"推理服务器未就绪：{exc}"


def post_image_detect(
    endpoint: str,
    image_path: str,
    extra_fields: dict[str, str] | None = None,
    timeout: int = 300,
) -> tuple[Image.Image | None, str, str]:
    """图片检测：返回 (结果图, 状态文案, JSON 文本)。"""
    fields = dict(extra_fields or {})
    with open(image_path, "rb") as file_obj:
        files = {"file": (Path(image_path).name, file_obj)}
        resp = requests.post(
            f"{API_BASE}{endpoint}",
            files=files,
            data=fields,
            timeout=timeout,
        )
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return None, f"后端返回非 JSON (HTTP {resp.status_code})", resp.text

    if payload.get("code") != 200:
        msg = payload.get("msg") or "检测失败"
        return None, msg, format_json(payload)

    data = payload.get("data") or {}
    rel_url = data.get("url", "")
    result_path = resolve_result_path(rel_url)
    if not result_path:
        return None, f"检测结果不存在：{rel_url}", format_json(payload)

    status = payload.get("msg") or "检测完成"
    return Image.open(result_path).convert("RGB"), status, format_json(payload)


def iter_ndjson_stream(
    endpoint: str,
    video_path: str,
    extra_fields: dict[str, str] | None = None,
    extra_files: dict[str, tuple[str, bytes, str]] | None = None,
    timeout: int = 600,
) -> Iterable[dict[str, Any]]:
    fields = dict(extra_fields or {})
    video_bytes = Path(video_path).read_bytes()
    files: list[tuple[str, tuple[str, bytes, str]]] = [
        ("file", (Path(video_path).name, video_bytes, "video/mp4")),
    ]
    if extra_files:
        for name, item in extra_files.items():
            files.append((name, item))

    with requests.post(
        f"{API_BASE}{endpoint}",
        files=files,
        data=fields,
        stream=True,
        timeout=timeout,
    ) as resp:
        if resp.status_code != 200:
            text = resp.text[:500]
            yield {"event": "error", "code": resp.status_code, "msg": text, "data": None}
            return

        for raw_line in resp.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue


def stream_video_detect(
    endpoint: str,
    video_path: str,
    extra_fields: dict[str, str] | None = None,
    extra_files: dict[str, tuple[str, bytes, str]] | None = None,
    on_frame: Callable[[dict[str, Any]], str] | None = None,
    *,
    ui_max_fps: float = UI_MAX_FPS,
    preview_max_width: int = PREVIEW_MAX_WIDTH,
) -> Generator[
    tuple[Any, Any, str, Any],
    None,
    None,
]:
    """
    消费 NDJSON 流，逐步 yield (实时帧, 结果视频路径, 状态, JSON)。

    帧事件节流到 ui_max_fps，且仅更新 Image+状态；Video/JSON 用 gr.update() 跳过，
    避免 Gradio 每帧重绘 Video 与 Textbox 导致卡顿。
    """
    last_frame: Image.Image | None = None
    result_video: str | None = None
    status = "正在检测，请稍候..."
    json_text = ""
    min_interval = 1.0 / ui_max_fps if ui_max_fps > 0 else 0.0
    last_ui_time = 0.0

    for event_obj in iter_ndjson_stream(endpoint, video_path, extra_fields, extra_files):
        event = event_obj.get("event", "")
        code = event_obj.get("code", -1)
        msg = event_obj.get("msg", "")
        data = event_obj.get("data") or {}

        if event == "start":
            total = data.get("total_frames", "?")
            status = f"实时检测中：共 {total} 帧"
            json_text = format_json(event_obj)
            last_ui_time = time.monotonic()
            yield image_for_gradio(last_frame), _SKIP_OUTPUT, status, _SKIP_OUTPUT
            continue

        if event == "frame":
            now = time.monotonic()
            if min_interval > 0 and (now - last_ui_time) < min_interval:
                continue

            b64 = data.get("frame_jpeg_base64", "")
            frame = decode_b64_jpeg_preview(b64, preview_max_width)
            if frame is not None:
                last_frame = frame
            idx = data.get("frame_index", 0)
            extra = on_frame(data) if on_frame else ""
            status = f"实时检测中：第 {idx} 帧" + (f" | {extra}" if extra else "")
            last_ui_time = now
            yield image_for_gradio(last_frame), _SKIP_OUTPUT, status, _SKIP_OUTPUT
            continue

        if event == "error" or code != 200:
            status = msg or "检测失败"
            json_text = format_json(event_obj)
            yield image_for_gradio(last_frame), _SKIP_OUTPUT, status, json_text
            return

        if event == "done":
            json_text = format_json(event_obj)
            rel_url = data.get("url", "")
            result_video = resolve_result_path(rel_url)
            status = msg or "检测完成"
            yield image_for_gradio(last_frame), result_video, status, json_text
            return

    if last_frame is None:
        yield None, None, "检测连接意外结束", json_text
    else:
        yield image_for_gradio(last_frame), result_video, status, json_text


def post_video_batch(
    endpoint: str,
    video_path: str,
    extra_fields: dict[str, str] | None = None,
    timeout: int = 600,
) -> tuple[str | None, str, str]:
    """整段视频检测，返回 (结果视频路径, 状态, JSON)。"""
    fields = dict(extra_fields or {})
    with open(video_path, "rb") as file_obj:
        files = {"file": (Path(video_path).name, file_obj, "video/mp4")}
        resp = requests.post(
            f"{API_BASE}{endpoint}",
            files=files,
            data=fields,
            timeout=timeout,
        )
    try:
        payload = resp.json()
    except json.JSONDecodeError:
        return None, f"后端返回非 JSON (HTTP {resp.status_code})", resp.text

    if payload.get("code") != 200:
        return None, payload.get("msg") or "检测失败", format_json(payload)

    data = payload.get("data") or {}
    rel_url = data.get("url", "")
    result_path = resolve_result_path(rel_url)
    if not result_path:
        return None, f"检测结果视频不存在：{rel_url}", format_json(payload)

    return result_path, payload.get("msg") or "检测完成", format_json(payload)


def clear_upload_temp() -> str:
    ok = True
    for sub in ("upload/detected", "upload/source"):
        dir_path = BACKEND_ROOT / sub
        if not dir_path.exists():
            dir_path.mkdir(parents=True, exist_ok=True)
            continue
        for child in dir_path.iterdir():
            try:
                if child.is_dir():
                    shutil.rmtree(child, ignore_errors=True)
                else:
                    child.unlink(missing_ok=True)
            except OSError:
                ok = False
    return "临时文件已清除成功。" if ok else "临时文件清除失败，请确认无检测任务运行后重试。"


def kill_listeners_on_port(port: int) -> None:
    import sys

    if sys.platform == "win32":
        result = subprocess.run(
            ["netstat", "-ano"],
            capture_output=True,
            text=True,
            check=False,
        )
        port_token = f":{port}"
        pids: set[int] = set()
        for line in result.stdout.splitlines():
            if port_token not in line or "LISTENING" not in line:
                continue
            parts = line.split()
            if len(parts) < 5:
                continue
            try:
                pids.add(int(parts[-1]))
            except ValueError:
                continue
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid)],
                capture_output=True,
                check=False,
            )
    else:
        subprocess.run(
            ["sh", "-c", f"lsof -ti tcp:{port} | xargs -r kill -9"],
            check=False,
        )


def restart_inference_server() -> str:
    kill_listeners_on_port(8000)
    time.sleep(0.5)
    python_exe = BACKEND_ROOT / (
        ".venv/Scripts/python.exe"
        if (BACKEND_ROOT / ".venv/Scripts/python.exe").exists()
        else ".venv/bin/python"
    )
    if not python_exe.is_file():
        return "未找到 backend/.venv Python，无法重启推理服务器。"

    subprocess.Popen(
        [str(python_exe), "main.py"],
        cwd=str(BACKEND_ROOT),
        creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
    )

    for _ in range(60):
        ok, msg = check_api_health()
        if ok:
            return msg
        time.sleep(1)
    return "已发送重启命令，但推理服务器尚未就绪，请稍后刷新状态。"


def license_table_html(
    name: str = "",
    gender: str = "",
    idno: str = "",
    address: str = "",
    license_type: str = "",
) -> str:
    rows = [
        ("姓名", name),
        ("性别", gender),
        ("身份证", idno),
        ("住址", address),
        ("驾照类型", license_type),
    ]
    body = []
    for label, value in rows:
        body.append(
            f'<tr><td class="label-col">{label}</td>'
            f'<td class="value-col">{value or ""}</td></tr>'
        )
    return (
        '<div class="license-table-wrap"><table class="license-table">'
        + "".join(body)
        + "</table></div>"
    )


def empty_license_table_html() -> str:
    return license_table_html()
