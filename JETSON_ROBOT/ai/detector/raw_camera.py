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


def set_focus(bus, value):
    """ArduCam IMX708 VCM(0x0C) 고정 초점 설정. value 0..1000 (0=원거리, 1000=근접).

    ArduCam Focuser 프로토콜: value(0..1000)->12bit(0..4095)<<4 후 reg0x00(상위)/0x01(하위)에 기록.
    i2c-tools(i2cset) 필요. 실패는 무시(초점 미지원/버스 오류 시에도 스트림은 계속).
    """
    value = max(0, min(1000, int(value)))
    v = int(value / 1000.0 * 4095) << 4
    for args in (["0x02", "0x00"],
                 ["0x00", "0x%02x" % ((v >> 8) & 0xFF)],
                 ["0x01", "0x%02x" % (v & 0xFF)]):
        try:
            subprocess.call(["i2cset", "-y", str(bus), "0x0c"] + args, stderr=subprocess.DEVNULL)
        except Exception:
            pass


class RawCsiCamera:
    """v4l2-ctl RG10 스트리밍 + RAW->BGR 백그라운드 스레드. get_latest_frame()로 최신 BGR 복사본."""

    def __init__(self, device="/dev/video0", width=1536, height=864,
                 black=64, wb=(1.0, 0.476, 0.87), bayer="BG",
                 exposure=3000, gain=16, scale=0.8, gamma=0.6, sensor_mode=2,
                 focus=None, i2c_bus=7, crop=1.0):
        import cv2
        self.cv2 = cv2
        self.W, self.H = width, height
        self.black = float(black)
        self.scale = float(scale)
        self.gamma = gamma
        # [2026-08-14] 중앙 크롭 비율(0<crop<=1). 150° 초광각이라 검사 각이 너무 넓을 때
        # 중앙만 남겨 화각을 좁히고 대상을 확대한다. crop=0.5 -> 가로·세로 중앙 50%만 사용.
        self.crop = max(0.05, min(1.0, float(crop)))
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

        # [2026-08-14] 순서가 중요하다: sensor_mode -> set-fmt -> exposure/gain -> stream.
        # 이유(실측): (1) sensor_mode를 안 박으면 센서가 mode0(4608x2592)을 뱉어, 우리가
        #   width*height*2 만큼만 읽으면 프레임이 어긋나 '가로 밴딩'이 생긴다.
        #   sensor_mode=2 == 1536x864@90 (0:4608 / 1:2304 / 2:1536).
        # (2) 모드/포맷을 바꾸면 노출이 초기화되므로 exposure/gain은 set-fmt '이후',
        #   스트리밍 직전에 같은 명령 안에서 건다(앞서 걸면 리셋돼 과다노출로 포화된다).
        cmd = ["v4l2-ctl", "-d", device,
               "--set-ctrl", "sensor_mode=%d" % sensor_mode,
               "--set-fmt-video=width=%d,height=%d,pixelformat=RG10" % (width, height),
               "--set-ctrl", "exposure=%d,gain=%d" % (exposure, gain),
               "--stream-mmap", "--stream-count=0", "--stream-to=-"]
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=0)

        # [2026-08-14] 고정 초점(선택). IMX708은 오토포커스(VCM) 렌즈지만 tegracam 드라이버가
        # v4l2 focus 컨트롤을 안 내보내, ArduCam VCM(I2C 0x0C, 버스=i2c_bus)에 직접 값을 쓴다.
        # focus 0..1000 (0=원거리/무한대, 1000=근접). 검사 거리(예: 30cm)에 맞는 값으로 고정.
        # 오토포커스 헌팅 없이 항상 같은 거리에 초점이 맞아 검사에 유리하다. (값은 focus_sweep.py로 탐색)
        if focus is not None:
            set_focus(i2c_bus, focus)

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
        if self.crop < 1.0:                        # 중앙 크롭 -> 화각 좁힘/확대
            h, w = bgr.shape[:2]
            ch, cw = int(h * self.crop), int(w * self.crop)
            y0, x0 = (h - ch) // 2, (w - cw) // 2
            bgr = bgr[y0:y0 + ch, x0:x0 + cw]
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
