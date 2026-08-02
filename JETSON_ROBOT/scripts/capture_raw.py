"""[2026-08-02] IMX708 RAW10(RG10) 프레임 캡처 + 디베이어 테스트.

OpenCV VideoCapture가 CSI RAW10을 못 읽어서(select timeout), v4l2-ctl로 raw 한 장을 뜬 뒤
numpy로 10비트 언팩 + Bayer(RGGB) -> BGR 변환해서 test.jpg로 저장한다.

이 스크립트가 성공하면:
  (1) 카메라 RAW 캡처 경로 OK
  (2) 디베이어 레시피 확정 -> 같은 로직을 ai/detector/frame_hub.py에 이식(최소 변경)
검증 후 --engine 을 주면 그 프레임으로 TensorRT 추론까지 바로 돌려본다.

사용법 (Jetson):
    python3 scripts/capture_raw.py                       # 1536x864 캡처 -> test.jpg
    python3 scripts/capture_raw.py --width 2304 --height 1296
    python3 scripts/capture_raw.py --pattern GB          # 색 이상하면 RG/GB/GR/BG 바꿔가며
    python3 scripts/capture_raw.py --engine              # 캡처+디베이어 후 엔진 추론까지
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# OpenCV Bayer 규칙은 헷갈리므로 4가지 다 준비 - 색이 이상하면 --pattern으로 교체.
_PATTERNS = {}  # 실행 시 cv2 로드 후 채움


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--width", type=int, default=1536)
    ap.add_argument("--height", type=int, default=864)
    ap.add_argument("--pattern", default="RG", choices=["RG", "GB", "GR", "BG"], help="Bayer 패턴(색 틀리면 교체)")
    ap.add_argument("--out", default="test.jpg")
    ap.add_argument("--raw", default="/tmp/frame.raw")
    ap.add_argument("--engine", action="store_true", help="캡처 후 TensorRT 추론까지 실행")
    args = ap.parse_args()

    import cv2
    import numpy as np
    _PATTERNS.update({
        "RG": cv2.COLOR_BayerRG2BGR, "GB": cv2.COLOR_BayerGB2BGR,
        "GR": cv2.COLOR_BayerGR2BGR, "BG": cv2.COLOR_BayerBG2BGR,
    })

    W, H = args.width, args.height

    # 1) v4l2-ctl로 포맷 지정 + 1프레임 RAW 캡처 (OpenCV 우회)
    cmd = ["v4l2-ctl", "-d", args.device,
           "--set-fmt-video=width={},height={},pixelformat=RG10".format(W, H),
           "--stream-mmap", "--stream-count=1", "--stream-to=" + args.raw]
    print("[1] 캡처:", " ".join(cmd))
    try:
        rc = subprocess.call(cmd)
    except FileNotFoundError:
        print("[FAIL] v4l2-ctl 없음 -> sudo apt install v4l-utils")
        return 1
    if rc != 0 or not os.path.exists(args.raw) or os.path.getsize(args.raw) == 0:
        print("[FAIL] v4l2-ctl 캡처 실패 (rc={})".format(rc))
        return 1

    # 2) RG10: 픽셀당 2바이트(16비트 컨테이너, 하위 10비트 유효)
    raw = np.fromfile(args.raw, dtype=np.uint16)
    expected = W * H
    print("[2] raw {} bytes -> {} px (기대 {})".format(os.path.getsize(args.raw), raw.size, expected))
    if raw.size < expected:
        print("[FAIL] raw 크기 부족 - stride 패딩이 있을 수 있음. 해상도를 낮춰(1536x864) 재시도.")
        return 1
    bayer = raw[:expected].reshape(H, W)
    bayer8 = (bayer >> 2).astype(np.uint8)   # 10bit -> 8bit

    # 3) 디베이어 -> BGR
    bgr = cv2.cvtColor(bayer8, _PATTERNS[args.pattern])
    cv2.imwrite(args.out, bgr)
    print("[3] 디베이어({}) -> 저장: {} {}".format(args.pattern, args.out, bgr.shape))
    print("    색이 이상하면 --pattern GB / GR / BG 로 바꿔서 재실행.")

    # 4) (선택) 엔진 추론까지
    if args.engine:
        from config.settings import settings as cfg
        from ai.detector.camera import CsiCameraVisionSource
        print("[4] 엔진 추론:", cfg.yolo_model_path)
        try:
            src = CsiCameraVisionSource.__new__(CsiCameraVisionSource)  # __init__(카메라 오픈) 우회
            # 엔진만 로드하도록 필요한 필드 세팅
            src.cv2 = cv2
            src.yolo_model_path = cfg.yolo_model_path
            src.yolo_conf_threshold = cfg.yolo_conf_threshold
            src.yolo_iou_threshold = cfg.yolo_iou_threshold
            src.yolo_input_size = cfg.yolo_input_size
            src.yolo_class_names = cfg.yolo_class_names
            _load_engine_only(src, cfg.yolo_model_path)
            res = src._read_with_yolo(bgr)
            print("    결과:", res.to_payload())
        except Exception as e:
            print("    [엔진 추론 스킵/실패]:", e)
    return 0


def _load_engine_only(src, engine_path):
    # camera.py __init__의 엔진 로드 부분만 떼어와 실행(카메라 오픈 없이).
    import tensorrt as trt
    import pycuda.driver as cuda
    import pycuda.autoinit  # noqa
    src.cuda = cuda
    logger = trt.Logger(trt.Logger.WARNING)
    with open(engine_path, "rb") as f, trt.Runtime(logger) as rt:
        src.engine = rt.deserialize_cuda_engine(f.read())
    src.context = src.engine.create_execution_context()
    src.stream = cuda.Stream()
    src.host_inputs, src.host_outputs = [], []
    src.device_inputs, src.device_outputs = [], []
    src.bindings = []
    for b in src.engine:
        size = trt.volume(src.engine.get_binding_shape(b)) * src.engine.max_batch_size
        dtype = trt.nptype(src.engine.get_binding_dtype(b))
        host = cuda.pagelocked_empty(size, dtype)
        dev = cuda.mem_alloc(host.nbytes)
        src.bindings.append(int(dev))
        if src.engine.binding_is_input(b):
            src.host_inputs.append(host); src.device_inputs.append(dev)
        else:
            src.host_outputs.append(host); src.device_outputs.append(dev)


if __name__ == "__main__":
    raise SystemExit(main())
