from shutil import copy
import uuid
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import cv2
import numpy as np
import re
import json
import requests

_BACKEND_DIR = Path(__file__).resolve().parent.parent


def resolve_chinese_font_path() -> str:
    """解析中文字体路径，优先 simsun，其次 platech，最后系统字体。"""
    candidates = [
        _BACKEND_DIR / "simsun.ttc",
        _BACKEND_DIR / "fonts" / "platech.ttf",
        Path(r"C:\Windows\Fonts\simsun.ttc"),
        Path("simsun.ttc"),
    ]
    for path in candidates:
        if path.exists():
            return str(path)
    return str(_BACKEND_DIR / "fonts" / "platech.ttf")

pattern_str = "([京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼]" \
              "{1}(([A-HJ-Z]{1}[A-HJ-NP-Z0-9]{5})|([A-HJ-Z]{1}(([DF]{1}[A-HJ-NP-Z0-9]{1}[0-9]{4})|([0-9]{5}[DF]" \
              "{1})))|([A-HJ-Z]{1}[A-D0-9]{1}[0-9]{3}警)))|([0-9]{6}使)|((([沪粤川云桂鄂陕蒙藏黑辽渝]{1}A)|鲁B|闽D|蒙E|蒙H)" \
              "[0-9]{4}领)|(WJ[京津沪渝冀豫云辽黑湘皖鲁新苏浙赣鄂桂甘晋蒙陕吉闽贵粤青藏川宁琼·•]{1}[0-9]{4}[TDSHBXJ0-9]{1})" \
              "|([VKHBSLJNGCE]{1}[A-DJ-PR-TVY]{1}[0-9]{5})"


# 校验车牌
def is_chinese_plate(plateno):
    if re.findall(pattern_str, plateno):
        return True
    else:
        return False


# 文件拷贝命令
def file_copy(src, dest):
    copy(src, dest)


# 生成UUID的函数
def generate_uuid():
    return str(uuid.uuid4())


# opencv实现视频里面写入中文字符串的函数
def cv2AddChineseText(img, text, position, textColor, textSize, font_path=None):
    if isinstance(img, np.ndarray):
        img = Image.fromarray(cv2.cvtColor(img, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(img)
    fontStyle = ImageFont.truetype(
        font_path or resolve_chinese_font_path(), textSize, encoding="utf-8"
    )
    draw.text(position, text, textColor, font=fontStyle)
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


# 把json字符串写入到json文件中。
"""
def writ2json(data, path):
    with open(path + '/result.json', 'w', encoding='utf-8') as file:
        # 将字符串写入文件
        file.write(data)
"""


def writ2json(data, path):
    # 确保路径存在斜杠结尾
    if not path.endswith('/'):
        path += '/'

    # 检查输入数据是字符串还是Python对象
    if isinstance(data, str):
        # 如果是字符串，解析为Python对象
        parsed_data = json.loads(data)
    else:
        # 如果是Python对象（如字典/列表），直接使用
        parsed_data = data

    # 将格式化后的JSON写入文件
    with open(path + 'result.json', 'w', encoding='utf-8') as file:
        json.dump(parsed_data, file, indent=4, ensure_ascii=False)


# 读取json文件返回json字符串
def read2json(path):
    with open(path, 'r', encoding='utf-8') as file:
        # 读取文件内容
        data = file.read()
        result_json = json.loads(data)
    return result_json


PLATE_CITY_API = "https://www.simoniu.com/commons/chinaplate/"


def normalize_plateno(plateno: str) -> str:
    """清洗识别结果中的空白、分隔符等，避免归属地查询请求失败。"""
    if not plateno:
        return plateno
    p = plateno.strip()
    p = p.replace("·", "").replace("•", "").replace(" ", "")
    p = re.sub(r"[\r\n\t\0]", "", p)
    return p


# 查询车牌归属地
def query_chinese_plate(plateno):
    from urllib.parse import quote

    plateno = normalize_plateno(plateno)
    if not plateno:
        return "未知"

    url = PLATE_CITY_API + quote(plateno, safe="")
    last_err = None
    for _ in range(2):
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            json_obj = json.loads(response.content.decode("utf-8"))
            data = json_obj.get("data")
            if isinstance(data, str):
                return data.strip() or "未知"
            if data is not None:
                return str(data)
            raise KeyError("missing data field")
        except Exception as e:
            last_err = e

    print(f"query_chinese_plate failed: plateno={plateno!r}, err={last_err}")
    return "未知"


def traffic_ratio_cal(current_num, num, ability=1000):
    level = current_num / (num * ability)
    result = "拥堵" if level > 1 else "畅通"
    return result


if __name__ == '__main__':
    str = "陕AN1M77"
    print(is_chinese_plate(str))  # False
