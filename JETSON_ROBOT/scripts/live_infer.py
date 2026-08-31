"""[2026-08-14] 카메라 연속 추론 + 라이브 스트림 (로봇 사이클/메가 없이 독립 실행).

main.py는 추론을 '로봇 사이클(메가 STATE-ACK)'에 맞춰 View 검사 시에만 돌린다. 이 스크립트는
그 사이클 없이 카메라 프레임마다 계속 YOLO 추론을 돌리고, 결과 박스를 그린 프레임을 MJPEG로
송출한다. 카메라 설정은 .env(RAW_* / YOLO_*)를 그대로 읽는다.

    python3 scripts/live_infer.py
    브라우저:  http://<젯슨IP>:8090/
    종료: Ctrl+C
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from dotenv import load_dotenv
    load_dotenv()   # .env -> os.environ (RAW_*, YOLO_*, CSI_* 반영)
except Exception:
    pass

from ai.detector.camera import CsiCameraVisionSource   # noqa: E402
from robot.vision_stream import VisionStreamServer      # noqa: E402


def main():
    idx = int(os.getenv("CSI_CAMERA_INDEX", "0"))
    fw = int(os.getenv("FRAME_WIDTH", "1280"))
    fh = int(os.getenv("FRAME_HEIGHT", "720"))
    model = os.getenv("YOLO_MODEL_PATH", "models/best.engine")
    port = int(os.getenv("STREAM_PORT", "8090"))

    print("엔진/카메라 로딩...")
    src = CsiCameraVisionSource(idx, fw, fh, model)

    # 첫 프레임 대기
    t_end = time.time() + 8
    while src.shared_camera.get_latest_frame() is None and time.time() < t_end:
        time.sleep(0.05)
    if src.shared_camera.get_latest_frame() is None:
        print("[FAIL] 카메라 첫 프레임 못 받음 - .env/카메라 확인"); src.close(); return 1

    server = VisionStreamServer(src.get_stream_frame, port=port)
    print("연속 추론 시작. 스트림: http://<젯슨IP>:%d/   (Ctrl+C 종료)" % port)

    n, t0 = 0, time.time()
    try:
        while True:
            r = src.read()          # 프레임 1장 추론 + 박스 프레임 갱신(get_stream_frame이 송출)
            n += 1
            if getattr(r, "label", None):
                print("  검출: %s conf=%s  (%dx%d @ %d,%d)" % (
                    r.label, getattr(r, "confidence", None),
                    getattr(r, "width", 0), getattr(r, "height", 0),
                    getattr(r, "x_center", 0), getattr(r, "y_center", 0)))
            if n % 30 == 0:
                fps = 30.0 / max(time.time() - t0, 1e-6); t0 = time.time()
                print("  [%d] 추론 %.1f FPS" % (n, fps))
    except KeyboardInterrupt:
        print("\n종료 중...")
    finally:
        try:
            server.close()
        except Exception:
            pass
        src.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
