# line_detect_service.py
"""车道线检测服务：封装传统 CV 检测、后处理与绘制。"""

from typing import List, Tuple

import cv2
import numpy as np


def _roi_mask(img_height: int, img_width: int) -> np.ndarray:
    """生成梯形 ROI 掩膜，只保留画面下半部分的车道区域。"""
    mask = np.zeros((img_height, img_width), dtype=np.uint8)
    pts = np.array([[
        (0, img_height),
        (int(img_width * 0.4), int(img_height * 0.6)),
        (int(img_width * 0.6), int(img_height * 0.6)),
        (img_width, img_height),
    ]], np.int32)
    cv2.fillPoly(mask, pts, 255)
    return mask


def _separate_lines(lines, img_width: int) -> Tuple[List, List]:
    """将 Hough 线段按斜率分为左车道线和右车道线。"""
    left_lines, right_lines = [], []
    if lines is None:
        return left_lines, right_lines
    mid = img_width / 2
    for line in lines:
        for x1, y1, x2, y2 in line:
            if x2 == x1:
                continue
            slope = (y2 - y1) / (x2 - x1)
            if abs(slope) < 0.3:
                continue
            x_mid = (x1 + x2) / 2
            if slope < 0 and x_mid < mid:
                left_lines.append((x1, y1, x2, y2))
            elif slope > 0 and x_mid > mid:
                right_lines.append((x1, y1, x2, y2))
    return left_lines, right_lines


def _avg_line(lines: List, img_height: int) -> Tuple[int, int, int, int] | None:
    """对一组线段求平均后外推到 ROI 上下边界。"""
    if not lines:
        return None
    xs, ys = [], []
    for x1, y1, x2, y2 in lines:
        xs.extend([x1, x2])
        ys.extend([y1, y2])
    if len(xs) < 2:
        return None
    poly = np.polyfit(ys, xs, 1)
    slope = poly[0]
    intercept = poly[1]
    y_bottom = img_height
    y_top = int(img_height * 0.6)
    x_bottom = int(slope * y_bottom + intercept)
    x_top = int(slope * y_top + intercept)
    return x_bottom, y_bottom, x_top, y_top


def detect_lines(frame) -> Tuple[np.ndarray, bool, int]:
    """对单帧图像执行车道线检测，返回标注图和检测结果。"""
    h, w = frame.shape[:2]
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blur, 50, 150)
    mask = _roi_mask(h, w)
    masked_edges = cv2.bitwise_and(edges, mask)
    lines = cv2.HoughLinesP(masked_edges, 1, np.pi / 180, 50,
                            minLineLength=80, maxLineGap=60)
    left_lines, right_lines = _separate_lines(lines, w)
    line_img = np.zeros_like(frame)
    line_count = 0
    left_pts = _avg_line(left_lines, h)
    right_pts = _avg_line(right_lines, h)
    if left_pts:
        cv2.line(line_img, (left_pts[0], left_pts[1]),
                 (left_pts[2], left_pts[3]), (0, 255, 0), 8)
        line_count += 1
    if right_pts:
        cv2.line(line_img, (right_pts[0], right_pts[1]),
                 (right_pts[2], right_pts[3]), (0, 255, 0), 8)
        line_count += 1
    result = cv2.addWeighted(frame, 0.8, line_img, 1, 0)
    return result, line_count > 0, line_count

