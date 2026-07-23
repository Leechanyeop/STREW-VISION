"""[2026-07-18] YOLOv8 후처리 검증 - Jetson/TensorRT 없이 numpy 합성 배열로 테스트."""

import numpy as np

from ai.detector.yolo_postprocess import (
    best_detection_to_frame_coords,
    decode_yolov8_output,
    letterbox_params,
    nms,
)

NC = 4  # healthy, powdery_mildew, missing_plant, empty_cell


def make_raw(preds):
    """[(cx,cy,w,h,scores[4])] -> (4+NC, N) 텐서."""
    n = len(preds)
    raw = np.zeros((4 + NC, n), dtype=np.float32)
    for i, (cx, cy, w, h, scores) in enumerate(preds):
        raw[0, i], raw[1, i], raw[2, i], raw[3, i] = cx, cy, w, h
        raw[4:, i] = scores
    return raw


def test_letterbox_params_1280x720_to_640():
    scale, pad_x, pad_y = letterbox_params(1280, 720, 640)
    assert scale == 0.5
    assert pad_x == 0
    assert pad_y == (640 - 360) // 2  # 위아래 140씩 패딩


def test_decode_filters_by_confidence_and_picks_class():
    raw = make_raw([
        (100, 100, 50, 50, [0.05, 0.9, 0.02, 0.03]),   # powdery_mildew 0.9 -> 통과
        (200, 200, 40, 40, [0.30, 0.1, 0.05, 0.05]),   # 최고 0.3 -> conf 0.4 미만 탈락
    ])
    dets = decode_yolov8_output(raw, NC, conf_threshold=0.4)
    assert len(dets) == 1
    conf, cls, cx, cy, w, h = dets[0]
    assert cls == 1 and abs(conf - 0.9) < 1e-6
    assert (cx, cy) == (100.0, 100.0)


def test_decode_accepts_batch_and_transposed_layouts():
    raw = make_raw([(100, 100, 50, 50, [0.9, 0.0, 0.0, 0.0])])
    batched = raw[np.newaxis, :, :]     # (1, 4+nc, N)
    transposed = raw.T                  # (N, 4+nc)
    assert len(decode_yolov8_output(batched, NC, 0.4)) == 1
    assert len(decode_yolov8_output(transposed, NC, 0.4)) == 1


def test_nms_suppresses_overlapping_keeps_distant():
    dets = [
        (0.9, 0, 100.0, 100.0, 50.0, 50.0),
        (0.8, 0, 105.0, 105.0, 50.0, 50.0),   # 위와 크게 겹침 -> 제거
        (0.7, 1, 400.0, 400.0, 50.0, 50.0),   # 멀리 떨어짐 -> 유지
    ]
    kept = nms(dets, iou_threshold=0.45)
    assert len(kept) == 2
    assert kept[0][0] == 0.9 and kept[1][0] == 0.7


def test_best_detection_maps_back_to_frame_coords():
    # 1280x720 -> 640 letterbox: scale 0.5, pad_y 140.
    # 모델 좌표 (320, 320) = 원본 (640, 360) 중앙이어야 한다.
    dets = [(0.9, 1, 320.0, 320.0, 100.0, 60.0)]
    best = best_detection_to_frame_coords(dets, 1280, 720, 640)
    conf, cls, x, y, w, h = best
    assert (x, y) == (640, 360)
    assert (w, h) == (200, 120)  # /scale = *2


def test_best_detection_none_when_empty():
    assert best_detection_to_frame_coords([], 1280, 720, 640) is None


def test_full_pipeline_synthetic():
    raw = make_raw([
        (320, 320, 100, 60, [0.05, 0.85, 0.05, 0.05]),  # powdery_mildew
        (322, 318, 98, 62, [0.05, 0.80, 0.05, 0.05]),   # 중복 -> NMS 제거
        (500, 500, 20, 20, [0.02, 0.02, 0.02, 0.03]),   # 저신뢰 -> 탈락
    ])
    dets = decode_yolov8_output(raw, NC, 0.4)
    kept = nms(dets, 0.45)
    best = best_detection_to_frame_coords(kept, 1280, 720, 640)
    conf, cls, x, y, w, h = best
    assert cls == 1          # powdery_mildew
    assert (x, y) == (640, 360)
