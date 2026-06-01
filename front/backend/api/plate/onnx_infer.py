import onnxruntime
import numpy as np
import cv2
import copy
import os
import argparse
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import time

from utils.myutils import (
    cv2AddChineseText,
    is_chinese_plate,
    normalize_plateno,
    query_chinese_plate,
)

PLATE_LABEL_FONT_SIZE = 24
PLATE_LABEL_FONT_FAMILY = "黑体"

_BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
_PLATE_FONT_FAMILY_FILES = {
    "黑体": [
        _BACKEND_DIR / "fonts" / "simhei.ttf",
        Path(r"C:\Windows\Fonts\simhei.ttf"),
        Path(r"C:\Windows\Fonts\STHEITI.TTF"),
    ],
    "宋体": [
        _BACKEND_DIR / "simsun.ttc",
        _BACKEND_DIR / "fonts" / "platech.ttf",
        Path(r"C:\Windows\Fonts\simsun.ttc"),
    ],
}


def _resolve_plate_label_font_path(
    family: str = PLATE_LABEL_FONT_FAMILY,
) -> str:
    """根据字体族名称解析字体文件路径。"""
    candidates = _PLATE_FONT_FAMILY_FILES.get(
        family, _PLATE_FONT_FAMILY_FILES["黑体"]
    )
    for path in candidates:
        if path.exists():
            return str(path)
    return str(_BACKEND_DIR / "fonts" / "platech.ttf")
plate_color_list=['黑色','蓝色','绿色','白色','黄色']
clors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0), (0, 255, 255)]
plateName=r"#京沪津渝冀晋蒙辽吉黑苏浙皖闽赣鲁豫鄂湘粤桂琼川贵云藏陕甘青宁新学警港澳挂使领民航危0123456789ABCDEFGHJKLMNPQRSTUVWXYZ险品"
mean_value,std_value=((0.588,0.193))#识别模型均值标准差

def load_models(detect_model_path="weights/plate_detect.onnx", rec_model_path="weights/plate_rec_color.onnx"):
    """
    加载车牌检测和识别的 ONNX 模型
    返回: (detect_session, rec_session)
    """
    providers = ['CPUExecutionProvider']
    detect_session = onnxruntime.InferenceSession(detect_model_path, providers=providers)
    rec_session = onnxruntime.InferenceSession(rec_model_path, providers=providers)
    return detect_session, rec_session


def decodePlate(preds):        #识别后处理
    pre=0
    newPreds=[]
    for i in range(len(preds)):
        if preds[i]!=0 and preds[i]!=pre:
            newPreds.append(preds[i])
        pre=preds[i]
    plate=""
    for i in newPreds:
        plate+=plateName[int(i)]
    return plate
    # return newPreds

def rec_pre_precessing(img,size=(48,168)): #识别前处理
    img =cv2.resize(img,(168,48))
    img = img.astype(np.float32)
    img = (img/255-mean_value)/std_value  #归一化 减均值 除标准差
    img = img.transpose(2,0,1)         #h,w,c 转为 c,h,w
    img = img.reshape(1,*img.shape)    #channel,height,width转为batch,channel,height,channel
    return img

def get_plate_result(img,session_rec): #识别后处理
    img =rec_pre_precessing(img)
    y_onnx_plate,y_onnx_color = session_rec.run([session_rec.get_outputs()[0].name,session_rec.get_outputs()[1].name], {session_rec.get_inputs()[0].name: img})
    index =np.argmax(y_onnx_plate,axis=-1)
    index_color = np.argmax(y_onnx_color)
    plate_color = plate_color_list[index_color]
    # print(y_onnx[0])
    plate_no = normalize_plateno(decodePlate(index[0]))
    return plate_no, plate_color


def allFilePath(rootPath,allFIleList):  #遍历文件
    fileList = os.listdir(rootPath)
    for temp in fileList:
        if os.path.isfile(os.path.join(rootPath,temp)):
            allFIleList.append(os.path.join(rootPath,temp))
        else:
            allFilePath(os.path.join(rootPath,temp),allFIleList)

def get_split_merge(img):  #双层车牌进行分割后识别
    h,w,c = img.shape
    img_upper = img[0:int(5/12*h),:]
    img_lower = img[int(1/3*h):,:]
    img_upper = cv2.resize(img_upper,(img_lower.shape[1],img_lower.shape[0]))
    new_img = np.hstack((img_upper,img_lower))
    return new_img


def order_points(pts):     # 关键点排列 按照（左上，右上，右下，左下）的顺序排列
    rect = np.zeros((4, 2), dtype = "float32")
    s = pts.sum(axis = 1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis = 1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image, pts):  #透视变换得到矫正后的图像，方便识别
    rect = order_points(pts)
    (tl, tr, br, bl) = rect
    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))
    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))
    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype = "float32")
    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
 
    # return the warped image
    return warped

def my_letter_box(img,size=(640,640)):  #
    h,w,c = img.shape
    r = min(size[0]/h,size[1]/w)
    new_h,new_w = int(h*r),int(w*r)
    top = int((size[0]-new_h)/2)
    left = int((size[1]-new_w)/2)
    
    bottom = size[0]-new_h-top
    right = size[1]-new_w-left
    img_resize = cv2.resize(img,(new_w,new_h))
    img = cv2.copyMakeBorder(img_resize,top,bottom,left,right,borderType=cv2.BORDER_CONSTANT,value=(114,114,114))
    return img,r,left,top

def xywh2xyxy(boxes):   #xywh坐标变为 左上 ，右下坐标 x1,y1  x2,y2
    xywh =copy.deepcopy(boxes)
    xywh[:,0]=boxes[:,0]-boxes[:,2]/2
    xywh[:,1]=boxes[:,1]-boxes[:,3]/2
    xywh[:,2]=boxes[:,0]+boxes[:,2]/2
    xywh[:,3]=boxes[:,1]+boxes[:,3]/2
    return xywh
 
def my_nms(boxes,iou_thresh):         #nms
    index = np.argsort(boxes[:,4])[::-1]
    keep = []
    while index.size >0:
        i = index[0]
        keep.append(i)
        x1=np.maximum(boxes[i,0],boxes[index[1:],0])
        y1=np.maximum(boxes[i,1],boxes[index[1:],1])
        x2=np.minimum(boxes[i,2],boxes[index[1:],2])
        y2=np.minimum(boxes[i,3],boxes[index[1:],3])
        
        w = np.maximum(0,x2-x1)
        h = np.maximum(0,y2-y1)

        inter_area = w*h
        union_area = (boxes[i,2]-boxes[i,0])*(boxes[i,3]-boxes[i,1])+(boxes[index[1:],2]-boxes[index[1:],0])*(boxes[index[1:],3]-boxes[index[1:],1])
        iou = inter_area/(union_area-inter_area)
        idx = np.where(iou<=iou_thresh)[0]
        index = index[idx+1]
    return keep

def restore_box(boxes,r,left,top):  #返回原图上面的坐标
    boxes[:,[0,2,5,7,9,11]]-=left
    boxes[:,[1,3,6,8,10,12]]-=top

    boxes[:,[0,2,5,7,9,11]]/=r
    boxes[:,[1,3,6,8,10,12]]/=r
    return boxes

def detect_pre_precessing(img,img_size):  #检测前处理
    img,r,left,top=my_letter_box(img,img_size)
    # cv2.imwrite("1.jpg",img)
    img =img[:,:,::-1].transpose(2,0,1).copy().astype(np.float32)
    img=img/255
    img=img.reshape(1,*img.shape)
    return img,r,left,top

def post_precessing(dets,r,left,top,conf_thresh=0.3,iou_thresh=0.5):#检测后处理
    choice = dets[:,:,4]>conf_thresh
    dets=dets[choice]
    dets[:,13:15]*=dets[:,4:5]
    box = dets[:,:4]
    boxes = xywh2xyxy(box)
    score= np.max(dets[:,13:15],axis=-1,keepdims=True)
    index = np.argmax(dets[:,13:15],axis=-1).reshape(-1,1)
    output = np.concatenate((boxes,score,dets[:,5:13],index),axis=1) 
    reserve_=my_nms(output,iou_thresh) 
    output=output[reserve_] 
    output = restore_box(output,r,left,top)
    return output

def rec_plate(outputs,img0,session_rec):  #识别车牌
    dict_list=[]
    for output in outputs:
        result_dict={}
        rect=output[:4].tolist()
        land_marks = output[5:13].reshape(4,2)
        roi_img = four_point_transform(img0,land_marks)
        label = int(output[-1])
        score = output[4]
        if label==1:  #代表是双层车牌
            roi_img = get_split_merge(roi_img)
        plate_no,plate_color = get_plate_result(roi_img,session_rec)
        result_dict['rect']=rect
        result_dict['landmarks']=land_marks.tolist()
        result_dict['plate_no']=plate_no
        result_dict['roi_height']=roi_img.shape[0]
        result_dict['plate_color']=plate_color
        dict_list.append(result_dict)
    return dict_list

def _draw_plate_label_on_box(orgimg, text, box_x1, box_y1):
    """黑底白字标签，紧贴检测框上方；固定字号与字体族。"""
    font_size = PLATE_LABEL_FONT_SIZE
    font_path = _resolve_plate_label_font_path(PLATE_LABEL_FONT_FAMILY)
    label_pad = 4
    gap = 0

    text_x = int(box_x1) + label_pad
    pil = Image.fromarray(cv2.cvtColor(orgimg, cv2.COLOR_BGR2RGB))
    draw = ImageDraw.Draw(pil)

    font = ImageFont.truetype(font_path, font_size, encoding="utf-8")
    probe_bbox = draw.textbbox((text_x, 0), text, font=font)
    text_h = probe_bbox[3] - probe_bbox[1]
    text_y = max(0, int(box_y1) - text_h - gap)

    bbox = draw.textbbox((text_x, text_y), text, font=font)
    draw.rectangle(
        [
            bbox[0] - label_pad,
            bbox[1] - label_pad,
            bbox[2] + label_pad,
            bbox[3] + label_pad,
        ],
        fill=(0, 0, 0),
    )
    orgimg = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
    return cv2AddChineseText(
        orgimg, text, (text_x, text_y), (255, 255, 255), font_size, font_path=font_path
    )


def _plate_label_text(plate_no: str, city_cache: dict, include_city: bool = True) -> str:
    if not include_city:
        return plate_no
    if plate_no not in city_cache:
        try:
            city_cache[plate_no] = query_chinese_plate(plate_no)
        except Exception:
            city_cache[plate_no] = "未知"
    city = city_cache[plate_no] or "未知"
    return f"{plate_no} {city}"


def draw_result(orgimg, dict_list, include_city: bool = True):
    result_str = ""
    city_cache = {}
    for item in dict_list:
        x1, y1, x2, y2 = item["rect"]
        w, h = x2 - x1, y2 - y1
        padding_w = 0.05 * w
        padding_h = 0.11 * h
        bx1 = max(0, int(x1 - padding_w))
        by1 = max(0, int(y1 - padding_h))
        bx2 = min(orgimg.shape[1], int(x2 + padding_w))
        by2 = min(orgimg.shape[0], int(y2 + padding_h))

        plate_no = item["plate_no"]
        if not is_chinese_plate(plate_no):
            continue

        landmarks = item["landmarks"]
        result_str += plate_no + " "
        for i in range(4):
            cv2.circle(orgimg, (int(landmarks[i][0]), int(landmarks[i][1])), 5, clors[i], -1)
        cv2.rectangle(orgimg, (bx1, by1), (bx2, by2), (0, 0, 0), 2)
        label_text = _plate_label_text(plate_no, city_cache, include_city)
        orgimg = _draw_plate_label_on_box(orgimg, label_text, bx1, by1)
    print(result_str)
    return orgimg

if __name__ == "__main__":
    begin = time.time()
    parser = argparse.ArgumentParser()
    parser.add_argument('--detect_model',type=str, default=r'weights/plate_detect.onnx', help='model.pt path(s)')  #检测模型
    parser.add_argument('--rec_model', type=str, default='weights/plate_rec_color.onnx', help='model.pt path(s)')#识别模型
    parser.add_argument('--image_path', type=str, default='imgs', help='source') 
    parser.add_argument('--img_size', type=int, default=640, help='inference size (pixels)')
    parser.add_argument('--output', type=str, default='result1', help='source') 
    opt = parser.parse_args()
    file_list = []
    allFilePath(opt.image_path,file_list)
    providers =  ['CPUExecutionProvider']

    img_size = (opt.img_size,opt.img_size)
    session_detect = onnxruntime.InferenceSession(opt.detect_model, providers=providers )
    session_rec = onnxruntime.InferenceSession(opt.rec_model, providers=providers )
    if not os.path.exists(opt.output):
        os.mkdir(opt.output)
    save_path = opt.output
    count = 0
    for pic_ in file_list:
        count+=1
        print(count,pic_,end=" ")
        img=cv2.imread(pic_)
        img0 = copy.deepcopy(img)
        img,r,left,top = detect_pre_precessing(img,img_size) #检测前处理
        # print(img.shape)
        y_onnx = session_detect.run([session_detect.get_outputs()[0].name], {session_detect.get_inputs()[0].name: img})[0]
        outputs = post_precessing(y_onnx,r,left,top) #检测后处理
        result_list=rec_plate(outputs,img0,session_rec)
        ori_img = draw_result(img0,result_list)
        img_name = os.path.basename(pic_)
        save_img_path = os.path.join(save_path,img_name)
        cv2.imwrite(save_img_path,ori_img)
    print(f"总共耗时{time.time()-begin} s")
    

        