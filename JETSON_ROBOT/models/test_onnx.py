import cv2
import time
from ultralytics import YOLO

# ONNX 모델 로드 (GPU 사용)
model = YOLO("best.onnx")

cap = cv2.VideoCapture(0)

if not cap.isOpened():
    print("카메라를 열 수 없습니다.")
    exit()

while True:
    ret, frame = cap.read()

    if not ret:
        break

    start = time.time()

    results = model.predict(
        source=frame,
        imgsz=640,
        verbose=False,
        device=0
    )

    fps = 1 / (time.time() - start)

    annotated = results[0].plot()

    cv2.putText(
        annotated,
        f"FPS : {fps:.2f}",
        (20, 40),
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        (0, 255, 0),
        2
    )

    cv2.imshow("STREW_VISION ONNX", annotated)

    if cv2.waitKey(1) & 0xFF == ord("q"):
        break

cap.release()
cv2.destroyAllWindows()