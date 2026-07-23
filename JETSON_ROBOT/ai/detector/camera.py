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
        from ai.detector.frame_hub import SharedFrameCamera

        self.cv2 = cv2
        # [2026-07-16 변경] 카메라 캡처 자체는 이제 SharedFrameCamera(백그라운드 스레드)가
        # 전담한다 - 병해충 의심 판정 시 WebRTC 라이브 스트리밍이 같은 카메라를 동시에
        # 봐야 해서, capture.read()를 직접 부르는 대신 공유 최신 프레임을 읽어온다.
        # (자세한 이유는 ai/detector/frame_hub.py 모듈 docstring 참고.)
        self.shared_camera = SharedFrameCamera(cv2, camera_index, frame_width, frame_height)
        self.yolo_model_path = yolo_model_path

        # tensorrt/pycuda는 여기서만(=yolo_model_path가 있을 때만) import한다.
        # cv2를 위에서 지역 import한 것과 같은 이유: 이 두 라이브러리는 젯슨/TensorRT가
        # 실제로 깔린 환경에만 있고, mock 모드나 이 프로젝트를 pytest로 돌리는 개발 PC에는
        # 없을 수 있음. 모듈 최상단에 import 해두면 mock 모드조차 이 파일을 import하는
        # 순간 죽어버리므로, "진짜 카메라 쓸 때만" 필요한 시점에 import한다.
        # [2026-07-18] YOLOv8 추론 파라미터는 전역 설정에서 읽는다 (환경변수로 조절 가능).
        from config.settings import settings as _s
        self.yolo_conf_threshold = _s.yolo_conf_threshold
        self.yolo_iou_threshold = _s.yolo_iou_threshold
        self.yolo_input_size = _s.yolo_input_size
        self.yolo_class_names = _s.yolo_class_names

        if self.yolo_model_path:
            import tensorrt as trt  # type: ignore
            import pycuda.driver as cuda  # type: ignore
            import pycuda.autoinit  # type: ignore  # noqa: F401  (CUDA context를 현재 스레드에 자동 생성/등록)

            # read() 경로(_read_with_yolo)에서 memcpy/stream을 써야 하므로 모듈 참조를 보관.
            self.cuda = cuda

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

                # [#18 리뷰 노트] get_binding_shape/binding_is_input/max_batch_size는
                # TensorRT 8.5+에서 제거된 구식 API지만, Jetson Nano(JetPack 4.x)의
                # TRT 8.2에서는 정상 동작한다. Nano를 벗어나 TRT를 올리게 되면
                # engine.get_tensor_shape()/get_tensor_mode() 계열로 바꿔야 한다.
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
        frame = self.shared_camera.get_latest_frame()
        if frame is None:
            return VisionResult(label=None)
        if self.yolo_model_path:
            return self._read_with_yolo(frame)
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

    # [2026-07-18] 실제 YOLOv8 TensorRT 추론 (#19 완료 - placeholder 대체).
    # __init__에서 이미 로딩된 엔진/버퍼를 매 프레임 재사용한다 - 여기서는 추론만.
    def _read_with_yolo(self, frame) -> VisionResult:
        import numpy as np
        from ai.detector.yolo_postprocess import (
            best_detection_to_frame_coords,
            decode_yolov8_output,
            letterbox_params,
            nms,
        )

        frame_h, frame_w = frame.shape[:2]
        s = self.yolo_input_size

        # 1) 전처리: letterbox(비율 유지 + 회색 패딩) -> RGB -> CHW -> 0~1 정규화
        scale, pad_x, pad_y = letterbox_params(frame_w, frame_h, s)
        new_w, new_h = int(round(frame_w * scale)), int(round(frame_h * scale))
        resized = self.cv2.resize(frame, (new_w, new_h))
        canvas = np.full((s, s, 3), 114, dtype=np.uint8)  # YOLO 관례상 114 회색 패딩
        canvas[pad_y:pad_y + new_h, pad_x:pad_x + new_w] = resized
        rgb = canvas[:, :, ::-1]                      # BGR -> RGB
        chw = rgb.transpose(2, 0, 1).astype(np.float32) / 255.0

        # 2) 엔진 실행: host 입력 버퍼에 복사 -> GPU -> 추론 -> 출력 회수
        np.copyto(self.host_inputs[0], chw.ravel().astype(self.host_inputs[0].dtype))
        self.cuda.memcpy_htod_async(self.device_inputs[0], self.host_inputs[0], self.stream)
        self.context.execute_async_v2(self.bindings, self.stream.handle)
        for host_out, device_out in zip(self.host_outputs, self.device_outputs):
            self.cuda.memcpy_dtoh_async(host_out, device_out, self.stream)
        self.stream.synchronize()

        # 3) 후처리: (4+nc, 8400) 디코드 -> NMS -> 최고 confidence 1개 -> 원본 좌표
        num_classes = len(self.yolo_class_names)
        raw = np.asarray(self.host_outputs[0]).reshape(4 + num_classes, -1)
        detections = decode_yolov8_output(raw, num_classes, self.yolo_conf_threshold)
        kept = nms(detections, self.yolo_iou_threshold)
        best = best_detection_to_frame_coords(kept, frame_w, frame_h, s)
        if best is None:
            return VisionResult(label=None)

        conf, cls, x_center, y_center, width, height = best
        class_name = self.yolo_class_names[cls] if 0 <= cls < num_classes else str(cls)
        return VisionResult(
            label=class_name,
            confidence=round(conf, 3),
            x_center=x_center,
            y_center=y_center,
            width=width,
            height=height,
            # 학습 클래스가 곧 상태값(healthy/powdery_mildew/missing_plant/empty_cell)이라
            # status에 그대로 넣는다 - planner가 이 값으로 판단요청 여부를 결정한다.
            status=class_name,
        )

    # 카메라 닫음
    def close(self) -> None:
        self.shared_camera.close()

    # [2026-07-16 추가] WebRTC publisher(robot/webrtc_publisher.py)가 병해충 의심
    # 판정으로 관리자 라이브 스트림을 열어야 할 때, YOLO 추론이 쓰는 것과 "같은"
    # 카메라 캡처(SharedFrameCamera)를 그대로 넘겨받기 위한 접근자. 새 cv2.VideoCapture를
    # 또 여는 게 아니라 이미 떠 있는 캡처를 공유하는 것이 핵심 - 자세한 이유는
    # frame_hub.py 참고.
    def get_shared_camera(self) -> "SharedFrameCamera":
        return self.shared_camera

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
