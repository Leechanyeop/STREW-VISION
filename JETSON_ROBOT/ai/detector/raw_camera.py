"""[2026-08-04] IMX708 RG10 RAW 연속 캡처 -> BGR (nvargus 우회, 정식 모듈).

nvargus(Argus)가 이 카메라에서 뿌옇게(소프트/저대비) 나와, RG10 Bayer RAW를 v4l2-ctl로
직접 연속 스트리밍받아 Python에서 ISP(Black level -> WB -> Demosaic -> gamma)를 해 BGR을 만든다.

인터페이스(get_latest_frame/close)가 frame_hub.SharedFrameCamera와 동일해, 그 내부 캡처만
이걸로 교체하면 camera.py/YOLO/webrtc 무수정으로 붙는다.

의존성: numpy, cv2, v4l2-ctl(v4l-utils). 추가 파이썬 패키지 불필요.
"""

import subprocess
import threading

import numpy as np


class RawCsiCamera:
    """v4l2-ctl RG10 스트리밍 + RAW->BGR 백그라운드 스레드. get_latest_frame()로 최신 BGR 복사본."""

    def __init__(self, device="/dev/video0", width=1536, height=864,
                 black=64, wb=(1.0, 0.476, 0.87), bayer="BG",
                 exposure=45000, gain=64, scale=0.8, gamma=0.6):
        import cv2
        self.cv2 = cv2
        self.W, self.H = width, height
        self.black = float(black)
        self.scale = float(scale)
        self.gamma = gamma
        self._frame_bytes = width * height * 2   # RG10 = 16bit 컨테이너/픽셀
        self._bayer_code = {
            "RG": cv2.COLOR_BayerRG2BGR, "GB": cv2.COLOR_BayerGB2BGR,
            "GR": cv2.COLOR_BayerGR2BGR, "BG": cv2.COLOR_BayerBG2BGR,
        }[bayer]

        # WB 게인맵(H,W): 2x2 RGGB 패턴 타일링해 mosaic 단계에서 한 번에 곱한다.
        gR, gG, gB = wb
        tile = np.array([[gR, gG], [gG, gB]], dtype=np.float32)  # RGGB
        self._gain_map = np.tile(tile, (height // 2, width // 2))
        self._lut = None
        if gamma:
            self._lut = (np.power(np.arange(256) / 255.0, gamma) * 255).astype(np.uint8)

        # 노출/게인 설정(있으면 - 실패 무시). 스트리밍 시작 전에.
        for ctrl in ("exposure=%d" % exposure, "gain=%d" % gain):
            try:
                subprocess.call(["v4l2-ctl", "-d", device, "--set-ctrl", ctrl],
                                stderr=subprocess.DEVNULL)
            except Exception:
                pass

        cmd = ["v4l2-ctl", "-d", device,
               "--set-fmt-video=width=%d,height=%d,pixelformat=RG10" % (width, height),
               "--stream-mmap", "--stream-count=0", "--stream-to=-"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

        self._lock = threading.Lock()
        self._latest = None
        self._running = True
        self._t = threading.Thread(target=self._loop, daemon=True)
        self._t.start()

    def _read_exact(self, n):
        buf = bytearray()
        while len(buf) < n and self._running:
            chunk = self._proc.stdout.read(n - len(buf))
            if not chunk:
                return None
            buf += chunk
        return bytes(buf) if len(buf) == n else None

    def _loop(self):
        first = True
        while self._running:
            raw = self._read_exact(self._frame_bytes)
            if raw is None:
                if self._running:
                    print("[raw_camera] 스트림 종료/부족 - v4l2-ctl / RG10 지원 확인")
                break
            f16 = (np.frombuffer(raw, np.uint16).reshape(self.H, self.W) & 0x03FF).astype(np.float32)
            bgr = self._raw_to_bgr(f16)
            if first:
                print("[raw_camera] 첫 프레임 OK:", bgr.shape)
                first = False
            with self._lock:
                self._latest = bgr

    def _raw_to_bgr(self, f16):
        f = np.maximum(f16 - self.black, 0.0)     # Black level 제거
        f *= self._gain_map                        # White balance (mosaic 단계)
        m8 = np.clip(f * self.scale, 0, 255).astype(np.uint8)
        bgr = self.cv2.cvtColor(m8, self._bayer_code)   # Demosaic
        if self._lut is not None:
            bgr = self.cv2.LUT(bgr, self._lut)     # gamma (학습 도메인 매칭용)
        return bgr

    def get_latest_frame(self):
        with self._lock:
            return None if self._latest is None else self._latest.copy()

    def close(self):
        self._running = False
        try:
            self._proc.terminate()
        except Exception:
            pass
        try:
            self._t.join(timeout=1.0)
        except Exception:
            pass
