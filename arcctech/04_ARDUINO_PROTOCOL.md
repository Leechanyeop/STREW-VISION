# Jetson Nano와 Arduino Mega 통신 규칙

## 통신 방식

- USB 시리얼
- 기본 속도: 115200 baud
- 데이터 형식: JSON 한 줄
- 한 명령은 반드시 줄바꿈 `\n`으로 끝난다.

## Jetson에서 Arduino로 보내는 명령

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

## Arduino에서 Jetson으로 보내는 응답

```json
{
  "completion_sign": "DONE",
  "message": "task accepted"
}
```

## completion_sign 의미

- `DONE`: 명령 처리 완료
- `FAILED`: 명령 처리 실패
- `RUNNING`: 아직 동작 중

## 쉽게 이해하기

Jetson은 카메라를 보고 판단하는 두뇌 역할이다. Arduino는 모터와 그리퍼를 직접 움직이는 손발 역할이다. Jetson이 “앞으로 가라” 또는 “이 위치의 물체를 잡아라” 같은 명령을 JSON으로 보내면, Arduino는 그 명령을 읽고 실제 핀과 모터를 제어한다.
