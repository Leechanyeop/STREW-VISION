# 데이터 흐름도 설명

## 1. 작업 요청 생성

웹 대시보드가 AWS 서버의 `/robot/request` API로 작업을 만든다.

```json
{
  "robot_id": "robot-01",
  "execute_task": "PICK_BY_VISION",
  "move_sign": "FORWARD",
  "target_label": "box"
}
```

## 2. Jetson Nano가 작업 수신

Jetson Nano 프로그램은 `/robot/next?robot_id=robot-01`을 반복 호출한다. 대기 중인 작업이 있으면 하나를 가져오고, 서버는 작업 상태를 `sent`로 바꾼다.

## 3. CSI 웹캠으로 비전 결과 생성

Jetson Nano는 OpenCV로 CSI 카메라를 연다. 기본 구현은 가장 큰 윤곽선을 찾아 `object`라는 라벨과 중심 좌표를 만든다. 나중에 YOLO 모델을 붙이면 `box`, `plant`, `target` 같은 더 정확한 라벨로 바꿀 수 있다.

```json
{
  "label": "object",
  "confidence": null,
  "x_center": 640,
  "y_center": 360,
  "width": 160,
  "height": 120
}
```

## 4. Jetson Nano가 Arduino Mega로 전송

Jetson Nano는 작업과 비전 결과를 합쳐 시리얼 포트로 JSON 한 줄을 보낸다.

```json
{
  "task_id": "작업ID",
  "execute_task": "PICK_BY_VISION",
  "move_sign": "FORWARD",
  "target_label": "box",
  "detected_label": "object",
  "x_center": 640,
  "y_center": 360
}
```

## 5. Arduino Mega가 응답

Arduino Mega는 명령을 처리하고 결과를 JSON으로 돌려준다.

```json
{
  "completion_sign": "DONE",
  "message": "task accepted"
}
```

## 6. AWS 서버에 결과 저장

Jetson Nano는 `/robot/response`로 결과를 올린다. `DONE`이면 작업 상태가 `done`, `FAILED`이면 `failed`, 그 외는 `running`이 된다.
