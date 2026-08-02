import threading
import time
from typing import Any, Optional


class SharedFrameCamera:
    """단일 카메라 캡처를 여러 소비자가 동시에 나눠 쓰게 해주는 공유 프레임 허브.

    [2026-07-16] 배경: 병해충 감시 중 (1) YOLO/TensorRT 추론과 (2) 관리자용 WebRTC 영상이
    동시에 같은 IMX708 카메라를 봐야 한다. 실제 캡처는 이 클래스의 백그라운드 스레드 하나만
    수행하고, 최신 프레임 1장을 락으로 보호된 버퍼에 저장한다. 소비자는 get_latest_frame()으로
    "그 순간 최신 프레임 복사본"만 읽어가 서로 간섭하지 않는다.

    [2026-08-02] 캡처 방식 변경 - OpenCV VideoCapture(V4L2) -> GStreamer(nvarguscamerasrc).
    이유: IMX708 CSI는 /dev/video0으로 RAW10(RG10 Bayer)만 내보내고, 젯슨의 스톡 OpenCV(3.2)는
    GStreamer 미포함이라 nvargus 파이프라인을 못 쓴다. 그래서 캡처는 GStreamer Python 바인딩
    (gi.repository.Gst) + appsink 로 직접 파이프라인을 돌려 BGR numpy 프레임을 뽑는다.
    이 변경은 이 파일(캡처부) 안에서만 일어나며, get_latest_frame()이 돌려주는 것은 여전히
    "BGR numpy 프레임"이라 camera.py / VisionResult / downstream 은 수정하지 않는다.

    NVMM 캡처 해상도는 센서 모드(1536x864 - 90fps 가능한 빠른 모드)로 고정하고, 출력은 nvvidconv
    로 요청 해상도(frame_width x frame_height)로 스케일해 BGR로 변환한다.
    """

    # 센서 모드(NVMM 캡처 해상도). 지원: 4608x2592@14 / 2304x1296@55 / 1536x864@90.
    _SENSOR_W = 1536
    _SENSOR_H = 864
    _FRAMERATE = 30
    _FLIP_METHOD = 0   # 화면이 뒤집혀 보이면 2(상하) 또는 6/4 등으로 조정.

    def __init__(self, cv2_module: Any, camera_index: int, frame_width: int, frame_height: int) -> None:
        self.cv2 = cv2_module

        # 무거운/하드웨어 전용 모듈은 실제 카메라를 열 때만 import (mock/PC import 안전).
        import numpy as np
        import gi
        gi.require_version("Gst", "1.0")
        from gi.repository import Gst
        # [중요] GstApp gir를 로드해야 appsink에 try_pull_sample()/pull_sample() '메서드'가 붙는다.
        # (안 불러오면 appsink가 일반 GstElement로만 보여 try_pull_sample 메서드가 없다.)
        try:
            gi.require_version("GstApp", "1.0")
            from gi.repository import GstApp  # noqa: F401 (import 자체로 메서드 바인딩)
        except Exception:
            pass

        self.np = np
        self.Gst = Gst
        Gst.init(None)

        pipeline = (
            "nvarguscamerasrc sensor-id={idx} ! "
            "video/x-raw(memory:NVMM),width={sw},height={sh},framerate={fps}/1 ! "
            "nvvidconv flip-method={flip} ! "
            "video/x-raw,width={w},height={h},format=BGRx ! "
            "videoconvert ! video/x-raw,format=BGR ! "
            "appsink name=sink max-buffers=1 drop=true sync=false"
        ).format(idx=camera_index, sw=self._SENSOR_W, sh=self._SENSOR_H, fps=self._FRAMERATE,
                 flip=self._FLIP_METHOD, w=frame_width, h=frame_height)

        try:
            self._pipeline = Gst.parse_launch(pipeline)
        except Exception as e:
            raise RuntimeError("GStreamer 파이프라인 생성 실패: {}".format(e))
        self._sink = self._pipeline.get_by_name("sink")
        if self._sink is None:
            raise RuntimeError("appsink를 찾지 못함 - 파이프라인 확인")
        self._pipeline.set_state(Gst.State.PLAYING)

        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_frame_time = 0.0
        self._running = True
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        Gst = self.Gst
        np = self.np
        bus = self._pipeline.get_bus()
        first = True
        while self._running:
            # 파이프라인 하류 에러(caps 협상 실패 등) 있으면 찍는다 - 프레임 안 오는 원인 진단용.
            msg = bus.pop_filtered(Gst.MessageType.ERROR)
            if msg is not None:
                err, dbg = msg.parse_error()
                print("[frame_hub] GStreamer 에러:", err, "|", dbg)

            # sample pull: GstApp 로드됐으면 try_pull_sample() 메서드, 아니면 action 시그널 emit.
            # 둘 다 timeout(ns) 후 None(타임아웃) 반환. 0.5초 폴링.
            try:
                if hasattr(self._sink, "try_pull_sample"):
                    sample = self._sink.try_pull_sample(Gst.SECOND // 2)
                else:
                    sample = self._sink.emit("try-pull-sample", Gst.SECOND // 2)
            except Exception as e:
                print("[frame_hub] pull 예외:", e)
                time.sleep(0.1)
                continue
            if sample is None:
                continue

            buf = sample.get_buffer()
            st = sample.get_caps().get_structure(0)
            w = st.get_value("width")
            h = st.get_value("height")
            ok, info = buf.map(Gst.MapFlags.READ)
            if not ok:
                continue
            try:
                # BGR 3채널 연속 버퍼 -> (h, w, 3) numpy 복사본.
                frame = np.frombuffer(info.data, dtype=np.uint8)
                if frame.size < w * h * 3:
                    continue
                frame = frame[:w * h * 3].reshape(h, w, 3).copy()
            finally:
                buf.unmap(info)

            if first:
                print("[frame_hub] 첫 프레임 수신 OK:", frame.shape)
                first = False
            with self._lock:
                self._latest_frame = frame
                self._latest_frame_time = time.monotonic()

    def get_latest_frame(self) -> Optional[Any]:
        """최신 프레임의 복사본 반환 (아직 한 장도 못 읽었으면 None). 반환은 BGR numpy 그대로."""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def close(self) -> None:
        self._running = False
        try:
            self._thread.join(timeout=1.0)
        except Exception:
            pass
        try:
            self._pipeline.set_state(self.Gst.State.NULL)
        except Exception:
            pass
