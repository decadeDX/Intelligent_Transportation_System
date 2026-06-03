# license_detected.py

"""驾驶证 / 证件图片 OCR 识别核心逻辑（PP-OCRv5 ONNX + onnxruntime）。"""



from __future__ import annotations



import os

import re

import shutil

import threading

from pathlib import Path

from typing import Any, Dict, List, Sequence, Tuple



import numpy as np



os.environ.setdefault("PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK", "True")



_BACKEND_DIR = Path(__file__).resolve().parents[2]

DEFAULT_OCR_MODELS_DIR = _BACKEND_DIR / "models"



OCR_DET_MODEL_NAME = "PP-OCRv5_server_det"

OCR_REC_MODEL_NAME = "PP-OCRv5_server_rec"

OCR_DET_ONNX_DIR_NAME = "PP-OCRv5_server_det_onnx"

OCR_REC_ONNX_DIR_NAME = "PP-OCRv5_server_rec_onnx"

OCR_INFERENCE_ENGINE = "onnxruntime"

_ocr_engine = None

_model_inference_lock = threading.Lock()





def resolve_ocr_onnx_model_dirs(models_dir: Path) -> tuple[Path, Path]:

    """

    解析本地 ONNX OCR 模型目录（检测 + 识别）。



    期望目录结构：

      {models_dir}/PP-OCRv5_server_det_onnx/inference.onnx

      {models_dir}/PP-OCRv5_server_rec_onnx/inference.onnx

    """

    det_dir = models_dir / OCR_DET_ONNX_DIR_NAME

    rec_dir = models_dir / OCR_REC_ONNX_DIR_NAME

    missing = []

    for name, path in (

        (OCR_DET_ONNX_DIR_NAME, det_dir),

        (OCR_REC_ONNX_DIR_NAME, rec_dir),

    ):

        if not (path / "inference.onnx").exists():

            missing.append(f"{name} -> {path}")

    if missing:

        raise FileNotFoundError(

            "未找到本地 ONNX OCR 模型，请执行 python paddleocr_onnx.py --method download "

            f"或将 *_onnx 目录放到 {models_dir}。缺失：{'; '.join(missing)}"

        )

    return det_dir, rec_dir





def _build_ocr_pipeline_config(det_dir: Path, rec_dir: Path) -> dict:
    from paddlex.inference import load_pipeline_config
    from paddleocr._pipelines.base import _merge_dicts
    from paddleocr._pipelines.utils import create_config_from_structure

    overrides = create_config_from_structure(

        {

            "SubModules.TextDetection.model_name": OCR_DET_MODEL_NAME,

            "SubModules.TextDetection.model_dir": str(det_dir),

            "SubModules.TextRecognition.model_name": OCR_REC_MODEL_NAME,

            "SubModules.TextRecognition.model_dir": str(rec_dir),

            "SubPipelines.DocPreprocessor.use_doc_orientation_classify": False,

            "SubPipelines.DocPreprocessor.use_doc_unwarping": False,

            "use_doc_preprocessor": False,

            "use_textline_orientation": False,

        }

    )

    return _merge_dicts(load_pipeline_config("OCR"), overrides)





def create_ocr_engine(models_dir: Path | None = None):

    """创建 PP-OCRv5 ONNX 推理流水线（CPU，onnxruntime）。"""

    from paddlex import create_pipeline

    root = models_dir or DEFAULT_OCR_MODELS_DIR

    det_dir, rec_dir = resolve_ocr_onnx_model_dirs(root)

    config = _build_ocr_pipeline_config(det_dir, rec_dir)

    return create_pipeline(

        config=config,

        device="cpu",

        engine=OCR_INFERENCE_ENGINE,

    )


def initialize_license_ocr(ocr_engine=None, models_dir: Path | None = None):
    """初始化驾驶证 OCR 模型，由启动流程统一调用。"""
    global _ocr_engine

    if ocr_engine is None:
        ocr_engine = create_ocr_engine(models_dir)
    _ocr_engine = ocr_engine


def _get_ocr_engine():
    if _ocr_engine is None:
        raise RuntimeError("驾驶证 OCR 模型未初始化，请先调用 initialize_license_ocr")
    return _ocr_engine





def _to_list(value) -> List:

    if value is None:

        return []

    if isinstance(value, np.ndarray):

        return value.tolist()

    return list(value)





def _bbox_from_item(box_item, index: int, boxes: List) -> List[int]:

    """从 rec_boxes（xyxy）或 rec_polys（四点）解析 bbox。"""

    if index < len(boxes):

        arr = np.asarray(boxes[index])

        if arr.size >= 4:

            if arr.ndim == 1 and arr.size == 4:

                x1, y1, x2, y2 = arr.tolist()

                return [int(x1), int(y1), int(x2), int(y2)]

            if arr.ndim == 2:

                xs = arr[:, 0]

                ys = arr[:, 1]

                return [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]

    return [0, 0, 0, 0]





# 驾驶证版面常见字段标签（含 OCR 误识变体）

_LABEL_NAME = ("姓名",)

_LABEL_GENDER = ("性别",)

_LABEL_IDNO = ("证号", "身份证号码", "身份号码")

_LABEL_ADDRESS = ("住址",)

_LABEL_TYPE = ("准驾车型", "准驾", "车型")

_LABEL_NATIONALITY = ("国籍",)

_LABEL_NATION = ("民族",)

_LABEL_FIRST_ISSUE_DATE = ("初次领证日期", "初次领证", "初领日期")

_LABEL_BIRTH_DATE = ("出生", "出生日期")



# 准驾车型：A1/A2/A3/B1/B2/C1/C2/C3/D/E/F 等

_VEHICLE_CLASS_RE = re.compile(r"^[A-Z]\d{0,2}$")

_IDNO_RE = re.compile(r"(?<!\d)(\d{17}[\dXx]|\d{15})(?!\d)")

_CHINESE_NAME_RE = re.compile(r"^[\u4e00-\u9fa5·]{2,8}$")

_SKIP_LINE_RE = re.compile(
    r"(驾驶证|Driving|License|Republic|China|CHN|Nationality|"
    r"Date|Issue|Valid|Period|Birth|Buth|First|Address|Name|Class|"
    r"中华人民共和国|交通|警察|支队)",
    re.I,
)

# 住址行合并：bbox 底边到下一框顶边间距超过该值视为版面另起一行
_ADDRESS_LINE_GAP = 42
# 常见住址结尾（组/号/户等），命中后不再吸收换行后的无关文本
_ADDRESS_SUFFIX_TERMINATORS = re.compile(
    r"(组|号|户|室|栋|单元|村|楼|层|巷|弄|路|街|道|镇|乡|坊|委)$"
)
_PROVINCE_RE = re.compile(r"[\u4e00-\u9fa5]{2,8}省")





def _plain_texts(text_list: Sequence[Dict[str, Any]]) -> List[str]:

    return [str(item.get("text", "")).strip() for item in text_list if str(item.get("text", "")).strip()]





def _contains_label(text: str, labels: Tuple[str, ...]) -> bool:

    return any(label in text for label in labels)





def _value_after_label(text: str, label: str) -> str:

    """从「标签+值」同一行中截取值，如 姓名邓艳波 → 邓艳波。"""

    if label not in text:

        return ""

    rest = text.split(label, 1)[-1].strip()

    rest = re.sub(r"^[：:\s]+", "", rest)

    if not rest or _contains_label(rest, _LABEL_NAME + _LABEL_GENDER + _LABEL_ADDRESS + _LABEL_TYPE):

        return ""

    return rest





def _extract_idno(texts: List[str]) -> str:

    for text in texts:

        inline = _value_after_label(text, "证号")

        if inline and _IDNO_RE.fullmatch(inline.replace(" ", "")):

            return inline.replace(" ", "").upper()

        match = _IDNO_RE.search(text.replace(" ", ""))

        if match:

            return match.group(1).upper()

    return ""





def _extract_labeled_value(texts: List[str], labels: Tuple[str, ...], lookahead: int = 3) -> str:
    for i, text in enumerate(texts):
        for label in labels:
            inline = _value_after_label(text, label)
            if inline:
                return inline
        if _contains_label(text, labels):
            for nxt in texts[i + 1 : i + 1 + lookahead]:
                if nxt and not _SKIP_LINE_RE.fullmatch(nxt):
                    return nxt
    return ""


def _normalize_date(text: str) -> str:
    compact = re.sub(r"\s+", "", text)
    match = re.search(r"(\d{4})[年./-]?(\d{1,2})[月./-]?(\d{1,2})日?", compact)
    if not match:
        return ""
    year, month, day = match.groups()
    return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"


def _extract_date_field(texts: List[str], labels: Tuple[str, ...]) -> str:
    for i, text in enumerate(texts):
        if _contains_label(text, labels):
            for label in labels:
                date = _normalize_date(_value_after_label(text, label))
                if date:
                    return date
            for nxt in texts[i + 1 : i + 4]:
                date = _normalize_date(nxt)
                if date:
                    return date
    return ""


def _normalize_nationality_value(text: str, allow_plain_chinese: bool = False) -> str:
    compact = re.sub(r"\s+", "", text)
    upper = compact.upper()
    if "中国" in compact or "CHN" in upper or upper == "CN":
        return "中国"

    if not allow_plain_chinese:
        return ""

    cleaned = re.sub(r"(国籍|Nationality|[:：/A-Za-z]+)", "", compact, flags=re.I)
    match = re.search(r"[\u4e00-\u9fa5]{2,8}", cleaned)
    if match and match.group(0) not in ("姓名", "性别", "住址", "证号", "民族"):
        return match.group(0)
    return ""


def _extract_nationality(texts: List[str]) -> str:
    for i, text in enumerate(texts):
        if not _contains_label(text, _LABEL_NATIONALITY):
            continue

        for label in _LABEL_NATIONALITY:
            value = _normalize_nationality_value(_value_after_label(text, label), True)
            if value:
                return value

        for nxt in texts[i + 1 : i + 7]:
            value = _normalize_nationality_value(nxt)
            if value:
                return value

    for text in texts:
        value = _normalize_nationality_value(text)
        if value:
            return value
    return ""


def _extract_nation(texts: List[str]) -> str:
    value = _extract_labeled_value(texts, _LABEL_NATION)
    if value:
        cleaned = re.sub(r"(民族|族|[:：\s])", "", value)
        match = re.search(r"[\u4e00-\u9fa5]{1,6}", cleaned)
        if match:
            return match.group(0)
    for text in texts:
        match = re.search(r"([\u4e00-\u9fa5]{1,6})族", text)
        if match:
            return match.group(1)
    return ""


def _extract_vehicle_type(texts: List[str]) -> str:

    for i, text in enumerate(texts):

        if _contains_label(text, _LABEL_TYPE):

            inline = ""

            for label in _LABEL_TYPE:

                inline = _value_after_label(text, label) or inline

            if inline and _VEHICLE_CLASS_RE.match(inline):

                return inline

            for nxt in texts[i + 1 : i + 4]:

                if _VEHICLE_CLASS_RE.match(nxt):

                    return nxt

    for text in texts:

        if _VEHICLE_CLASS_RE.match(text):

            return text

    return ""





def _extract_gender(texts: List[str]) -> str:

    for i, text in enumerate(texts):

        if "性别" in text:

            inline = _value_after_label(text, "性别")

            gender_match = re.search(r"[男女]", inline)

            if gender_match:

                return gender_match.group(0)

            for nxt in texts[i + 1 : i + 4]:

                if nxt in ("男", "女"):

                    return nxt

                gender_match = re.search(r"[男女]", nxt)

                if gender_match and "民族" not in nxt[:3]:

                    return gender_match.group(0)

    for text in texts:

        if text in ("男", "女"):

            return text

    return ""





def _extract_name(texts: List[str]) -> str:

    for i, text in enumerate(texts):

        if "姓名" in text:

            inline = _value_after_label(text, "姓名")

            if inline:

                name = re.sub(r"性别.*$", "", inline).strip()

                name_match = re.search(r"[\u4e00-\u9fa5·]{2,8}", name)

                if name_match:

                    return name_match.group(0)

            for nxt in texts[i + 1 : i + 3]:

                if _CHINESE_NAME_RE.match(nxt):

                    return nxt

                name_match = re.search(r"[\u4e00-\u9fa5·]{2,4}", nxt)

                if name_match and nxt not in ("男", "女"):

                    return name_match.group(0)

    return ""





def _bbox_y_range(bbox: Sequence[int]) -> Tuple[int, int]:
    return int(bbox[1]), int(bbox[3])


def _address_segment_blocked(text: str) -> bool:
    if _contains_label(text, _LABEL_NAME + _LABEL_GENDER + _LABEL_TYPE):
        return True
    if _contains_label(text, ("出生", "初次", "有效", "国籍", "证号", "公民身份")):
        return True
    if _SKIP_LINE_RE.fullmatch(text):
        return True
    if re.match(r"^\d{4}-\d{2}-\d{2}", text) or re.match(r"^\d{4}年", text):
        return True
    if _VEHICLE_CLASS_RE.match(text):
        return True
    if re.fullmatch(r"\d{5,}", text.replace(" ", "")):
        return True
    return False


def _address_segment_skip(text: str) -> bool:
    """英文标签等：跳过但不结束住址拼接。"""
    return text.strip().lower() == "address"


def _address_looks_complete(address: str) -> bool:
    return bool(_ADDRESS_SUFFIX_TERMINATORS.search(address.strip()))


def _extra_province_segment(current: str, segment: str) -> bool:
    """当前住址已含省，下一段又以另一省份开头 → 多为下一行字段（如出生地）。"""
    cur_provinces = _PROVINCE_RE.findall(current)
    new_provinces = _PROVINCE_RE.findall(segment)
    if not cur_provinces or not new_provinces:
        return False
    return new_provinces[0] not in cur_provinces


def _is_address_continuation(prev_y_max: int, bbox: Sequence[int]) -> bool:
    y_min, _ = _bbox_y_range(bbox)
    return y_min <= prev_y_max + _ADDRESS_LINE_GAP


def _extract_address(text_list: Sequence[Dict[str, Any]]) -> str:
    items = [
        item
        for item in text_list
        if str(item.get("text", "")).strip() and item.get("bbox")
    ]
    for i, item in enumerate(items):
        text = str(item["text"]).strip()
        if not _contains_label(text, _LABEL_ADDRESS):
            continue

        inline = ""
        for label in _LABEL_ADDRESS:
            inline = _value_after_label(text, label) or inline
        parts = [inline] if inline else []
        y_max = _bbox_y_range(item["bbox"])[1]

        for nxt_item in items[i + 1 :]:
            nxt = str(nxt_item["text"]).strip()
            bbox = nxt_item["bbox"]
            if _address_segment_skip(nxt):
                continue
            if _address_segment_blocked(nxt):
                break
            if not _is_address_continuation(y_max, bbox):
                break

            current = "".join(parts)
            if current and _extra_province_segment(current, nxt):
                break

            parts.append(nxt)
            y_max = max(y_max, _bbox_y_range(bbox)[1])

            if _address_looks_complete("".join(parts)):
                break

        address = "".join(parts)
        if len(address) >= 6:
            return address
    return ""





def parse_license_fields(text_list: Sequence[Dict[str, Any]]) -> Dict[str, str]:

    """

    从 OCR 文本列表解析驾驶证结构化字段。



    返回: name, gender, idno, address, type（识别不到则为空字符串）

    """

    texts = _plain_texts(text_list)

    return {

        "name": _extract_name(texts),

        "gender": _extract_gender(texts),

        "idno": _extract_idno(texts),

        "address": _extract_address(text_list),

        "type": _extract_vehicle_type(texts),

        "nationality": _extract_nationality(texts),

        "nation": _extract_nation(texts),

        "first_issue_date": _extract_date_field(texts, _LABEL_FIRST_ISSUE_DATE),

    }


def parse_id_card_fields(text_list: Sequence[Dict[str, Any]]) -> Dict[str, str]:
    """从 OCR 文本列表解析身份证结构化字段。"""
    texts = _plain_texts(text_list)
    return {
        "name": _extract_name(texts),
        "gender": _extract_gender(texts),
        "nation": _extract_nation(texts),
        "birth_date": _extract_date_field(texts, _LABEL_BIRTH_DATE),
        "address": _extract_address(text_list),
        "idno": _extract_idno(texts),
    }





def build_text_list(ocr_data: Dict[str, Any]) -> List[Dict[str, Any]]:

    """从 OCR 结果字典构建文字列表。"""

    texts = ocr_data.get("rec_texts") or []

    scores = _to_list(ocr_data.get("rec_scores"))

    boxes = _to_list(ocr_data.get("rec_boxes"))

    polys = _to_list(ocr_data.get("rec_polys"))

    box_source = boxes if boxes else polys



    text_list: List[Dict[str, Any]] = []

    for i, text in enumerate(texts):

        if text is None or str(text).strip() == "":

            continue

        conf = float(scores[i]) if i < len(scores) else 0.0

        text_list.append(

            {

                "text": str(text),

                "confidence": round(conf, 4),

                "bbox": _bbox_from_item(None, i, box_source),

            }

        )

    return text_list





def _relocate_annotated_image(detected_dir: Path, file_path: Path) -> Path:

    """将 OCR 生成的标注图重命名为 license_{原文件名}。"""

    stem = file_path.stem

    generated = list(detected_dir.glob(f"{stem}_ocr_res_img.*"))

    output_path = detected_dir / f"license_{file_path.name}"

    if generated:

        src = generated[0]

        if output_path.exists():

            output_path.unlink()

        shutil.move(str(src), str(output_path))

    elif not output_path.exists():

        raise FileNotFoundError("检测结果图片未生成")

    return output_path





def _ocr_result_payload(ocr_result) -> Dict[str, Any]:

    ocr_data = ocr_result.json if hasattr(ocr_result, "json") else {}

    if isinstance(ocr_data, dict) and "res" in ocr_data:

        ocr_data = ocr_data["res"]

    return ocr_data





def run_image_detection(file_path: Path, detected_dir: Path, recognition_type: str = "driver_license") -> dict:

    """执行图片 OCR（ONNX），返回 API data 字段内容。"""

    if not file_path.exists():

        raise FileNotFoundError(f"图片不存在: {file_path}")



    with _model_inference_lock:
        results = list(_get_ocr_engine().predict(str(file_path)))

    if not results:

        raise ValueError("OCR 未返回识别结果")



    ocr_result = results[0]

    ocr_data = _ocr_result_payload(ocr_result)



    detected_dir.mkdir(parents=True, exist_ok=True)

    ocr_result.save_to_img(str(detected_dir))

    output_path = _relocate_annotated_image(detected_dir, file_path)



    text_list = build_text_list(ocr_data)

    full_text = "\n".join(item["text"] for item in text_list)

    card_type = "id_card" if recognition_type == "id_card" else "driver_license"
    structured_fields = (
        parse_id_card_fields(text_list)
        if card_type == "id_card"
        else parse_license_fields(text_list)
    )



    return {

        "card_type": card_type,

        "structured_fields": structured_fields,

        "name": structured_fields.get("name", ""),

        "gender": structured_fields.get("gender", ""),

        "idno": structured_fields.get("idno", ""),

        "address": structured_fields.get("address", ""),

        "type": structured_fields.get("type", ""),

        "nationality": structured_fields.get("nationality", ""),

        "nation": structured_fields.get("nation", ""),

        "first_issue_date": structured_fields.get("first_issue_date", ""),

        "birth_date": structured_fields.get("birth_date", ""),

        "text_number": len(text_list),

        "text_list": text_list,

        "full_text": full_text,

        "url": str(output_path).replace("\\", "/"),

        "result_dir": str(detected_dir).replace("\\", "/"),

    }


