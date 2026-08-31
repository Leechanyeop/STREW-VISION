"""[2026-08-14] IMX708 고정초점 자동 탐색 (30cm 등 검사거리용).

이 카메라(ArduCam IMX708)는 오토포커스(VCM) 렌즈지만 젯슨 tegracam 드라이버가 v4l2 focus
컨트롤을 안 내보낸다. 그래서 ArduCam VCM(I2C 0x0C)에 focus 값(0..1000)을 직접 써야 한다.
nvargus 미리보기는 이 장치에서 깨져 있으므로, 우리 RAW 파이프라인(RawCsiCamera)으로 프레임을
받아 '선명도(라플라시안 분산)'를 재면서 focus를 훑어 가장 선명한 값을 찾는다.

사용:
    # 카메라 앞 30cm에 검사 물체를 놓고 실행. 끝나면 best focus 값을 출력하고 out_focus/에 샘플 저장.
    python3 scripts/focus_sweep.py --save out_focus
    python3 scripts/focus_sweep.py --min 300 --max 1000 --coarse 50 --fine 8

찾은 값을 .env 에 넣으면 카메라가 켜질 때 그 거리로 초점이 고정된다:
    RAW_FOCUS=<best>
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.detector.raw_camera import RawCsiCamera, set_focus  # noqa: E402


def sharpness(cv2, frame):
    """중앙 ROI의 라플라시안 분산 = 초점 선명도 지표(클수록 선명)."""
    h, w = frame.shape[:2]
    roi = frame[h // 4:h * 3 // 4, w // 4:w * 3 // 4]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    return float(cv2.Laplacian(gray, cv2.CV_64F).var())


def grab_fresh(cam, settle=0.45, n=4):
    """focus 변경 후 렌즈가 움직일 시간을 준 뒤, 여러 프레임 중 가장 선명한 것을 반환."""
    time.sleep(settle)
    best, best_s = None, -1.0
    import cv2
    for _ in range(n):
        f = cam.get_latest_frame()
        if f is not None:
            s = sharpness(cv2, f)
            if s > best_s:
                best_s, best = s, f
        time.sleep(0.05)
    return best, best_s


def sweep(cam, cv2, bus, lo, hi, step, label):
    results = []
    v = lo
    while v <= hi:
        set_focus(bus, v)
        _, s = grab_fresh(cam)
        results.append((v, s))
        print("  [{}] focus={:4d}  sharpness={:.1f}".format(label, v, s))
        v += step
    return max(results, key=lambda r: r[1])


def main():
    ap = argparse.ArgumentParser(description="IMX708 고정초점 자동 탐색")
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--bus", type=int, default=7, help="ArduCam VCM I2C 버스 (기본 7)")
    ap.add_argument("--min", type=int, default=0)
    ap.add_argument("--max", type=int, default=1000)
    ap.add_argument("--coarse", type=int, default=50, help="1차 훑기 간격")
    ap.add_argument("--fine", type=int, default=8, help="best 주변 정밀 훑기 간격")
    ap.add_argument("--exposure", type=int, default=3000)
    ap.add_argument("--gain", type=int, default=16)
    ap.add_argument("--save", default="out_focus", help="best 프레임 저장 폴더")
    args = ap.parse_args()

    import cv2
    cam = RawCsiCamera(args.device, exposure=args.exposure, gain=args.gain)  # 기본: 1536x864 BG mode2

    print("워밍업...")
    t_end = time.time() + 5
    while cam.get_latest_frame() is None and time.time() < t_end:
        time.sleep(0.05)
    if cam.get_latest_frame() is None:
        print("[FAIL] 첫 프레임 못 받음 - 카메라 확인"); cam.close(); return 1

    print("1차 훑기 (coarse, {}~{} step {})...".format(args.min, args.max, args.coarse))
    best_v, best_s = sweep(cam, cv2, args.bus, args.min, args.max, args.coarse, "coarse")
    print("  -> coarse best focus={} (sharpness={:.1f})".format(best_v, best_s))

    lo = max(args.min, best_v - args.coarse)
    hi = min(args.max, best_v + args.coarse)
    print("2차 정밀 훑기 (fine, {}~{} step {})...".format(lo, hi, args.fine))
    best_v, best_s = sweep(cam, cv2, args.bus, lo, hi, args.fine, "fine")

    # best로 고정하고 샘플 저장
    set_focus(args.bus, best_v)
    frame, s = grab_fresh(cam, settle=0.6, n=6)
    save_dir = Path(args.save); save_dir.mkdir(parents=True, exist_ok=True)
    if frame is not None:
        cv2.imwrite(str(save_dir / "focus_{:04d}.jpg".format(best_v)), frame)

    cam.close()
    print("\n==============================")
    print("  BEST FOCUS = {}  (sharpness={:.1f})".format(best_v, best_s))
    print("  .env 에 넣으세요:  RAW_FOCUS={}".format(best_v))
    print("  샘플: {}/focus_{:04d}.jpg 열어서 선명한지 확인".format(args.save, best_v))
    print("==============================")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
