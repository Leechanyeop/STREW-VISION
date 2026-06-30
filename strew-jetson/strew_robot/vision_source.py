from typing import Optional
from .models import VisionResult

class VisionSource:
    def read(self) -> VisionResult:
        raise NotImplementedError

class MockVisionSource(VisionSource):
    def read(self) -> VisionResult:
        return VisionResult(label="mock-object", confidence=0.80, x_center=640, y_center=360, width=160, height=120)

class CsiCameraVisionSource(VisionSource):
    def __init__(self, camera_index: int, frame_width: int, frame_height: int, yolo_model_path: str = "") -> None:
        import cv2
        self.cv2 = cv2
        self.capture = cv2.VideoCapture(camera_index, cv2.CAP_V4L2)
        self.capture.set(cv2.CAP_PROP_FRAME_WIDTH, frame_width)
        self.capture.set(cv2.CAP_PROP_FRAME_HEIGHT, frame_height)
        if not self.capture.isOpened():
            raise RuntimeError(f"CSI camera open failed: index={camera_index}")
        self.yolo_model_path = yolo_model_path

    def read(self) -> VisionResult:
        ok, frame = self.capture.read()
        if not ok or frame is None:
            return VisionResult(label=None)
        if self.yolo_model_path:
            return self._read_with_yolo_placeholder(frame)
        return self._read_by_simple_contour(frame)

    def _read_by_simple_contour(self, frame) -> VisionResult:
        gray = self.cv2.cvtColor(frame, self.cv2.COLOR_BGR2GRAY)
        blur = self.cv2.GaussianBlur(gray, (5, 5), 0)
        _, thresh = self.cv2.threshold(blur, 0, 255, self.cv2.THRESH_BINARY + self.cv2.THRESH_OTSU)
        contours, _ = self.cv2.findContours(thresh, self.cv2.RETR_EXTERNAL, self.cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return VisionResult(label=None)
        contour = max(contours, key=self.cv2.contourArea)
        area = self.cv2.contourArea(contour)
        if area < 100:
            return VisionResult(label=None)
        x, y, w, h = self.cv2.boundingRect(contour)
        return VisionResult(label="object", confidence=None, x_center=x + w // 2, y_center=y + h // 2, width=w, height=h)

    def _read_with_yolo_placeholder(self, frame) -> VisionResult:
        # YOLO 모델 연결 위치. ultralytics YOLO를 설치한 뒤 여기서 추론 결과를 VisionResult로 바꾸면 된다.
        return self._read_by_simple_contour(frame)

    def close(self) -> None:
        self.capture.release()

def create_vision_source(mode: str, camera_index: int, frame_width: int, frame_height: int, yolo_model_path: str) -> VisionSource:
    if mode.lower() == "mock":
        return MockVisionSource()
    return CsiCameraVisionSource(camera_index, frame_width, frame_height, yolo_model_path)
