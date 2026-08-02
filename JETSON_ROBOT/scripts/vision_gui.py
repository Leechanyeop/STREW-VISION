"""[2026-08-02] Vision 실시간 GUI - TensorRT 검출을 카메라 화면 위에 박스로 그려서 보여준다.

로봇·Mega·AWS 없이 Vision만 돌리며, YOLOv8 TensorRT가 프레임에서 무엇을 어떻게 검출하는지
바운딩박스 + 클래스 + confidence로 실시간 시각화한다. (read()의 "최고 1개"가 아니라 NMS 후
'모든' 검출을 그린다 - 인식이 실제로 어떻게 되는지 확인용.)

사용법 (Jetson에서 - 디스플레이 연결 or `ssh -X` 필요):
    python3 scripts/vision_gui.py                    # 실시간 카메라 GUI (q 로 종료)
    python3 scripts/vision_gui.py --image test.jpg   # 정지 이미지에 검출 그려서 저장/표시
    python3 scripts/vision_gui.py --save-dir out      # 헤드리스: 프레임을 out/에 jpg로 저장
    python3 scripts/vision_gui.py --conf 0.3          # confidence 임계값 강제

박스 색: 흰가루병=빨강 / 결주=주황 / 빈셀=노랑 / 정상=초록.
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

COLOR = {
    "powdery_mildew": (0, 0, 255),   # 빨강 (BGR)
    "missing_plant": (0, 140, 255),  # 주황
    "empty_cell": (0, 255, 255),     # 노랑
    "healthy": (0, 220, 0),          # 초록
}


def _infer_all(src, frame, np):
    """엔진 실행 후 NMS까지 거친 '모든' 검출을 원본 프레임 좌표로 반환.
    반환: [(conf, class_id, cx, cy, w, h)] (원본 픽셀). src의 로드된 엔진/버퍼를 재사용."""
    from ai.detector.yolo_postprocess import decode_yolov8_output, letterbox_params, nms

    s = src.yolo_input_size
    fh, fw = frame.shape[:2]
    scale, pad_x, pad_y = letterbox_params(fw, fh, s)
    new_w, new_h = int(round(fw * scale)), int(round(fh * scale))
    resized = src.cv2.resize(frame, (new_w, new_h))
    canvas = np.full((s, s, 3), 114, dtype=np.uint8)
    canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
    chw = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0

    np.copyto(src.host_inputs[0], chw.ravel().astype(src.host_inputs[0].dtype))
    src.cuda.memcpy_htod_async(src.device_inputs[0], src.host_inputs[0], src.stream)
    src.context.execute_async_v2(src.bindings, src.stream.handle)
    for ho, do in zip(src.host_outputs, src.device_outputs):
        src.cuda.memcpy_dtoh_async(ho, do, src.stream)
    src.stream.synchronize()

    nc = len(src.yolo_class_names)
    raw = np.asarray(src.host_outputs[0]).reshape(4 + nc, -1)
    kept = nms(decode_yolov8_output(raw, nc, src.yolo_conf_threshold), src.yolo_iou_threshold)
    out = []
    for conf, cls, cx, cy, w, h in kept:
        out.append((conf, cls, (cx - pad_x) / scale, (cy - pad_y) / scale, w / scale, h / scale))
    return out


def _draw(src, frame, dets, cv2, fps=None):
    nc = len(src.yolo_class_names)
    for conf, cls, cx, cy, w, h in dets:
        name = src.yolo_class_names[cls] if 0 <= cls < nc else str(cls)
        col = COLOR.get(name, (200, 200, 200))
        x1, y1 = int(cx - w / 2), int(cy - h / 2)
        x2, y2 = int(cx + w / 2), int(cy + h / 2)
        cv2.rectangle(frame, (x1, y1), (x2, y2), col, 2)
        label = "{} {:.2f}".format(name, conf)
        cv2.rectangle(frame, (x1, y1 - 20), (x1 + 8 * len(label) + 6, y1), col, -1)
        cv2.putText(frame, label, (x1 + 3, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (10, 10, 10), 1)
    hud = "det: {}".format(len(dets))
    if fps is not None:
        hud += "  {:.1f} FPS".format(fps)
    cv2.putText(frame, hud, (10, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)
    return frame


def main() -> int:
    ap = argparse.ArgumentParser(description="STREW_VISION 실시간 검출 GUI")
    ap.add_argument("--image", default=None, help="정지 이미지 경로(주면 그 이미지에 검출 표시/저장)")
    ap.add_argument("--conf", type=float, default=None, help="confidence 임계값 강제")
    ap.add_argument("--save-dir", default=None, help="헤드리스: 프레임을 이 폴더에 jpg로 저장")
    args = ap.parse_args()

    import cv2
    import numpy as np
    from config.settings import settings as cfg
    from ai.detector.camera import CsiCameraVisionSource

    if not cfg.yolo_model_path:
        print("[FAIL] YOLO_MODEL_PATH가 비어있음 - .engine 경로 필요")
        return 1

    print("engine:", cfg.yolo_model_path, "| classes:", list(cfg.yolo_class_names))
    try:
        src = CsiCameraVisionSource(cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path)
    except Exception as e:
        print("[FAIL] 엔진 로드/소스 생성 실패:", e)
        return 1
    if args.conf is not None:
        src.yolo_conf_threshold = args.conf

    save_dir = None
    if args.save_dir:
        save_dir = Path(args.save_dir)
        save_dir.mkdir(parents=True, exist_ok=True)

    # ---- 정지 이미지 ----
    if args.image:
        frame = cv2.imread(args.image)
        if frame is None:
            print("[FAIL] 이미지 로드 실패:", args.image)
            return 1
        dets = _infer_all(src, frame, np)
        _draw(src, frame, dets, cv2)
        outp = str(Path(args.image).with_name(Path(args.image).stem + "_result.jpg"))
        cv2.imwrite(outp, frame)
        print("검출 {}개 - 저장: {}".format(len(dets), outp))
        for conf, cls, cx, cy, w, h in dets:
            nm = src.yolo_class_names[cls] if 0 <= cls < len(src.yolo_class_names) else cls
            print("  {} {:.2f}  box=({:.0f},{:.0f},{:.0f},{:.0f})".format(nm, conf, cx, cy, w, h))
        try:
            cv2.imshow("STREW Vision", frame); cv2.waitKey(0); cv2.destroyAllWindows()
        except Exception:
            print("(디스플레이 없음 - 저장된 이미지 확인)")
        src.close()
        return 0

    # ---- 실시간 카메라 ----
    cam = src.get_shared_camera()
    has_gui = save_dir is None
    print("실시간 검출 시작 - {} (q 종료)".format("GUI 창" if has_gui else "저장 모드: " + str(save_dir)))
    n, t_last = 0, time.time()
    try:
        while True:
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(0.05); continue
            frame = frame.copy()
            t0 = time.time()
            dets = _infer_all(src, frame, np)
            fps = 1.0 / max(1e-6, (time.time() - t0))
            _draw(src, frame, dets, cv2, fps)
            n += 1
            if has_gui:
                try:
                    cv2.imshow("STREW Vision", frame)
                    if (cv2.waitKey(1) & 0xFF) == ord('q'):
                        break
                except Exception as e:
                    print("[!] GUI 표시 불가({}) - --save-dir 로 저장 모드 쓰거나 ssh -X 사용".format(e))
                    has_gui = False
                    save_dir = save_dir or Path("vision_out"); save_dir.mkdir(exist_ok=True)
            if not has_gui:
                cv2.imwrite(str(save_dir / "frame_{:05d}.jpg".format(n)), frame)
                if n % 10 == 0:
                    print("  저장 {}장... (Ctrl+C 종료)".format(n))
    except KeyboardInterrupt:
        print("\n(중단)")
    finally:
        try:
            cv2.destroyAllWindows()
        except Exception:
            pass
        src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
