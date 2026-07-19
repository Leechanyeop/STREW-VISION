import threading
import time
from typing import Any, Optional


class SharedFrameCamera:
    """단일 카메라 캡처를 여러 소비자가 동시에 나눠 쓰게 해주는 공유 프레임 허브.

    [2026-07-16 추가 - 배경]
    병해충 감시 중 관리자가 판단을 내려야 할 때는 (1) 기존 YOLO/TensorRT 추론
    파이프라인(CsiCameraVisionSource.read())과 (2) 관리자에게 실시간으로 보여줄 WebRTC
    영상 트랙이 "동시에" 같은 IMX708 카메라를 봐야 한다. 그런데 CSI 카메라는 보통
    cv2.VideoCapture(V4L2) 핸들을 하나만 열 수 있다 - 같은 장치를 두 번 열면 대부분
    실패하거나 프레임이 서로 충돌해서 깨진다.

    그래서 실제 캡처(capture.read())는 이 클래스의 백그라운드 스레드 하나만 계속
    수행하고, 그 결과(가장 최근 프레임 1장)를 락으로 보호된 버퍼에 저장해둔다.
    YOLO 추론 쪽과 WebRTC 트랙 쪽 둘 다 get_latest_frame()으로 "그 순간의 최신
    프레임 복사본"만 읽어간다 - 카메라 핸들 자체를 공유하는 게 아니라 "이미 읽어온
    결과"를 공유하는 방식이라 두 소비자가 서로 간섭하지 않는다.

    주의: opencv(cv2) 모듈은 여기서 직접 import하지 않는다. camera.py가 이미
    "실제 카메라를 쓸 때만" cv2를 지역 import하는 패턴을 쓰고 있어서, 그 흐름을 그대로
    따르기 위해 cv2 모듈 자체를 호출자(camera.py)로부터 인자로 받는다. mock 모드나
    cv2가 없는 개발 PC에서 이 파일을 import해도 문제없다.
    """

    def __init__(self, cv2_module: Any, camera_index: int, frame_width: int, frame_height: int) -> None:
        self.cv2 = cv2_module
        self.capture = self.cv2.VideoCapture(camera_index, self.cv2.CAP_V4L2)
        self.capture.set(self.cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        self.capture.set(self.cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        if not self.capture.isOpened():
            raise RuntimeError(f"CSI camera open failed: index={camera_index}")

        self._lock = threading.Lock()
        self._latest_frame = None
        self._latest_frame_time = 0.0
        self._running = True
        # daemon=True: 메인 프로세스 종료 시 이 스레드 때문에 매달리지 않게.
        self._thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._thread.start()

    def _capture_loop(self) -> None:
        while self._running:
            ok, frame = self.capture.read()
            if ok and frame is not None:
                with self._lock:
                    self._latest_frame = frame
                    self._latest_frame_time = time.monotonic()
            else:
                # 일시적으로 프레임을 못 읽었을 때 CPU를 100% 태우며 도는 걸 방지.
                time.sleep(0.01)

    def get_latest_frame(self) -> Optional[Any]:
        """최신 프레임의 복사본을 반환한다 (아직 한 장도 못 읽었으면 None).
        .copy()로 넘기는 이유: 호출자가 이 배열을 그리기/변환 등으로 건드려도
        캡처 루프가 다음 프레임으로 덮어쓸 버퍼 자체와는 무관하게 만들기 위함."""
        with self._lock:
            if self._latest_frame is None:
                return None
            return self._latest_frame.copy()

    def close(self) -> None:
        self._running = False
        self._thread.join(timeout=1.0)
        self.capture.release()
