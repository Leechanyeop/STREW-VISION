from ai.detector.result import VisionResult
import random

#실제로쓰이는 실제 AI 파이프라인이다
class VisionSource:
    def read(self) -> VisionResult:
        raise NotImplementedError

#가짜신호 개발용
class MockVisionSource(VisionSource):
    def read(self) -> VisionResult:
        return VisionResult(
            label="mock-object",
            confidence=0.80,
            x_center=640,
            y_center=360,
            width=160,
            height=120,
            status = random.choice(["healthy", "powdery_mildew", "missing_plant","empty_cell"])
        )

#진짜 카메라 연결 
class CsiCameraVisionSource(VisionSource):

    # 카메라 설정 및 TensorRT 엔진 실행
    def __init__(
        self,
        camera_index: int,
        frame_width: int,
        frame_height: int,
        yolo_model_path: str = "",
    ) -> None:
        
        import cv2

        self.cv2 = cv2
        self.capture = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        if not self.capture.isOpened():
            raise RuntimeError(f"CSI camera open failed: index={camera_index}")
        self.yolo_model_path = yolo_model_path

        # tensorrt/pycuda는 여기서만(=yolo_model_path가 있을 때만) import한다.
        # cv2를 위에서 지역 import한 것과 같은 이유: 이 두 라이브러리는 젯슨/TensorRT가
        # 실제로 깔린 환경에만 있고, mock 모드나 이 프로젝트를 pytest로 돌리는 개발 PC에는
        # 없을 수 있음. 모듈 최상단에 import 해두면 mock 모드조차 이 파일을 import하는
        # 순간 죽어버리므로, "진짜 카메라 쓸 때만" 필요한 시점에 import한다.
        if self.yolo_model_path:
            import tensorrt as trt
            import pycuda.driver as cuda
            import pycuda.autoinit  # noqa: F401  (CUDA context를 현재 스레드에 자동 생성/등록)

            try:
                trt_logger = trt.Logger(trt.Logger.WARNING)

                # 1) .engine 파일 -> TensorRT 엔진 객체로 역직렬화 (여기서 딱 한 번만)
                with open(self.yolo_model_path, "rb") as f, trt.Runtime(trt_logger) as runtime:
                    self.engine = runtime.deserialize_cuda_engine(f.read())

                # 2) 실행 컨텍스트 생성 (매 프레임 재사용, 엔진 1개당 여러개 만들 수도 있지만 여기선 1개)
                self.context = self.engine.create_execution_context()

                # 3) CUDA Stream 생성 (memcpy_htod -> execute_async -> memcpy_dtoh 순서 보장)
                self.stream = cuda.Stream()

                # 4) 입력/출력 버퍼를 CPU(host)/GPU(device) 양쪽에 미리 할당하고,
                #    bindings에 "슬롯 순서대로" GPU 주소를 담아둔다.
                #    입력 1개, 출력 3개라서 host_input/host_output 단수 이름 대신
                #    리스트로 바꿨다 (출력 3개를 변수 하나에 담을 수 없어서).
                self.host_inputs = []
                self.host_outputs = []
                self.device_inputs = []
                self.device_outputs = []
                self.bindings = []

                for binding in self.engine:
                    size = trt.volume(self.engine.get_binding_shape(binding)) * self.engine.max_batch_size
                    dtype = trt.nptype(self.engine.get_binding_dtype(binding))
                    host_mem = cuda.pagelocked_empty(size, dtype)
                    device_mem = cuda.mem_alloc(host_mem.nbytes)
                    self.bindings.append(int(device_mem))

                    if self.engine.binding_is_input(binding):
                        self.host_inputs.append(host_mem)
                        self.device_inputs.append(device_mem)
                    else:
                        self.host_outputs.append(host_mem)
                        self.device_outputs.append(device_mem)

            except Exception as e:
                # 저번 설계 리뷰 결론 그대로: 엔진 로딩/버퍼 할당 실패 시
                # 폴백(contour 탐지) 없이 즉시 에러를 보고하고 애플리케이션을 종료한다.
                raise RuntimeError(f"YOLO TensorRT engine load failed: {e}") from e



    # 프레임읽고 가장큰 물체 잡아서 돌려줌
    def read(self) -> VisionResult:
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return VisionResult(label=None)
        if self.yolo_model_path:
            return self._read_with_yolo_placeholder(frame)
        return self._read_by_simple_contour(frame)

    # 임시탐지 로직 
    # 프레임 흑백 윤곽선 찾고 사각박스 씌우고 검출됨
    def _read_by_simple_contour(self, frame) -> VisionResult:

        
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        blur = self.cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = self.cv2.threshold(
            blur,
            0,
            255,
            self.cv2.THRESH_BINARY + self.cv2.THRESH_OTSU,
        )
        contours, _ = self.cv2.findContours(
            thresh,
            self.cv2.RETR_EXTERNAL,
            self.cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            return VisionResult(label=None)

        #물체의 외곽선 윤곽선을 땀
        contour = max(contours, key=self.cv2.contourArea)
        area = self.cv2.contourArea(contour)
        if area < 100:
            return VisionResult(label=None)

        x, y, w, h = self.cv2.boundingRect(contour)
        return VisionResult(
            label="object",
            confidence=None,
            x_center=x + w // 2,
            y_center=y + h // 2,
            width=w,
            height=h,
        )

    # 실제 YOLO 추론을 넣을 자리
    # 카메라 프레임 여러번 불릴때 마다 
    # 이미로딩된 엔진으로 추론만 해야됨
    def _read_with_yolo_placeholder(self, frame) -> VisionResult:
        # YOLO inference will replace this contour fallback when the detector is wired.
        # yolo 추론코드로 대체됨 
        return self._read_by_simple_contour(frame)

    # 카메라 닫음
    def close(self) -> None:
        self.capture.release()

#일반 함수
def create_vision_source(
    mode: str,
    camera_index: int,
    frame_width: int,
    frame_height: int,
    yolo_model_path: str,
) -> VisionSource:
    if mode.lower() == "mock":
        return MockVisionSource()
    return CsiCameraVisionSource(camera_index, frame_width, frame_height, yolo_model_path)
