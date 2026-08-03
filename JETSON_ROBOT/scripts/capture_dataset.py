"""[2026-08-03] 데이터셋 수집 - Jetson CSI(IMX708)로 샘플 이미지를 저장한다.

흰가루병 검출 가중치가 실제 온실 도메인을 못 잡는 문제 -> 젯슨 카메라로 직접 찍은
이미지를 모아 라벨링/재학습하기 위한 원천 수집 도구. 로봇/Mega/AWS/엔진 없이 카메라만 쓴다.
검증된 캡처 경로(ai/detector/frame_hub.SharedFrameCamera = nvargus GStreamer)를 그대로 재사용.

사용법 (Jetson, SSH 헤드리스 OK):
    python3 scripts/capture_dataset.py                       # 100장, 0.8초 간격, ./dataset_raw 에 저장
    python3 scripts/capture_dataset.py --count 50            # 50장
    python3 scripts/capture_dataset.py --interval 1.5        # 간격 늘려 잎 바꿀 시간 확보
    python3 scripts/capture_dataset.py --manual              # Enter 칠 때마다 1장(신중 촬영)
    python3 scripts/capture_dataset.py --width 1536 --height 864   # 더 큰 해상도로
    python3 scripts/capture_dataset.py --prefix powdery      # 파일명 접두어(병징별로 나눠 찍기 좋음)
    python3 scripts/capture_dataset.py --out /home/blackhood/captures

TIP(중요): 100장이 서로 비슷하면 학습에 도움이 안 된다. 촬영 중 카메라/잎을 계속
    움직이고 각도·거리·조명을 바꿔라. 흰가루 잎을 집중적으로 찍되 healthy도 섞어라.
"""

import argparse
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    ap = argparse.ArgumentParser(description="Jetson CSI 데이터셋 수집")
    ap.add_argument("--count", type=int, default=100, help="저장할 장수(기본 100)")
    ap.add_argument("--interval", type=float, default=0.8, help="자동 모드 촬영 간격(초)")
    ap.add_argument("--manual", action="store_true", help="Enter 칠 때마다 1장 저장")
    ap.add_argument("--out", default="dataset_raw", help="저장 폴더")
    ap.add_argument("--prefix", default="csi", help="파일명 접두어")
    ap.add_argument("--width", type=int, default=None, help="캡처 폭(기본: config)")
    ap.add_argument("--height", type=int, default=None, help="캡처 높이(기본: config)")
    ap.add_argument("--quality", type=int, default=95, help="JPEG 품질(1~100)")
    ap.add_argument("--warmup", type=float, default=2.0, help="첫 프레임 확보 대기(초)")
    args = ap.parse_args()

    import cv2
    from config.settings import settings as cfg
    from ai.detector.frame_hub import SharedFrameCamera

    w = args.width or cfg.frame_width
    h = args.height or cfg.frame_height

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 52)
    print(" STREW_VISION 데이터셋 수집 (Jetson CSI)")
    print("=" * 52)
    print("저장 폴더 :", out_dir.resolve())
    print("해상도    : {}x{}".format(w, h))
    print("모드      :", "수동(Enter)" if args.manual else "자동({}초 간격)".format(args.interval))
    print("목표 장수 :", args.count)
    print()

    # 카메라 오픈 (nvargus). 첫 프레임까지 잠깐 대기.
    try:
        cam = SharedFrameCamera(cv2, cfg.csi_camera_index, w, h)
    except Exception as e:
        print("[FAIL] 카메라 오픈 실패:", e)
        return 1

    print("카메라 워밍업 {}초...".format(args.warmup))
    t_end = time.time() + args.warmup
    frame = None
    while time.time() < t_end:
        frame = cam.get_latest_frame()
        if frame is not None:
            break
        time.sleep(0.1)
    if frame is None:
        # 조금 더 기다려본다
        for _ in range(30):
            frame = cam.get_latest_frame()
            if frame is not None:
                break
            time.sleep(0.1)
    if frame is None:
        print("[FAIL] 프레임을 못 받음 - 카메라/케이블 확인")
        cam.close()
        return 1
    print("첫 프레임 OK:", frame.shape, "-> 촬영 시작\n")

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    jpg_params = [cv2.IMWRITE_JPEG_QUALITY, max(1, min(100, args.quality))]
    saved = 0
    try:
        while saved < args.count:
            if args.manual:
                try:
                    input("[{}/{}] Enter=저장 (q+Enter=종료) > ".format(saved + 1, args.count))
                except EOFError:
                    break
            frame = cam.get_latest_frame()
            if frame is None:
                time.sleep(0.05)
                continue
            fname = "{}_{}_{:04d}.jpg".format(args.prefix, stamp, saved + 1)
            path = out_dir / fname
            cv2.imwrite(str(path), frame, jpg_params)
            saved += 1
            if args.manual:
                print("  저장:", fname)
            else:
                if saved % 10 == 0 or saved == 1:
                    print("[{:3d}/{}] 저장 {} ({}x{})".format(saved, args.count, fname, frame.shape[1], frame.shape[0]))
                time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n(중단)")
    finally:
        cam.close()

    print("\n=== 완료 ===")
    print("총 {}장 저장 -> {}".format(saved, out_dir.resolve()))
    print("파일 수 확인: ls {} | wc -l".format(out_dir))
    print("\n다음 단계: PC로 복사 후 라벨링. 예)")
    print("  scp -r blackhood@<젯슨IP>:{}/  \"C:\\\\VISION SOURCE\\\\raw_captures\\\\\"".format(out_dir.resolve()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
