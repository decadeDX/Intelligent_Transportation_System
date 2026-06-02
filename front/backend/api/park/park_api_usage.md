# 车位检测接口调用说明

## 图片检测

```http
POST /parkDetected
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 待检测图片 |
| `parking_spots_file` | file | 否 | 车位坐标 JSON 文件 |

未上传 `parking_spots_file` 时，接口自动使用原有网格化车位估算逻辑。

## 视频流式检测

```http
POST /parkVideoDetectedWithFrame
Content-Type: multipart/form-data
```

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| `file` | file | 是 | 待检测视频 |
| `parking_spots_file` | file | 否 | 车位坐标 JSON 文件 |
| `frame_interval` | int | 否 | 帧间隔参数，默认 `5` |

## 车位 JSON 示例

参考同目录下的 `parking_spots_example.json`。

```json
{
  "parking_lot_info": {
    "lot_id": "garage_01",
    "lot_name": "一号地下车库"
  },
  "parking_spots": [
    {
      "spot_id": "A01",
      "spot_name": "A区-01",
      "coordinates": [[120, 420], [300, 410], [310, 620], [130, 630]],
      "attributes": {
        "type": "standard",
        "status": "normal"
      }
    }
  ]
}
```

说明：

- `coordinates` 推荐使用四点坐标 `[[左上x,左上y], [右上x,右上y], [右下x,右下y], [左下x,左下y]]`，用于倾斜车位 IoU。
- 旧格式 `[x1, y1, x2, y2]` 仍兼容，会自动转换为矩形车位。
- `status` 为 `normal` 的车位参与检测。
- `status` 为 `repair` 或其他值的车位会被跳过。
- 坐标越界、坐标无效、字段格式错误的单个车位会被过滤。

## 响应增强字段

| 字段 | 说明 |
| --- | --- |
| `parking_lot_info` | 上传 JSON 中的车库信息；未上传时为空对象 |
| `spot_regions` | 每个车位的坐标、占用状态，以及 `spot_id`、`spot_name` |
| `occupied_spots` | 占用车位数 |
| `free_spots` | 空闲车位数 |
| `total_spots` | 参与检测的车位总数 |

## 错误码

| code | 场景 |
| --- | --- |
| `200` | 检测成功 |
| `400` | 上传视频无法打开，或车位 JSON 根格式错误 |
| `500` | 图像读取失败、模型未初始化或其他运行时错误 |
