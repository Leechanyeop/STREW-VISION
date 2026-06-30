from pathlib import Path

import cv2
from ultralytics import YOLO


def main() -> None:
    model_path = Path(__file__).resolve().parents[2] / "models" / "best.pt"
    if not model_path.exists():
        print(f"model file not found: {model_path}")
        return

    model = YOLO(str(model_path))
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("camera open failed")
        return

    print("starting webcam detection. press q to quit.")
    while True:
        ok, frame = cap.read()
        if not ok:
            break

        annotated_frame = frame
        for result in model(frame, stream=True, conf=0.5, iou=0.45, imgsz=640):
            annotated_frame = result.plot()

        cv2.imshow("STREW Detection", annotated_frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
