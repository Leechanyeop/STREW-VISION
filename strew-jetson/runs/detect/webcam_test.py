import os
import cv2
from ultralytics import YOLO

def main():
    # 가장 최근에 '완벽하게 학습이 끝난' 폴더의 best.pt 경로를 지정하세요.
    model_path = r"K:\runs\detect\train-12\weights\best.pt"

    if not os.path.exists(model_path):
        print(f"❌ 모델 파일을 찾을 수 없습니다. 경로를 확인하세요: {model_path}")
        return

    model = YOLO(model_path) 

    # 카메라 연결
    cap = cv2.VideoCapture(0)
    if not cap.isOpened():
        print("❌ 카메라는 열 수 없습니다.")
        return

    print("정밀 인식을 시작합니다...")

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        # [인식률 향상 핵심 파트] 예측 옵션 튜닝
        results = model(
            frame, 
            stream=True, 
            conf=0.5,     # 1️⃣ 확신도 문턱을 0.5로 높여서 더 정확한 인식을 하도록 설정
            iou=0.45,      # 2️⃣ 박스가 겹칠 때 중복 박스를 깔끔하게 제거 (기본값 0.7에서 하향)
            imgsz=640      # 3️⃣ 입력 이미지 해상도 강제 (학습할 때 크기와 맞춰야 정확함)
        )

        annotated_frame = frame
        for r in results:
            annotated_frame = r.plot()

        cv2.imshow("Strawberry Leaf High-Accuracy Detection", annotated_frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == '__main__':
    main()