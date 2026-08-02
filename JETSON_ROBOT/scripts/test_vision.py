"""[2026-08-02] Vision 단독 테스트 - TensorRT 엔진/추론 파이프라인을 로봇·Mega·AWS 없이 검증.

Vision 모듈만 떼어내 create_vision_source() -> read() -> VisionResult 를 직접 돌려본다.
엔진 로드 / 전처리 / TensorRT 실행 / 후처리(NMS) / VisionResult 변환이 정상인지, 추론 속도가
얼마인지 한 번에 확인한다.

사용법 (Jetson에서):
    python3 scripts/test_vision.py                       # 설정(VISION_MODE)대로 카메라에서 10회 추론
    python3 scripts/test_vision.py --count 30            # 30회 추론(FPS 측정)
    python3 scripts/test_vision.py --image test.jpg      # 정지 이미지 1장으로 엔진 추론(카메라 불필요)
    python3 scripts/test_vision.py --mode csi            # 모드 강제
    YOLO_MODEL_PATH=models/best.engine python3 scripts/test_vision.py

출력: 프레임별 status/confidence/박스 + 추론 시간(ms), 마지막에 평균 ms / FPS / 클래스 분포.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="STREW_VISION Vision 단독 테스트")
    ap.add_argument("--count", type=int, default=10, help="카메라 모드에서 추론 횟수")
    ap.add_argument("--interval", type=float, default=0.2, help="추론 간 대기(초)")
    ap.add_argument("--image", default=None, help="정지 이미지 경로(주면 카메라 없이 엔진만 테스트)")
    ap.add_argument("--mode", default=None, help="vision_mode 강제(mock/csi). 없으면 설정값")
    args = ap.parse_args()

    from config.settings import settings as cfg
    mode = (args.mode or cfg.vision_mode).lower()

    print("=" * 48)
    print(" STREW_VISION Vision 단독 테스트")
    print("=" * 48)
    print("mode        :", mode)
    print("engine path :", cfg.yolo_model_path)
    print("class_names :", list(cfg.yolo_class_names))
    print("conf/iou    : {} / {}".format(cfg.yolo_conf_threshold, cfg.yolo_iou_threshold))
    print("input size  :", cfg.yolo_input_size)
    print()

    # ---- 정지 이미지 모드: 카메라 없이 엔진 추론만 검증 ----
    if args.image:
        import cv2
        from ai.detector.camera import CsiCameraVisionSource

        frame = cv2.imread(args.image)
        if frame is None:
            print("[FAIL] 이미지 로드 실패:", args.image)
            return 1
        print("이미지 로드:", args.image, "shape:", frame.shape)
        try:
            src = CsiCameraVisionSource(cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path)
        except Exception as e:
            print("[FAIL] 엔진 로드/소스 생성 실패:", e)
            return 1
        t0 = time.time()
        res = src._read_with_yolo(frame)   # 카메라 우회, 엔진+전처리+후처리 직접 실행
        dt = (time.time() - t0) * 1000.0
        print("추론 결과:", res.to_payload())
        print("추론 시간: {:.1f} ms".format(dt))
        try:
            src.close()
        except Exception:
            pass
        return 0

    # ---- 카메라 모드: create_vision_source -> read() 반복 ----
    from ai.detector.camera import create_vision_source
    try:
        src = create_vision_source(mode, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path)
    except Exception as e:
        print("[FAIL] Vision 소스 생성 실패(엔진/카메라 확인):", e)
        return 1

    if mode == "csi":
        time.sleep(1.0)  # 공유 카메라 첫 프레임 확보 대기

    times = []
    classes = {}
    try:
        for i in range(args.count):
            t0 = time.time()
            res = src.read()
            dt = (time.time() - t0) * 1000.0
            times.append(dt)
            p = res.to_payload()
            st = p.get("status") or p.get("label") or "None"
            classes[st] = classes.get(st, 0) + 1
            print("[{:2d}] {:6.1f} ms  status={:<16} conf={}  box=({},{},{},{})".format(
                i + 1, dt, str(st), p.get("confidence"),
                p.get("x_center"), p.get("y_center"), p.get("width"), p.get("height")))
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n(중단)")
    finally:
        try:
            src.close()
        except Exception:
            pass

    if times:
        avg = sum(times) / len(times)
        fps = 1000.0 / avg if avg > 0 else 0.0
        print()
        print("=== 요약 ===")
        print("추론 {}회 · 평균 {:.1f} ms · 최소 {:.1f} · 최대 {:.1f} · ~{:.1f} FPS".format(
            len(times), avg, min(times), max(times), fps))
        print("클래스 분포:", classes)
        if mode == "csi" and all(t < 1.0 for t in times):
            print("[!] 추론이 너무 빨라(≈0ms) - 엔진 미로드/폴백(contour) 가능성. yolo_model_path 확인.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
