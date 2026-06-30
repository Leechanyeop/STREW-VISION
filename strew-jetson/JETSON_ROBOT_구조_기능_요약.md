# JETSON_ROBOT 구조와 기능 요약

대상 폴더: `J:\STREW_VISION\STREW_VISION_system_architecture\JETSON_ROBOT`

## 1. 이 폴더는 무엇인가?

`JETSON_ROBOT`은 Jetson 보드에서 돌아가는 로봇 프로그램 모음이다.

쉽게 말하면, Jetson이 로봇의 "중간 두뇌" 역할을 한다.

서버에서 "무엇을 하라"는 작업을 받아오고, 카메라로 주변 물체를 확인한 다음, 아두이노에게 실제 움직임 명령을 보낸다. 아두이노가 처리한 결과는 다시 서버로 보고한다.

전체 흐름은 다음과 같다.

```text
AWS/API 서버
  -> Jetson 로봇 에이전트
  -> 카메라로 물체 확인
  -> Arduino에 이동/작업 명령 전달
  -> Arduino 응답 수신
  -> 서버에 완료 결과 보고
```

## 2. 최상위 폴더 구조

```text
JETSON_ROBOT
├─ strew_robot/        로봇 에이전트의 핵심 Python 코드
├─ systemd/            Jetson 부팅 시 자동 실행하기 위한 서비스 설정
├─ scripts/            실행 스크립트
├─ runs/               YOLO 학습 결과와 카메라 테스트 자료
├─ JETSON/             HuskyLens 테스트, 카메라 드라이버 관련 자료
├─ requirements.txt    Python 필수 라이브러리 목록
└─ .env.example        환경변수 예시 파일
```

## 3. 핵심 코드: `strew_robot`

`strew_robot` 폴더가 실제 로봇 에이전트의 중심이다.

### `main.py`

프로그램 시작점이다.

`Config`로 설정을 읽고, `RobotAgent`를 만든 다음 계속 실행한다.

```text
main.py
  -> Config 읽기
  -> RobotAgent 생성
  -> run_forever() 실행
```

### `config.py`

환경 설정을 담당한다.

`.env` 파일이나 시스템 환경변수에서 값을 읽는다.

중요한 설정은 다음과 같다.

| 설정 | 의미 |
|---|---|
| `ROBOT_ID` | 서버에서 구분하는 로봇 이름 |
| `AWS_API_BASE` | 작업을 받아올 서버 주소 |
| `API_KEY` | 서버 인증 키 |
| `ARDUINO_PORT` | 아두이노가 연결된 포트 |
| `ARDUINO_BAUDRATE` | 시리얼 통신 속도 |
| `POLL_INTERVAL_SEC` | 서버에 작업을 물어보는 간격 |
| `VISION_MODE` | 카메라 모드, 기본값은 `csi` |
| `FRAME_WIDTH`, `FRAME_HEIGHT` | 카메라 영상 크기 |
| `YOLO_MODEL_PATH` | YOLO 모델 파일 경로 |

### `agent.py`

로봇의 전체 행동 순서를 관리하는 파일이다.

가장 중요한 클래스는 `RobotAgent`이다.

`run_once()`의 동작 순서는 다음과 같다.

1. 서버에 다음 작업이 있는지 물어본다.
2. 작업이 없으면 아무것도 하지 않는다.
3. 작업이 있으면 카메라로 현재 물체 정보를 읽는다.
4. 읽은 비전 정보를 서버에 보낸다.
5. 작업 정보와 비전 정보를 합쳐 아두이노 명령을 만든다.
6. 아두이노에 JSON 한 줄로 명령을 보낸다.
7. 아두이노 응답을 서버에 완료 결과로 보고한다.

즉, `agent.py`는 서버, 카메라, 아두이노를 연결하는 교통정리 담당이다.

### `cloud_client.py`

AWS/API 서버와 HTTP 통신을 담당한다.

주요 기능은 세 가지다.

| 함수 | 역할 |
|---|---|
| `next_task()` | 서버에서 로봇이 해야 할 다음 작업을 가져온다 |
| `post_vision_event()` | 카메라가 본 물체 정보를 서버에 보낸다 |
| `post_response()` | 작업 완료 결과를 서버에 보낸다 |

서버 주소는 `AWS_API_BASE` 설정을 사용하고, 요청 헤더에는 `X-API-Key`를 넣는다.

### `arduino_link.py`

Jetson과 Arduino 사이의 시리얼 통신을 담당한다.

Jetson은 아두이노에게 JSON 형태의 명령을 한 줄로 보낸다.

예시 형태:

```json
{
  "task_id": "task-001",
  "execute_task": "MOVE",
  "move_sign": "FORWARD",
  "target_label": "RED",
  "detected_label": "RED",
  "x_center": 640,
  "y_center": 360
}
```

아두이노가 응답을 보내면 JSON으로 해석하고, JSON이 아니면 원문 문자열로 저장한다.

### `vision_source.py`

카메라와 물체 인식을 담당한다.

현재 두 가지 모드가 있다.

| 모드 | 설명 |
|---|---|
| `mock` | 실제 카메라 없이 가짜 물체 데이터를 돌려준다 |
| `csi` | Jetson CSI 카메라를 열어서 실제 영상을 읽는다 |

현재 YOLO 모델 경로가 있으면 `_read_with_yolo_placeholder()`로 들어가지만, 실제 YOLO 추론 코드는 아직 완성되어 있지 않다. 지금은 임시로 단순 윤곽선 방식으로 물체 위치를 찾는다.

단순 윤곽선 방식은 영상을 흑백으로 바꾸고, 가장 큰 덩어리를 찾아서 물체 위치처럼 사용한다. 그래서 정확한 딥러닝 객체 인식이라기보다는 기본 테스트용에 가깝다.

### `models.py`

서로 주고받는 데이터 모양을 정리한 파일이다.

| 데이터 클래스 | 의미 |
|---|---|
| `VisionResult` | 카메라 인식 결과 |
| `ArduinoCommand` | 아두이노로 보낼 명령 |

`VisionResult`에는 라벨, 신뢰도, 중심 좌표, 박스 크기가 들어간다.

`ArduinoCommand`에는 작업 ID, 실행할 작업, 이동 신호, 목표 라벨, 감지 라벨, 좌표가 들어간다.

## 4. 실행 관련 파일

### `requirements.txt`

필요한 Python 라이브러리 목록이다.

```text
requests       서버와 HTTP 통신
pyserial       Arduino/HuskyLens와 시리얼 통신
python-dotenv  .env 설정 파일 읽기
```

단, 카메라 코드에서는 `cv2`를 사용하므로 실제 CSI 카메라 기능을 쓰려면 OpenCV도 설치되어 있어야 한다.

### `.env.example`

환경 설정 예시 파일이다.

실제 실행할 때는 이 파일을 참고해서 `.env`를 만들고 서버 주소, API 키, 아두이노 포트 등을 맞춰야 한다.

### `scripts/run_agent.sh`

Linux/Jetson에서 로봇 에이전트를 실행하는 스크립트다.

하는 일은 다음과 같다.

1. 프로젝트 폴더로 이동한다.
2. Python 가상환경 `.venv`를 만든다.
3. 필요한 라이브러리를 설치한다.
4. `python -m strew_robot.main`으로 에이전트를 실행한다.

### `systemd/strew-robot-agent.service`

Jetson을 켰을 때 로봇 에이전트가 자동 실행되도록 하는 systemd 서비스 파일이다.

서비스가 꺼지면 `Restart=always` 설정 때문에 3초 뒤 다시 시작한다.

## 5. `runs` 폴더

`runs` 폴더는 YOLO 객체 인식 학습 결과와 테스트 코드가 들어 있다.

### `runs/detect/train-12`

YOLOv8n 모델을 50 epoch 학습한 결과 폴더다.

중요한 파일은 다음과 같다.

| 파일 | 의미 |
|---|---|
| `weights/best.pt` | 가장 성능이 좋았던 모델 가중치 |
| `weights/last.pt` | 마지막 epoch의 모델 가중치 |
| `args.yaml` | 학습할 때 사용한 설정 |
| `results.csv` | epoch별 성능 기록 |
| `results.png` | 학습 성능 그래프 |
| `confusion_matrix.png` | 어떤 클래스를 헷갈렸는지 보는 표 |
| `train_batch*.jpg` | 학습 이미지 예시 |
| `val_batch*_pred.jpg` | 검증 이미지 예측 결과 |

학습 설정을 보면 `yolov8n.pt`를 기반으로 50 epoch 학습했다.

마지막 50번째 epoch 기준 주요 성능은 대략 다음과 같다.

| 지표 | 값 |
|---|---:|
| Precision | 0.773 |
| Recall | 0.626 |
| mAP50 | 0.701 |
| mAP50-95 | 0.536 |

쉽게 말하면, 모델이 어느 정도 물체를 찾기는 하지만 완벽하지는 않다. 실제 로봇에 쓰려면 조명, 각도, 배경이 바뀌어도 잘 찾는지 추가 테스트가 필요하다.

### `runs/detect/webcam_test.py`

웹캠으로 YOLO 모델을 테스트하는 코드다.

다만 파일 안의 모델 경로가 `K:\runs\detect\train-12\weights\best.pt`로 되어 있어서, 현재 프로젝트 폴더 안의 `best.pt`를 쓰려면 경로를 수정해야 한다.

또한 주석 일부가 글자 깨짐 상태라서 나중에 정리하는 것이 좋다.

## 6. `JETSON` 폴더

이 폴더는 Jetson에서 카메라나 외부 센서를 테스트하기 위한 자료가 들어 있다.

### `huskylens_color_labels.py`

HuskyLens 센서에서 색상 인식 결과를 읽는 Python 코드다.

색상 ID를 다음처럼 라벨로 바꾼다.

| ID | 색상 |
|---:|---|
| 1 | RED |
| 2 | ORANGE |
| 3 | YELLOW |
| 4 | GREEN |
| 5 | BLUE |
| 6 | PURPLE |

HuskyLens가 여러 색상 블록을 찾으면, 면적이 가장 큰 블록을 대표 색상으로 선택한다.

### `imx708-v4l2-driver-4lane_dkms`

카메라 센서 드라이버 관련 자료다.

폴더 이름은 IMX708 드라이버처럼 보이지만, README 내용은 IMX585를 설명하고 있다. 이름과 문서 내용이 맞지 않으므로 실제 사용 전 확인이 필요하다.

이 폴더 안에는 커널 드라이버 소스, DKMS 설정, 설치 스크립트, 디바이스 트리 오버레이 파일 등이 있다.

## 7. 전체 동작을 고등학생 눈높이로 설명

이 시스템을 학교 방송부에 비유하면 이해하기 쉽다.

서버는 방송실 선생님이다. 선생님은 "로봇 1번, 앞으로 가서 빨간 물체를 확인해" 같은 지시를 내린다.

Jetson은 반장이다. 선생님 말을 듣고, 카메라로 앞을 보고, 실제로 모터를 움직이는 친구인 아두이노에게 명령을 전달한다.

Arduino는 행동 담당이다. 모터나 그리퍼 같은 실제 장치를 움직인다.

카메라는 눈이다. 물체가 어디 있는지, 어떤 색인지, 화면 중앙에서 얼마나 떨어졌는지를 알려준다.

마지막으로 Jetson은 "작업 끝났습니다" 또는 "이런 결과가 나왔습니다"라고 다시 서버에 보고한다.

## 8. 현재 구조에서 보이는 주의점

1. `vision_source.py`의 YOLO 연결은 아직 placeholder 상태다. `YOLO_MODEL_PATH`를 넣어도 실제 YOLO 추론을 하지 않고 단순 윤곽선 방식으로 처리한다.
2. `requirements.txt`에는 `opencv-python`이나 `ultralytics`가 없다. CSI 카메라나 YOLO 테스트를 하려면 추가 설치가 필요할 수 있다.
3. `webcam_test.py`의 모델 경로가 현재 폴더 기준이 아니라 `K:\...`로 되어 있다.
4. `webcam_test.py` 주석 일부가 인코딩 문제로 깨져 있다.
5. `imx708-v4l2-driver-4lane_dkms` 폴더명과 README의 IMX585 설명이 서로 다르다.
6. 서버 API가 살아 있어야 `CloudClient`가 정상 동작한다.
7. Arduino가 지정된 포트에 연결되어 있어야 `ArduinoLink`가 정상 동작한다.

## 9. 한 줄 요약

`JETSON_ROBOT`은 Jetson이 서버, 카메라, Arduino 사이에서 명령을 받아 실행하고 결과를 보고하게 만드는 로봇 제어 에이전트이며, YOLO 학습 결과와 카메라/센서 테스트 자료도 함께 포함된 폴더다.
