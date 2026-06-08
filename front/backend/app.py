"""
基于 Gradio 的智慧交通系统 Web 端。

启动顺序：
  1. python main.py          # FastAPI 推理服务 (127.0.0.1:8000)
  2. python app.py           # 本 Web UI (127.0.0.1:7860)

功能与 front/Main.qml Qt 版一一对应，均通过 HTTP 调用 main.py 提供的 API。

若启动报错 startup-events 502：多为系统/Clash 等 HTTP 代理拦截了 localhost，
本文件已在导入 Gradio 前设置 NO_PROXY；仍失败时请临时关闭代理或手动设置环境变量。
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _ensure_localhost_no_proxy() -> None:
    """避免 HTTP(S)_PROXY 将 127.0.0.1 走代理，导致 Gradio startup-events 502。"""
    bypass = ("localhost", "127.0.0.1", "::1", "0.0.0.0", "<local>")
    for var in ("NO_PROXY", "no_proxy"):
        current = os.environ.get(var, "")
        parts = [p.strip() for p in current.split(",") if p.strip()]
        for host in bypass:
            if host not in parts:
                parts.append(host)
        os.environ[var] = ",".join(parts)


_ensure_localhost_no_proxy()

import gradio as gr
from gradio_support import (
    TARGET_LABEL_MAP,
    THEME_CSS,
    decode_b64_jpeg,
    empty_license_table_html,
    format_json,
    iter_ndjson_stream,
    license_table_html,
    post_image_detect,
    post_video_batch,
    get_launch_allowed_paths,
    load_sample_asset,
    stream_video_detect,
    STREAM_FRAME_IMAGE_KWARGS,
)

APP_TITLE = "基于YOLO的智慧交通系统"

# 视频 NDJSON 流式检测（生成器自动流式输出；Gradio 5.x 用 stream_every 控制刷新间隔）
STREAM_DETECT_KWARGS = {
    "show_progress": "hidden",
    "stream_every": 0.1,
}

# 检测页左右分栏：左右各占一半；左侧仅按钮不填充，展示组件保持通栏
LEFT_PANEL_COL = {"scale": 1, "elem_classes": ["left-panel"]}
RIGHT_PANEL_COL = {"scale": 1, "elem_classes": ["panel-divider"]}

def _image_path(file_obj) -> str | None:
    if file_obj is None:
        return None
    if isinstance(file_obj, dict):
        return file_obj.get("path") or file_obj.get("name")
    return str(file_obj)


def _video_path(file_obj) -> str | None:
    return _image_path(file_obj)


# ---------------------------------------------------------------------------
# 图片车辆行人检测
# ---------------------------------------------------------------------------
def detect_image_car_person(image, model_type, target_label):
    path = _image_path(image)
    if not path:
        return None, "请先上传待检测图片", ""
    class_name = TARGET_LABEL_MAP.get(target_label, "all")
    result_img, status, raw = post_image_detect(
        "/yoloDetected",
        path,
        {"class_name": class_name, "model_type": model_type},
    )
    try:
        payload = json.loads(raw)
        data = payload.get("data", {})
        if payload.get("code") == 200:
            status = (
                f"检测完成：模型 {data.get('model_type', model_type)}，"
                f"目标：{target_label}，数量：{data.get('numbers', 0)}"
            )
    except json.JSONDecodeError:
        pass
    return result_img, status, raw


# ---------------------------------------------------------------------------
# 视频车辆行人检测
# ---------------------------------------------------------------------------
def detect_video_car_person(video, model_type, target_label, realtime, frame_interval):
    path = _video_path(video)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return

    class_name = TARGET_LABEL_MAP.get(target_label, "all")
    fields = {"class_name": class_name, "model_type": model_type}

    if realtime:
        fields["frame_interval"] = str(int(frame_interval))
        for frame, result_vid, status, raw in stream_video_detect(
            "/yoloVideoDetectedWithFrame",
            path,
            fields,
            on_frame=lambda d: f"目标数 {d.get('numbers', 0)}",
        ):
            yield frame, result_vid, status, raw
        return

    result_vid, status, raw = post_video_batch(
        "/yoloVideoDetected", path, fields
    )
    yield None, result_vid, status, raw


# ---------------------------------------------------------------------------
# 图片车牌检测
# ---------------------------------------------------------------------------
def detect_image_plate(image):
    path = _image_path(image)
    if not path:
        return None, "请先上传待检测图片", ""
    result_img, status, raw = post_image_detect("/plateDetected", path)
    try:
        payload = json.loads(raw)
        if payload.get("code") == 200:
            n = (payload.get("data") or {}).get("plate_number", 0)
            status = f"检测完成：共识别 {n} 个车牌"
    except json.JSONDecodeError:
        pass
    return result_img, status, raw


# ---------------------------------------------------------------------------
# 视频车牌检测
# ---------------------------------------------------------------------------
def detect_video_plate(video, realtime, frame_interval):
    path = _video_path(video)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return

    if realtime:
        fields = {"frame_interval": str(int(frame_interval))}
        for frame, result_vid, status, raw in stream_video_detect(
            "/plateVideoDetectedWithFrame",
            path,
            fields,
        ):
            yield frame, result_vid, status, raw
        return

    result_vid, status, raw = post_video_batch("/plateVideoDetected", path)
    yield None, result_vid, status, raw


# ---------------------------------------------------------------------------
# 车速检测
# ---------------------------------------------------------------------------
def detect_car_speed(
    video,
    speed_mode,
    meters_per_pixel,
    start_line_y_ratio,
    end_line_y_ratio,
    zone_distance_m,
):
    path = _video_path(video)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return

    if speed_mode == "区间测速":
        endpoint = "/speedRegionVideoDetected"
        fields = {
            "frame_interval": "1",
            "start_line_y_ratio": str(start_line_y_ratio),
            "end_line_y_ratio": str(end_line_y_ratio),
            "zone_distance_m": str(zone_distance_m),
        }
    else:
        endpoint = "/speedVideoDetected"
        fields = {
            "frame_interval": "1",
            "meters_per_pixel": str(meters_per_pixel),
        }

    for frame, result_vid, status, raw in stream_video_detect(endpoint, path, fields):
        if isinstance(raw, str) and raw.strip():
            try:
                payload = json.loads(raw)
                if payload.get("event") == "done":
                    data = payload.get("data") or {}
                    status = (
                        f"检测完成：共 {data.get('vehicle_count', 0)} 辆车，"
                        f"可靠测速 {data.get('reliable_vehicle_count', 0)} 辆，"
                        f"最高时速 {data.get('max_speed_kmh', 0):.1f} km/h"
                    )
            except json.JSONDecodeError:
                pass
        yield frame, result_vid, status, raw


# ---------------------------------------------------------------------------
# 车道 / 车位 / 车流量
# ---------------------------------------------------------------------------
def detect_lane_video(video):
    path = _video_path(video)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return
    for item in stream_video_detect(
        "/lineVideoDetected", path, {"frame_interval": "1"}
    ):
        yield item


def detect_parking_video(video, position_file):
    path = _video_path(video)
    pos_path = _image_path(position_file)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return
    if not pos_path:
        yield None, None, "请上传车位定位 JSON 文件", ""
        return

    pos_bytes = Path(pos_path).read_bytes()
    extra_files = {
        "position": (Path(pos_path).name, pos_bytes, "application/json"),
    }
    for item in stream_video_detect(
        "/parkingVideoDetected",
        path,
        {"frame_interval": "1"},
        extra_files=extra_files,
    ):
        yield item


def detect_traffic_flow(video, num_lanes, frame_interval):
    path = _video_path(video)
    if not path:
        yield None, None, "请先上传待检测视频", ""
        return
    fields = {
        "num_lanes": str(int(num_lanes)),
        "frame_interval": str(int(frame_interval)),
    }
    for item in stream_video_detect("/trafficVideoDetected", path, fields):
        yield item


# ---------------------------------------------------------------------------
# 交通标识 / 驾照
# ---------------------------------------------------------------------------
def detect_traffic_sign(image):
    path = _image_path(image)
    if not path:
        return None, "请先上传待检测图片", ""
    result_img, status, raw = post_image_detect("/signDetected", path)
    try:
        payload = json.loads(raw)
        if payload.get("code") == 200:
            n = (payload.get("data") or {}).get("sign_number", 0)
            status = f"检测完成：共识别 {n} 个交通标识"
    except json.JSONDecodeError:
        pass
    return result_img, status, raw


def detect_driver_license(image):
    path = _image_path(image)
    if not path:
        return None, "请先上传待检测图片", empty_license_table_html()
    result_img, status, raw = post_image_detect("/driverLicenseDetected", path)
    name = gender = idno = address = lic_type = ""
    try:
        payload = json.loads(raw)
        if payload.get("code") == 200:
            data = payload.get("data") or {}
            name = data.get("name", "")
            gender = data.get("gender", "")
            idno = data.get("idno", "")
            address = data.get("address", "")
            lic_type = data.get("type", "")
            status = "检测完成"
    except json.JSONDecodeError:
        pass
    table = license_table_html(name, gender, idno, address, lic_type)
    return result_img, status, table


# ---------------------------------------------------------------------------
# UI 构建
# ---------------------------------------------------------------------------
def build_app() -> gr.Blocks:
    with gr.Blocks(
        title=APP_TITLE,
        css=THEME_CSS,
        theme=gr.themes.Default(primary_hue="blue", neutral_hue="gray"),
    ) as demo:
        gr.Markdown(f"# {APP_TITLE}", elem_id="main-title")
        with gr.Tabs():
            # ---- 1 图片车辆行人 ----
            with gr.Tab("图片车辆行人检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        img_cp_in = gr.Image(label="上传图片", type="filepath", height=360)
                        with gr.Row():
                            model_cp = gr.Dropdown(
                                ["yolov8n", "yolov8s", "yolo11n", "yolo11s"],
                                value="yolov8n",
                                label="选择 YOLO 模型",
                            )
                            target_cp = gr.Dropdown(
                                list(TARGET_LABEL_MAP.keys()),
                                value="全部",
                                label="检测目标",
                            )
                        btn_cp = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        img_cp_out = gr.Image(label="检测结果", height=360)
                        st_cp = gr.Textbox(label="状态", interactive=False)

                btn_cp.click(
                    detect_image_car_person,
                    [img_cp_in, model_cp, target_cp],
                    [img_cp_out, st_cp],
                )

            # ---- 2 视频车辆行人 ----
            with gr.Tab("视频车辆行人检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_yc_in = gr.Video(label="上传视频", height=320)
                        gr.Button("加载样例：video/street001.mp4", size="sm").click(
                            fn=lambda: load_sample_asset("video/street001.mp4"),
                            outputs=vid_yc_in,
                        )
                        with gr.Row():
                            model_yv = gr.Dropdown(
                                ["yolov8n", "yolov8s", "yolo11n", "yolo11s"],
                                value="yolov8n",
                                label="YOLO 模型",
                            )
                            target_yv = gr.Dropdown(
                                list(TARGET_LABEL_MAP.keys()),
                                value="汽车",
                                label="检测目标",
                            )
                        realtime_yv = gr.Checkbox(label="实时检测（NDJSON 逐帧）", value=True)
                        fi_yv = gr.Slider(1, 30, value=5, step=1, label="跳帧间隔 frame_interval")
                        btn_yv = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_yv = gr.Image(
                            label="实时检测帧",
                            height=280,
                            **STREAM_FRAME_IMAGE_KWARGS,
                        )
                        vid_yv_out = gr.Video(label="检测结果视频", height=280)
                        st_yv = gr.Textbox(label="状态", interactive=False)
                        json_yv = gr.Textbox(label="接口返回 JSON", lines=8)

                btn_yv.click(
                    detect_video_car_person,
                    [vid_yc_in, model_yv, target_yv, realtime_yv, fi_yv],
                    [frame_yv, vid_yv_out, st_yv, json_yv],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 3 图片车牌 ----
            with gr.Tab("图片车牌检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        img_pl_in = gr.Image(label="上传图片", type="filepath", height=360)
                        btn_pl = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        img_pl_out = gr.Image(label="检测结果", height=360)
                        st_pl = gr.Textbox(label="状态", interactive=False)
                        json_pl = gr.Textbox(label="接口返回 JSON", lines=14)

                btn_pl.click(
                    detect_image_plate,
                    [img_pl_in],
                    [img_pl_out, st_pl, json_pl],
                )

            # ---- 4 视频车牌 ----
            with gr.Tab("视频车牌检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_pl_in = gr.Video(label="上传视频", height=320)
                        for sample in (
                            "video/car_plate_video001.mp4",
                            "video/car_plate_video003.mp4",
                        ):
                            gr.Button(f"样例：{sample}", size="sm").click(
                                fn=lambda s=sample: load_sample_asset(s),
                                outputs=vid_pl_in,
                            )
                        realtime_pl = gr.Checkbox(label="实时检测", value=True)
                        fi_pl = gr.Slider(1, 30, value=5, step=1, label="frame_interval")
                        btn_vpl = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_pl = gr.Image(
                            label="实时帧", height=280, **STREAM_FRAME_IMAGE_KWARGS
                        )
                        vid_pl_out = gr.Video(label="结果视频", height=280)
                        st_vpl = gr.Textbox(label="状态", interactive=False)
                        json_vpl = gr.Textbox(label="接口返回 JSON", lines=8)

                btn_vpl.click(
                    detect_video_plate,
                    [vid_pl_in, realtime_pl, fi_pl],
                    [frame_pl, vid_pl_out, st_vpl, json_vpl],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 5 车速 ----
            with gr.Tab("车速检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_sp_in = gr.Video(label="上传视频", height=300)
                        gr.Button("样例：video/test_track.mp4", size="sm").click(
                            fn=lambda: load_sample_asset("video/test_track.mp4"),
                            outputs=vid_sp_in,
                        )
                        mode_sp = gr.Radio(
                            ["瞬时测速", "区间测速"],
                            value="瞬时测速",
                            label="测速模式",
                        )
                        mpp_sp = gr.Number(
                            label="meters_per_pixel",
                            value=0.1,
                            visible=True,
                        )
                        with gr.Group(visible=False) as region_group:
                            start_sp = gr.Slider(0, 1, value=0.4, label="start_line_y_ratio")
                            end_sp = gr.Slider(0, 1, value=0.6, label="end_line_y_ratio")
                            zone_sp = gr.Number(label="zone_distance_m", value=45)

                        def toggle_region(mode):
                            instant = mode == "瞬时测速"
                            return (
                                gr.update(visible=instant),
                                gr.update(visible=not instant),
                            )

                        mode_sp.change(
                            toggle_region,
                            mode_sp,
                            [mpp_sp, region_group],
                        )
                        btn_sp = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_sp = gr.Image(
                            label="实时帧", height=260, **STREAM_FRAME_IMAGE_KWARGS
                        )
                        vid_sp_out = gr.Video(label="结果视频", height=260)
                        st_sp = gr.Textbox(label="状态", interactive=False)
                        json_sp = gr.Textbox(label="接口返回 JSON", lines=10)

                btn_sp.click(
                    detect_car_speed,
                    [vid_sp_in, mode_sp, mpp_sp, start_sp, end_sp, zone_sp],
                    [frame_sp, vid_sp_out, st_sp, json_sp],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 6 车道 ----
            with gr.Tab("车道检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_ln_in = gr.Video(label="上传视频", height=320)
                        gr.Button("样例：video/car_line01.mp4", size="sm").click(
                            fn=lambda: load_sample_asset("video/car_line01.mp4"),
                            outputs=vid_ln_in,
                        )
                        btn_ln = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_ln = gr.Image(
                            label="实时帧", height=300, **STREAM_FRAME_IMAGE_KWARGS
                        )
                        vid_ln_out = gr.Video(label="结果视频", height=300)
                        st_ln = gr.Textbox(label="状态", interactive=False)
                        json_ln = gr.Textbox(label="接口返回 JSON", lines=8)

                btn_ln.click(
                    detect_lane_video,
                    [vid_ln_in],
                    [frame_ln, vid_ln_out, st_ln, json_ln],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 7 车位 ----
            with gr.Tab("车位检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_pk_in = gr.Video(label="上传视频", height=280)
                        pos_pk_in = gr.File(label="车位定位 JSON (position)", file_types=[".json"])
                        gr.Button("样例视频", size="sm").click(
                            fn=lambda: load_sample_asset("video/parking1.mp4"),
                            outputs=vid_pk_in,
                        )
                        gr.Button("样例定位文件", size="sm").click(
                            fn=lambda: load_sample_asset("video/parking1_position.json"),
                            outputs=pos_pk_in,
                        )
                        btn_pk = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_pk = gr.Image(
                            label="实时帧", height=260, **STREAM_FRAME_IMAGE_KWARGS
                        )
                        vid_pk_out = gr.Video(label="结果视频", height=260)
                        st_pk = gr.Textbox(label="状态", interactive=False)
                        json_pk = gr.Textbox(label="接口返回 JSON", lines=8)

                btn_pk.click(
                    detect_parking_video,
                    [vid_pk_in, pos_pk_in],
                    [frame_pk, vid_pk_out, st_pk, json_pk],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 8 车流量 ----
            with gr.Tab("车流量检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        vid_tf_in = gr.Video(label="上传视频", height=300)
                        gr.Button("样例：video/street_car_001.mp4", size="sm").click(
                            fn=lambda: load_sample_asset("video/street_car_001.mp4"),
                            outputs=vid_tf_in,
                        )
                        lanes_tf = gr.Slider(1, 6, value=1, step=1, label="车道数量")
                        fi_tf = gr.Slider(1, 30, value=3, step=1, label="frame_interval")
                        btn_tf = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        frame_tf = gr.Image(
                            label="实时帧", height=280, **STREAM_FRAME_IMAGE_KWARGS
                        )
                        vid_tf_out = gr.Video(label="结果视频", height=280)
                        st_tf = gr.Textbox(label="状态", interactive=False)
                        json_tf = gr.Textbox(label="接口返回 JSON", lines=8)

                btn_tf.click(
                    detect_traffic_flow,
                    [vid_tf_in, lanes_tf, fi_tf],
                    [frame_tf, vid_tf_out, st_tf, json_tf],
                    **STREAM_DETECT_KWARGS,
                )

            # ---- 9 交通标识 ----
            with gr.Tab("交通标识检测"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        img_sg_in = gr.Image(label="上传图片", type="filepath", height=360)
                        btn_sg = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        img_sg_out = gr.Image(label="检测结果", height=360)
                        st_sg = gr.Textbox(label="状态", interactive=False)
                        json_sg = gr.Textbox(label="接口返回 JSON", lines=14)

                btn_sg.click(
                    detect_traffic_sign,
                    [img_sg_in],
                    [img_sg_out, st_sg, json_sg],
                )

            # ---- 10 驾照 ----
            with gr.Tab("驾照识别"):
                with gr.Row(equal_height=False):
                    with gr.Column(**LEFT_PANEL_COL):
                        img_lc_in = gr.Image(label="上传图片", type="filepath", height=360)
                        gr.Button("加载样例：images/car_license01.jpg", size="sm").click(
                            fn=lambda: load_sample_asset("images/car_license01.jpg"),
                            outputs=img_lc_in,
                        )
                        btn_lc = gr.Button(
                            "开始检测", elem_classes=["btn-detect"], size="sm"
                        )
                    with gr.Column(**RIGHT_PANEL_COL):
                        img_lc_out = gr.Image(label="检测结果", height=300)
                        st_lc = gr.Textbox(label="状态", interactive=False)
                        table_lc = gr.HTML(empty_license_table_html(), label="识别结果")

                btn_lc.click(
                    detect_driver_license,
                    [img_lc_in],
                    [img_lc_out, st_lc, table_lc],
                )

    return demo


if __name__ == "__main__":
    demo = build_app()
    try:
        demo.queue(default_concurrency_limit=2).launch(
            server_name="127.0.0.1",
            server_port=7869,
            show_error=True,
            share=False,
            allowed_paths=get_launch_allowed_paths(),
        )
    except Exception as exc:
        msg = str(exc)
        if "startup-events" in msg and "502" in msg:
            raise SystemExit(
                "Gradio 无法访问本机 127.0.0.1（startup-events 502）。\n"
                "常见原因：系统或 Clash/V2Ray 等开启了 HTTP 代理。\n"
                "请任选其一：\n"
                "  1. 在代理软件中开启「绕过局域网/本地地址」；\n"
                "  2. 启动前执行：set NO_PROXY=localhost,127.0.0.1,::1\n"
                "  3. 临时关闭 HTTP_PROXY / HTTPS_PROXY 后再运行 python app.py"
            ) from exc
        raise
