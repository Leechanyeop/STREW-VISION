# JETSON_ROBOT 구조와 기능 요약 (v2)

대상 폴더: `C:\STREW_VISION\JETSON_ROBOT`

> 이 문서는 전체 디렉터리를 다시 전수조사해서 갱신한 버전이다. HuskyLens 관련 내용은 더 이상 사용하지 않으므로 모두 제외했다. 대신 "지금 학습된 모델이 YOLOv8인데 실제 Jetson Nano에 들어갈 것은 YOLOv5"라는 버전 불일치 문제를 핵심으로 다룬다.
>
> **[재검토 갱신]** 직전 버전 작성 이후 실제 폴더에서 다음이 삭제된 것을 확인했다: `strew_robot/`(레거시 코드) 전체, `runs/` 내부 학습 산출물 전체, `JETSON/` 폴더 전체(IMX708 드라이버 자료 포함), `scripts/` 폴더 전체. 이 변화를 반영해 2, 3, 6, 7, 8, 9, 12, 13절을 다시 정리했다.

## 1. 이 폴더는 무엇인가?

`JETSON_ROBOT`은 Jetson 보드에서 돌아가는 로봇 프로그램 모음이다.

서버(AWS)에서 작업(Task)을 받아오고, 카메라로 주변 물체를 확인한 다음, 아두이노에게 실제 움직임 명령을 보낸다. 아두이노가 처리한 결과는 다시 서버로 보고한다.

```text
AWS/API 서버
  -> Jetson 로봇 에이전트
  -> 카메라로 물체 확인 (현재는 AI 없이 윤곽선 방식)
  -> Arduino에 이동/작업 명령 전달
  -> Arduino 응답 수신
  -> 서버에 완료 결과 보고
```

## 2. 최상위 폴더 구조 (실제 확인 기준)

```text
JETSON_ROBOT
├─ ai/                 새 비전 처리 모듈 (대부분 빈 스텁)
│   ├─ detector/        카메라·추론 관련 파일 10개
│   ├─ qr/              QR 인식용 폴더 (현재 비어 있음)
│   ├─ segmentation/    분할(segmentation)용 폴더 (비어 있음)
│   └─ tracker/         추적(tracker)용 폴더 (비어 있음)
├─ robot/              로봇 제어 로직 (실제 진입점이 사용하는 곳)
├─ cloud/              AWS 서버 통신
├─ config/             설정 (환경변수, 로깅)
├─ models/             배포용 모델 가중치(best.pt) + 설정 — ⚠ 이 학습 결과의 유일한 best.pt 사본
├─ runs/               (현재 비어 있음 — 학습 원본 산출물이 삭제됨)
├─ systemd/            Jetson 부팅 시 자동 실행 서비스 설정
├─ tests/              단위 테스트 + 학습 산출물 사본(last.pt만 있음, best.pt 없음)
├─ README.md           목표 아키텍처 설명 (현재 구조보다 더 세분화된 목표치)
├─ JETSON_AWS_MEGA_INTEGRATION_PLAN.md  AWS-Jetson-Arduino 역할 분담 계획
├─ requirements.txt    Python 라이브러리 목록
└─ .env.example        환경변수 예시 파일
```

> `strew_robot/`(레거시 코드), `scripts/`(실행 스크립트), `JETSON/`(카메라 드라이버 자료) 폴더는 재검토 시점에 이미 삭제되어 더 이상 존재하지 않는다. 아래 3, 6, 8, 9절에 반영했다.

## 3. 중요 발견 — 레거시 구현체는 이미 정리 완료됨

직전 조사 시점에는 로봇 에이전트가 **레거시 버전(`strew_robot/`)과 신규 버전 두 개**로 나뉘어 있었으나, 재검토 시점에 `strew_robot/` 폴더 전체가 삭제된 것을 확인했다. 즉 이전 문서의 "정리 필요" 지적 사항 중 하나는 이미 반영된 상태다.

| 구분 | 위치 | 현재 상태 |
|---|---|---|
| 신규(현재 사용, 유일한 구현체) | 최상위 `main.py` → `config/settings.py` + `robot/state_machine.py`(`RobotAgent`) + `ai/detector/camera.py` + `robot/uart.py` + `cloud/api_client.py` | 실제 진입점, `tests/`도 이 구조를 대상으로 작성됨 |
| 레거시 | `strew_robot/` | **삭제됨** (더 이상 존재하지 않음) |

다만 `tests/artifacts/legacy-strew_robot/__init__.py`라는 빈 잔재 파일 하나가 아직 남아 있다 — 내용이 없는 빈 파일이라 실행에는 영향이 없지만, 폴더명 자체가 삭제된 레거시를 가리키고 있으므로 같이 정리하는 게 깔끔하다.

## 4. 신규 구조 상세

### `robot/state_machine.py` — `RobotAgent` (실제 진입점)

```text
run_once()
  1. cloud.next_task() 로 AWS에서 작업 조회
  2. 작업 없으면 종료
  3. vision.read() 로 카메라 읽기 (현재는 AI 없이 윤곽선 방식)
  4. cloud.post_vision_event() 로 비전 결과 보고
  5. build_command() 로 ArduinoCommand 생성
  6. arduino.send_json_line() 으로 UART 전송
  7. cloud.post_response() 로 완료 결과 보고
```

### `robot/` 나머지 파일

| 파일 | 상태 | 설명 |
|---|---|---|
| `command.py` | 구현됨 | `ArduinoCommand` 데이터클래스 |
| `uart.py` | 구현됨 | `pyserial` 기반 실제 시리얼 송수신 |
| `packet.py` | 구현됨 | JSON 한 줄 패킷 인코딩 |
| `protocol.py` | 구현됨 | `DONE/FAILED/RUNNING` 상수만 정의 |
| `task_manager.py` | 최소 구현 | `TaskQueue`는 단순 FIFO 리스트 (우선순위·중복방지 없음) |
| `planner.py` | 최소 구현 | task와 vision을 딕셔너리로 합치기만 함 |
| `motion.py` | **완전 빈 파일** | 모터/그리퍼 등 실제 동작 로직 없음 |

### `cloud/` — AWS 통신

| 파일 | 상태 | 설명 |
|---|---|---|
| `api_client.py` | 구현됨 | `next_task`, `post_response`, `post_vision_event` 3개 REST 호출 |
| `mqtt.py` | 스텁 | `connect()` 호출 시 `NotImplementedError` |
| `sync.py` | **완전 빈 파일** | 오프라인 동기화 로직 없음 |

### `ai/detector/` — 비전 처리 (대부분 통과용 스텁)

| 파일 | 줄 수 | 상태 |
|---|---:|---|
| `camera.py` | 96줄 | 유일하게 실구현. CSI 카메라 오픈 + OpenCV 윤곽선 검출 (`_read_by_simple_contour`) |
| `detector.py`, `capture.py` | 3줄 | `camera.py`의 `create_vision_source`를 그대로 재노출만 함 |
| `engine.py` | 3줄 | `AiEngine.run()`이 `NotImplementedError` — 추론 엔진 자체가 없음 |
| `inference.py` | 2줄 | `engine.run(frame)`을 그대로 호출하는 래퍼뿐 |
| `parser.py`, `preprocess.py` | 2줄 | 입력을 그대로 반환 (통과용) |
| `validator.py` | 2줄 | `label`이 있는지만 확인 |
| `calibration.py` | 2줄 | 캘리브레이션 로직 없이 값만 반환 |
| `json_builder.py` | 2줄 | 딕셔너리 병합만 함 |
| `result.py` | 15줄 | `VisionResult` 데이터클래스 |

결론: `ai/detector/` 폴더는 이름과 달리 **실제 AI 추론이 전혀 연결되어 있지 않다.** `camera.py`의 `_read_with_yolo_placeholder()`도 내부적으로 결국 단순 윤곽선 방식(`_read_by_simple_contour`)을 호출한다. YOLO 모델 경로(`yolo_model_path`)는 함수에 전달만 될 뿐 실제로 로드되거나 추론에 쓰이지 않는다.

### `ai/qr/`, `ai/segmentation/`, `ai/tracker/`

세 폴더 모두 `__init__.py`만 있고 내용은 비어 있다. (이전 문서에 있던 HuskyLens 기반 색상 인식 코드는 이번 버전에서 제외했다 — 더 이상 필요 없다는 방향에 맞춰 문서에서도 삭제.)

## 5. YOLO 모델 — v8/v5 불일치 문제 (핵심)

이 부분이 지금 가장 중요하게 짚어야 할 이슈다.

| 항목 | 실제 확인 내용 |
|---|---|
| 학습 결과 | `runs/detect/train-12/` — `args.yaml`에 `model: yolov8n.pt` 로 명시. Ultralytics YOLOv8n 기반 50 epoch 학습 |
| 배포 지정 모델 | `models/best.pt` — `runs/detect/train-12/weights/best.pt`와 **완전히 동일한 파일**(MD5 일치). 즉 학습된 v8 가중치를 그대로 배포용으로 복사해 둔 상태 |
| 설정 기본값 | `config/settings.py`의 `YOLO_MODEL_PATH` 기본값이 `"models/best.pt"` → 지금 시스템은 v8 가중치를 가리키고 있음 |
| 라이브러리 | `requirements.txt`에 `ultralytics>=8.3.0` 명시 — 이건 YOLOv8/v11 계열 전용 패키지이며 YOLOv5(`yolov5` 리포지토리, `torch.hub` 방식)와는 별개 |
| 실제 추론 | 위 4절에서 확인했듯 `ai/detector/engine.py`가 `NotImplementedError`라서 **v8 모델이든 뭐든 아직 아무것도 로드/추론되지 않고 있음** |

정리하면 다음과 같다.

- 지금 당장은 추론 자체가 연결 안 되어 있어서 v8/v5 문제가 실행 오류로 나타나지는 않는다.
- 하지만 나중에 `ai/detector/engine.py`를 실제로 구현해서 `models/best.pt`를 로드하는 순간, 그 가중치는 **YOLOv8n**이다.
- 최종적으로 Jetson Nano에 올릴 모델은 **YOLOv5**로 가야 한다는 게 방향이므로, 지금 있는 `runs/detect/train-12`와 `models/best.pt`는 이 목적에 그대로 쓸 수 없다. Jetson Nano(구형 JetPack/CUDA 환경)에서는 최신 `ultralytics`(YOLOv8) 패키지가 요구하는 PyTorch/CUDA 버전을 맞추기 까다로운 반면, YOLOv5는 구형 Jetson Nano 환경에서 검증된 사례가 많아 상대적으로 돌리기 쉽다.
- 따라서 실제 배포 전에는 **YOLOv5로 재학습(또는 최소한 변환/재검증)** 이 필요하며, `config/settings.py`의 `YOLO_MODEL_PATH`, `requirements.txt`의 `ultralytics` 의존성, `models/config.yaml`도 함께 정리해야 한다.
- `models/labels.yaml`은 `names: []`로 비어 있어 클래스 라벨조차 채워지지 않은 상태다.

**[재검토 추가]** `runs/detect/train-12`(학습 원본)가 삭제되면서 **`models/best.pt`가 이 학습의 유일하게 남은 best-weight 사본**이 됐다. `tests/artifacts/yolo-train-12`에는 `last.pt`만 있고 `best.pt`는 원래부터 없었다. 즉 지금 `models/best.pt`를 잘못 지우면 이 YOLOv8n 학습 결과 자체를 되살릴 방법이 없다 — v5로 다시 학습할 계획이라도, 그 전까지는 백업을 하나 더 떠 두는 게 안전하다.

또한 `tests/manual/webcam_test.py`(실제 남아있는 유일한 웹캠 테스트 스크립트)는 이전 버전 문서가 지적했던 `K:\...` 하드코딩 경로 문제가 더 이상 없다. 지금은 `Path(__file__).resolve().parents[2] / "models" / "best.pt"`로 상대경로를 쓰고, `ultralytics.YOLO`로 실제 추론까지 돌리는 완결된 스크립트로 바뀌어 있다. 다만 이건 독립 실행 스크립트일 뿐이고, 로봇 에이전트의 실제 파이프라인(`ai/detector/engine.py`)에는 여전히 연결되어 있지 않다.

## 6. 레거시 구조: `strew_robot/` — 삭제 완료 확인

이전 문서가 설명하던 레거시 로봇 에이전트(`main.py`, `agent.py`, `config.py`, `cloud_client.py`, `arduino_link.py`, `vision_source.py`, `models.py`)는 재검토 시점에 폴더째 삭제되어 더 이상 존재하지 않는다. 정리가 이미 끝난 것으로 확인했다.

## 7. `runs/` 및 `tests/artifacts/` — YOLO 학습 산출물 (원본 삭제됨)

`runs/detect/train-12/`(학습 원본 폴더)가 삭제되어 `runs/`는 현재 완전히 비어 있다. 남은 건 `tests/artifacts/yolo-train-12/`뿐이고, 여기엔 `last.pt`만 있고 `best.pt`는 없다 (5절에서 설명했듯 `models/best.pt`가 이 학습의 유일한 best-weight 사본이 된 상태).

마지막 50 epoch 기준 성능(YOLOv8n 기준, `tests/artifacts/yolo-train-12/results.csv` 근거):

| 지표 | 값 |
|---|---:|
| Precision | 0.773 |
| Recall | 0.626 |
| mAP50 | 0.701 |
| mAP50-95 | 0.536 |

과거 `runs/detect/webcam_test.py` 사본은 폴더째 삭제되어 없어졌고, 남아있는 `tests/manual/webcam_test.py`는 하드코딩 경로 문제가 이미 해결된 상태다(5절 참고).

## 8. `JETSON/` 폴더 — 삭제 완료 확인 (IMX708 드라이버 자료 포함)

이전 문서가 설명하던 `imx708-v4l2-driver-4lane_dkms/`(카메라 드라이버 소스, DKMS 설정 등)를 포함해 `JETSON/` 폴더 전체가 삭제되어 더 이상 존재하지 않는다. HuskyLens 관련 코드도 이 폴더 안에 있었으므로 자연히 함께 제거됐다.

⚠ 다만 이건 "필요 없는 것만 골라서 정리됨"이 아니라 **폴더 전체가 사라진 것**이다. IMX708(혹은 실제로는 README가 설명하던 IMX585) 카메라 드라이버가 나중에 실제로 필요하다면, 이 자료를 다시 구해서 받아와야 한다는 뜻이다. 지금 남은 카메라 관련 코드는 `ai/detector/camera.py`의 OpenCV `cv2.VideoCapture` 호출뿐이고, 드라이버 설치 자료는 없다.

## 9. 설정/실행 파일

| 파일 | 설명 |
|---|---|
| `config/settings.py` | `.env` 기반 `Config` dataclass. `ROBOT_ID`, `AWS_API_BASE`, `API_KEY`, `ARDUINO_PORT`, `POLL_INTERVAL_SEC`, `VISION_MODE`, `YOLO_MODEL_PATH` 등 |
| `config/logging.conf` | 로깅 설정 |
| `config/uart.yaml` | **빈 파일** |
| `requirements.txt` | `requests`, `pyserial`, `python-dotenv`, `ultralytics`, `opencv-python`, `numpy`, `pillow`, `scipy`, `pandas`, `matplotlib`, `pyzbar`, `paho-mqtt`, `boto3`, `fastapi`, `uvicorn`, `segmentation-models-pytorch`, `albumentations` 등 — 목록은 방대하지만 실제로 코드에서 쓰이는 건 앞의 3~4개뿐이고 나머지는 아직 연결 안 된 기능(YOLO, MQTT, 세그멘테이션 등)을 위해 미리 적어둔 상태로 보임 |
| `scripts/run_agent.sh` | **삭제됨.** Jetson에서 에이전트를 실행할 표준 스크립트가 현재 없음 — `systemd` 서비스만으로 실행하거나 스크립트를 다시 만들어야 함 |
| `systemd/strew-robot-agent.service` | 부팅 시 자동 실행, `Restart=always`. `ExecStart`가 이미 `python -m main`으로 되어 있어 신규 구조와 정합됨(레거시 경로 아님, 문제 없음). 단 `WorkingDirectory`가 `/home/jetson/STREW_VISION/strew-jetson`으로 되어 있어 실제 Jetson 배포 경로와 일치하는지는 배포 시 확인 필요 |

## 10. `tests/` — 신규 구조 기준으로 작성됨

| 파일 | 대상 |
|---|---|
| `test_camera.py` | `ai.detector.camera.MockVisionSource` |
| `test_decision.py` | `robot.planner.plan_task` |
| `test_detection.py` | `ai.detector.validator.is_valid_detection` |
| `test_robot.py` | `robot.packet.encode_packet` |
| `test_task.py` | `robot.task_manager.TaskQueue` |

5개 테스트 모두 `strew_robot/`이 아닌 `ai/`, `robot/` 신규 구조를 대상으로 작성되어 있다. 이 점이 신규 구조가 "진짜" 활성 구현이라는 근거이기도 하다.

## 11. `README.md`가 제시하는 목표 구조와의 차이

`README.md`는 아래처럼 더 세분화된 목표 구조를 제시하지만, 실제로는 아직 여기까지 나뉘어 있지 않다.

| README가 제시하는 폴더 | 실제 상태 |
|---|---|
| `camera/` | 없음 — `ai/detector/camera.py`에 통합되어 있음 |
| `decision/` | 없음 — `robot/planner.py`(2줄)로만 존재 |
| `detection/` | 없음 — `ai/detector/result.py`, `validator.py`로 대체 |
| `mqtt/` | 없음 — `cloud/mqtt.py` 스텁 하나뿐 |
| `task/` | 없음 — `robot/task_manager.py`(19줄)로만 존재 |
| `utils/` | 없음 — 별도 유틸 폴더 없음 |

즉 README는 향후 리팩터링 방향(목표 아키텍처)이고, 지금 코드는 그 초기 단계다.

## 12. 정리 필요 사항 (Action Items) — 재검토 갱신판

이미 해결된 항목과 여전히 남아있는 항목을 구분했다.

### ✅ 이미 해결됨 (재검토 시점에 확인)

1. ~~레거시 제거~~: `strew_robot/` 폴더가 실제로 삭제됨. 다만 `tests/artifacts/legacy-strew_robot/__init__.py` 빈 잔재 파일 하나는 아직 남아있어 같이 지우면 됨.
2. ~~경로 하드코딩(webcam_test.py)~~: 남은 유일한 사본인 `tests/manual/webcam_test.py`는 `K:\...` 하드코딩이 아니라 상대경로로 이미 수정되어 있고, `ultralytics.YOLO`로 실제 추론까지 도는 완결된 스크립트로 바뀜.
3. ~~systemd 실행 경로 불일치~~: `systemd/strew-robot-agent.service`의 `ExecStart`는 이미 `python -m main`으로 신규 구조와 정합됨.

### ⚠ 새로 생긴 리스크 (기존 항목이 형태를 바꿔 재등장)

4. **모델 백업 없음 (구 "중복 산출물" 항목의 반전)**: `runs/detect/train-12` 원본이 삭제되면서 `models/best.pt`가 이 YOLOv8n 학습의 **유일한 best-weight 사본**이 됨. `tests/artifacts/yolo-train-12`엔 `last.pt`만 있음. `models/best.pt`를 잘못 지우면 이 학습 결과는 복구 불가 — 재학습(v5) 전까지 별도 백업 권장.
5. **카메라 드라이버 자료 소실 (구 "IMX708/IMX585 표기 불일치" 항목의 반전)**: `JETSON/imx708-v4l2-driver-4lane_dkms` 폴더 전체가 삭제되어, 표기 불일치를 확인할 대상 자체가 없어짐. IMX708(또는 IMX585) 드라이버가 실제로 필요한 시점에는 자료를 다시 구해야 함.
6. **실행 스크립트 없음**: `scripts/run_agent.sh`가 삭제되어 Jetson에서 에이전트를 수동 실행할 표준 스크립트가 없음. `systemd` 서비스로만 실행하거나 스크립트를 다시 작성해야 함.

### ▲ 여전히 유효한 항목 (변화 없음)

7. **YOLO 버전 정리 (최우선)**: `models/best.pt`, `tests/artifacts/yolo-train-12`는 모두 YOLOv8n(ultralytics) 산출물. Jetson Nano 배포 목표가 YOLOv5라면 그대로 못 쓰며, YOLOv5로 재학습하거나 최소 재검증이 필요. `requirements.txt`의 `ultralytics` 의존성도 재검토.
8. **추론 엔진 미구현**: `ai/detector/engine.py`가 여전히 `NotImplementedError` 상태. `tests/manual/webcam_test.py`가 독립 스크립트로는 YOLOv8 추론에 성공하고 있지만, 로봇 에이전트 본 파이프라인에는 아직 연결 안 됨 — 연결하는 시점에 반드시 v5/v8 문제를 먼저 해결해야 함.
9. **빈 파일 정리**: `robot/motion.py`, `cloud/sync.py`, `config/uart.yaml`은 여전히 내용이 전혀 없는 빈 파일.
10. **모델 메타데이터 미완성**: `models/labels.yaml`의 `names`가 여전히 빈 배열 — 클래스 라벨 정의 필요.

## 13. 한 줄 요약 (재검토 갱신판)

`JETSON_ROBOT`은 Jetson이 서버·카메라·Arduino 사이에서 명령을 받아 실행하고 결과를 보고하는 로봇 제어 에이전트다. 레거시 코드(`strew_robot/`)와 카메라 드라이버 자료(`JETSON/`), 학습 원본(`runs/`)은 이미 정리(삭제)된 상태고 실행 스크립트(`scripts/`)도 함께 사라졌다. 실제 활성 구현은 `ai/`+`robot/`+`cloud/`+`config/` 구조이며 AI 추론은 아직 로봇 파이프라인에 연결되지 않았고, 유일하게 남은 학습 가중치(`models/best.pt`)는 최종 목표(YOLOv5)와 다른 YOLOv8n이라 그대로는 Jetson Nano 배포에 쓸 수 없다 — 게다가 이제는 이 파일이 그 학습 결과의 마지막 사본이라 삭제 시 복구 불가라는 점도 새로 짚어야 한다.
