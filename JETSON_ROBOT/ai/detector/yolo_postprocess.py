"""[2026-07-18] YOLOv8 TensorRT 출력 후처리 - numpy 순수 로직.

의도적으로 tensorrt/pycuda/cv2 를 import하지 않는다. 그래서 이 모듈의 함수들은
Jetson 없이 개발 PC의 pytest로 전부 검증할 수 있다. camera.py가 전처리(cv2)와
엔진 실행(TensorRT)을 담당하고, 여기는 "출력 텐서 -> 검출 결과" 변환만 담당한다.

YOLOv8 ONNX/TensorRT 출력 형식 (v5와 다름에 주의):
    shape (1, 4+nc, 8400)  - nc=클래스 수
    행 0~3: cx, cy, w, h (입력 이미지 640 기준 픽셀 좌표)
    행 4~ : 클래스별 score (objectness 없음 - v5와의 결정적 차이)
"""

from typing import List, Optional, Tuple

import numpy as np


def letterbox_params(frame_w: int, frame_h: int, input_size: int) -> Tuple[float, int, int]:
    """원본 프레임을 input_size 정사각형에 비율 유지로 맞출 때의 (scale, pad_x, pad_y).

    camera.py의 전처리와 여기 좌표 역변환이 반드시 같은 값을 써야 해서 함수로 뽑아둠.
    """
    scale = min(input_size / frame_w, input_size / frame_h)
    new_w, new_h = int(round(frame_w * scale)), int(round(frame_h * scale))
    pad_x = (input_size - new_w) // 2
    pad_y = (input_size - new_h) // 2
    return scale, pad_x, pad_y


def decode_yolov8_output(raw: np.ndarray, num_classes: int, conf_threshold: float) -> List[Tuple[float, int, float, float, float, float]]:
    """(4+nc, 8400) 또는 (1, 4+nc, 8400) 텐서 -> [(conf, class_id, cx, cy, w, h), ...].

    conf_threshold 미만은 버린다. 좌표는 아직 입력(640) 기준.
    """
    arr = np.asarray(raw)
    if arr.ndim == 3:
        arr = arr[0]
    if arr.shape[0] != 4 + num_classes:
        # (8400, 4+nc)로 온 경우(레이아웃 반대) 전치해서 맞춘다.
        arr = arr.T
    boxes = arr[:4, :]                # (4, N)
    scores = arr[4:4 + num_classes, :]  # (nc, N)
    class_ids = np.argmax(scores, axis=0)
    confidences = scores[class_ids, np.arange(scores.shape[1])]

    keep = confidences >= conf_threshold
    result = []
    for i in np.flatnonzero(keep):
        cx, cy, w, h = boxes[:, i]
        result.append((float(confidences[i]), int(class_ids[i]), float(cx), float(cy), float(w), float(h)))
    return result


def _iou(a, b) -> float:
    # a, b: (cx, cy, w, h)
    ax1, ay1, ax2, ay2 = a[0] - a[2] / 2, a[1] - a[3] / 2, a[0] + a[2] / 2, a[1] + a[3] / 2
    bx1, by1, bx2, by2 = b[0] - b[2] / 2, b[1] - b[3] / 2, b[0] + b[2] / 2, b[1] + b[3] / 2
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    inter = max(0.0, ix2 - ix1) * max(0.0, iy2 - iy1)
    union = a[2] * a[3] + b[2] * b[3] - inter
    return inter / union if union > 0 else 0.0


def nms(detections: List[Tuple[float, int, float, float, float, float]], iou_threshold: float) -> List[Tuple[float, int, float, float, float, float]]:
    """confidence 내림차순 그리디 NMS. detections: [(conf, cls, cx, cy, w, h)]."""
    ordered = sorted(detections, key=lambda d: d[0], reverse=True)
    kept: List[Tuple[float, int, float, float, float, float]] = []
    for det in ordered:
        if all(_iou(det[2:], k[2:]) < iou_threshold for k in kept):
            kept.append(det)
    return kept


def best_detection_to_frame_coords(
    detections: List[Tuple[float, int, float, float, float, float]],
    frame_w: int,
    frame_h: int,
    input_size: int,
) -> Optional[Tuple[float, int, int, int, int, int]]:
    """최고 confidence 검출 하나를 골라 원본 프레임 좌표로 역변환.

    반환: (conf, class_id, x_center, y_center, width, height) - 원본 픽셀 기준.
    검출이 없으면 None.
    """
    if not detections:
        return None
    conf, cls, cx, cy, w, h = max(detections, key=lambda d: d[0])
    scale, pad_x, pad_y = letterbox_params(frame_w, frame_h, input_size)
    fx = (cx - pad_x) / scale
    fy = (cy - pad_y) / scale
    fw = w / scale
    fh = h / scale
    # 원본 프레임 밖으로 나가는 값은 잘라낸다.
    fx = min(max(fx, 0), frame_w)
    fy = min(max(fy, 0), frame_h)
    return conf, cls, int(round(fx)), int(round(fy)), int(round(fw)), int(round(fh))
