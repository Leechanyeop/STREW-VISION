"""[2026-08-04] IMX708 RG10 RAW 캡처 단독 테스트 (헤드리스).

실제 캡처 클래스는 ai/detector/raw_camera.RawCsiCamera (frame_hub도 이걸 씀).
이 파일은 그걸 불러 FPS/화질을 확인하는 테스트 하네스일 뿐이다.

    python3 scripts/raw_camera.py --save out --frames 30 --scale 0.8 --gamma 0.6
    python3 scripts/raw_camera.py --save out --frames 30 --wb 1.0 0.476 0.87 --bayer RG
"""

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.detector.raw_camera import RawCsiCamera  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description="IMX708 RG10 연속 RAW 캡처 테스트")
    ap.add_argument("--device", default="/dev/video0")
    ap.add_argument("--width", type=int, default=1536)
    ap.add_argument("--height", type=int, default=864)
    ap.add_argument("--black", type=int, default=64)
    ap.add_argument("--wb", type=float, nargs=3, default=[1.0, 0.476, 0.87], metavar=("R", "G", "B"))
    ap.add_argument("--bayer", default="BG", choices=["RG", "GB", "GR", "BG"])
    ap.add_argument("--exposure", type=int, default=3000)
    ap.add_argument("--gain", type=int, default=16)
    ap.add_argument("--sensor-mode", type=int, default=2, help="0:4608x2592 / 1:2304x1296 / 2:1536x864")
    ap.add_argument("--crop", type=float, default=1.0, help="중앙 크롭 비율(1.0=전체, 0.5=중앙 50%로 화각 좁힘)")
    ap.add_argument("--scale", type=float, default=0.8)
    ap.add_argument("--gamma", type=float, default=0.6)
    ap.add_argument("--save", default=None, help="이 폴더에 프레임 저장(헤드리스)")
    ap.add_argument("--frames", type=int, default=60)
    args = ap.parse_args()

    import cv2
    cam = RawCsiCamera(args.device, args.width, args.height, args.black, tuple(args.wb),
                       args.bayer, args.exposure, args.gain, args.scale, args.gamma,
                       sensor_mode=args.sensor_mode, crop=args.crop)
    save_dir = None
    if args.save:
        save_dir = Path(args.save); save_dir.mkdir(parents=True, exist_ok=True)

    print("워밍업... (첫 프레임 대기)")
    t_end = time.time() + 5
    while cam.get_latest_frame() is None and time.time() < t_end:
        time.sleep(0.05)
    if cam.get_latest_frame() is None:
        print("[FAIL] 첫 프레임 못 받음 - v4l2-ctl / 카메라 확인"); cam.close(); return 1

    n, t0 = 0, time.time()
    while n < args.frames:
        frame = cam.get_latest_frame()
        if frame is None:
            time.sleep(0.01); continue
        n += 1
        if save_dir is not None:
            cv2.imwrite(str(save_dir / "raw_{:05d}.jpg".format(n)), frame)
        if n % 10 == 0:
            fps = 10.0 / max(time.time() - t0, 1e-6); t0 = time.time()
            print("  [{}] {:.1f} FPS  mean={:.0f}  shape={}".format(n, fps, frame.mean(), frame.shape))
    cam.close()
    print("완료: {}장 -> {}".format(n, save_dir if save_dir else "(저장 안 함)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
