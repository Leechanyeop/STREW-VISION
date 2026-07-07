# JETSON_ROBOT 수정 구축 계획

기준 문서: Notion `Volume 01. JETSON NANO System Engineering Manual`
변경 사유: **지금 당장은 AI 추론(카메라/YOLO/TensorRT) 기능을 추가하지 않는다. 대신 AWS가 이미 계산해 둔 비전인식 결과만 받아서 쓴다.**

## 0. 핵심 결정

Notion 마스터플랜은 Jetson Nano에서 카메라부터 YOLO, TensorRT까지 온디바이스로 전부 구축하는 것(PHASE 2~6)을 전제로 한다. 이번 결정으로 그 전제가 바뀐다.

- 바뀌는 것: `VisionResult`의 출처가 "Jetson이 카메라로 직접 추론"에서 "AWS가 내려주는 결과를 그대로 수신"으로 바뀐다.
- 안 바뀌는 것: `VisionResult` 이후의 파이프라인(Decision Engine → Robot Command → UART → Arduino → 결과 보고)은 원래 계획 그대로 간다. Notion 문서가 강조하는 "모든 모듈은 교체 가능해야 한다"는 원칙과도 맞다 — 비전 공급자만 카메라에서 AWS로 교체하는 것.

**[추가 결정]** AWS 서버 구현(`strew-backend` 등)도 지금 당장은 하지 않는다. 즉 지금은 AI 추론도, AWS 연동도 둘 다 없는 상태다. 그렇다면 지금 실제로 만들 수 있는 건 "AWS/카메라 둘 다 없어도 돌아가는 부분", 즉 **Decision Engine + Robot Command + UART 구간을 Mock 입력으로 먼저 완성**하는 것이다. `VisionResult`와 Task 데이터를 실제로 어디서 받아오는지(AWS든 카메라든)는 인터페이스 뒤로 숨겨두고, 나중에 AWS가 준비되면 Mock을 실제 호출로 갈아끼우기만 하면 되도록 만든다.

## 1. PHASE별 대응표 (원래 계획 vs 지금 결정)

| PHASE | Notion 원래 계획 | 지금 결정 |
|---|---|---|
| PHASE 0 | 시스템 아키텍처 · 역할 분리 | 유지 (완료 상태 그대로) |
| PHASE 1 | Project Foundation (디렉터리 고정) | 유지, 단 `ai/` 하위 목표 구조는 축소 |
| PHASE 2 | AI Framework (Camera → Inference Engine → Vision Result) | **생략.** 대신 "AWS Vision Result Receiver"를 새로 정의 |
| PHASE 3 | AI Engine Interface (`VisionEngine.execute(frame)`) | **보류.** 인터페이스 설계 개념만 유지, 지금 구현하지 않음 |
| PHASE 4 | YOLO Engine (PyTorch/YOLO/Weights/Inference) | **보류** |
| PHASE 5 | TensorRT | **보류** |
| PHASE 6 | Vision Pipeline (CSI Camera→YOLO→QR→Tracking→Merge) | **보류** |
| PHASE 7 | Robot Integration (VisionResult→RobotAgent→Arduino→Cloud) | **부분 진행.** VisionResult·Task는 당분간 Mock으로 대체, Decision→Command→UART 구간만 먼저 완성 |
| PHASE 8 | Cloud (AWS/MQTT/Dashboard/History) | **[수정] 이것도 보류.** AWS 서버 구현 자체를 지금 하지 않기로 함 |
| PHASE 9 | Optimization (TensorRT/CUDA) | 보류 (PHASE 4~6과 함께 나중에) |
| PHASE 10 | Deployment (systemd 등) | 보류 — 배포할 AWS 연동이 없는 상태이므로 뒤로 미룸 |

## 2. 새 데이터 흐름

**원래 계획**
```
CSI Camera → YOLO Inference → VisionResult → Decision Engine → Robot Command
```

**지금 결정 (1차 — 지난 대화 시점)**
```
AWS (비전인식 결과 저장소) → REST 조회 → VisionResult → Decision Engine → Robot Command
```

**지금 결정 (2차 — AWS 구현도 보류)**
```
Mock Task + Mock VisionResult → Decision Engine → Robot Command → UART → Arduino
```

`VisionResult`·Task 객체 모두 이미 코드에 존재하는 형태를 그대로 쓴다(`ai/detector/result.py`의 `VisionResult`, `ai/detector/camera.py`의 `MockVisionSource`가 이미 Mock 데이터를 리턴하도록 구현되어 있음). 지금은 이 Mock 공급자를 그대로 두고 Decision Engine 이후 로직만 완성한다. AWS가 준비되면 Mock 대신 실제 REST 호출로 교체하는 것이 마지막 단계가 된다 — 즉 "공급자 교체 지점"이 AWS에서 Mock으로 한 단계 더 뒤로 밀린 것뿐, 구조 자체는 바뀌지 않는다.

## 3. 지금 당장 만들 것

1. `robot/planner.py`를 Chapter 05-4 Decision Engine 규칙표대로 실제 구현 (현재 2줄 통과용 스텁 상태) — **최우선, AWS/AI 없이도 바로 착수 가능**
2. `robot/state_machine.py`를 Mock Task + `MockVisionSource`(이미 있음) 기준으로 동작하도록 정리 — 카메라·AWS 호출 부분은 그대로 두되 당장 실제 연결은 안 함
3. `tests/test_decision.py`를 7절 Rule Table의 4가지 케이스(OBSERVE/REPLACE/NUTRITION/SKIP) 기준으로 확장
4. Mock 기반 End-to-End 로컬 테스트: Mock Task → Mock Vision → Decision Engine → Robot Command → (실제 Arduino 연결 시) UART 전송까지 확인

## 4. 지금 당장 안 만들 것 (보류)

- `ai/detector/engine.py` 실제 추론 구현
- YOLOv5/v8 재학습, TensorRT 변환 (지난 문서에서 지적한 v8/v5 불일치 문제는 이 보류로 자연스럽게 뒤로 미뤄짐)
- `ai/detector/camera.py`의 실카메라(CSI) 경로
- `ai/qr/`, `ai/segmentation/`, `ai/tracker/` 구현
- Notion `OPERATION 003`이 지시하는 `ai/engine`, `ai/models`, `ai/weights`, `ai/benchmark`, `ai/pipeline` 폴더 생성
- **[추가] AWS 서버 구현 전체** (`strew-backend` 등) — `cloud/api_client.py`에 새 함수를 추가하는 작업도 지금은 보류. 호출할 서버가 없으므로 지금 만들어도 검증 불가
- **[추가] `cloud/mqtt.py`, `cloud/sync.py`** — AWS 자체가 보류이므로 자연히 함께 보류

## 5. 코드 매핑 (기존 파일 → 이번 계획에서의 역할)

| 계획 요소 | 기존 파일 | 상태 |
|---|---|---|
| Task 조회 | `cloud/api_client.py`의 `next_task()` | 구현은 되어 있으나 **호출 보류** (AWS 없음) |
| 비전결과 조회 | `cloud/api_client.py` | **보류** — AWS 확정 전까지 착수 안 함 |
| Mock Task/Vision | `ai/detector/camera.py`의 `MockVisionSource` | 이미 있음 — 지금 단계의 실질적 입력 소스 |
| VisionResult 데이터 구조 | `ai/detector/result.py`의 `VisionResult` | 이미 있음 — 그대로 재사용 |
| Decision Engine | `robot/planner.py`의 `plan_task()` | 현재 2줄 스텁 → **Rule Table 실제 구현 필요 (최우선 작업)** |
| Robot Command | `robot/command.py`의 `ArduinoCommand` | 이미 구현됨 |
| UART 전송 | `robot/uart.py`의 `ArduinoLink` | 이미 구현됨 — Arduino 준비되면 바로 검증 가능 |
| 결과 보고 | `cloud/api_client.py`의 `post_response()` | 구현은 되어 있으나 **호출 보류** (AWS 없음) |
| 로봇 메인 루프 | `robot/state_machine.py`의 `RobotAgent.run_once()` | Mock 입력 기준으로 동작 확인, AWS/카메라 연결부는 나중으로 |

## 6. AWS 쪽 선행조건 — 전체 보류

`JETSON_AWS_MEGA_INTEGRATION_PLAN.md`(기존 문서)는 정반대 방향, 즉 "Jetson이 카메라/YOLO로 비전을 캡처해서 AWS에 `POST /vision/event`로 올린다"는 흐름을 전제로 쓰여 있다. 이번 결정과도 방향이 다르고, 애초에 AWS 구현 자체를 지금 하지 않기로 했으므로 **이 문서는 지금 갱신하지 않고 그대로 둔다.** AWS 쪽 작업을 실제로 시작하는 시점에 다시 꺼내서 정리한다.

지난 버전 문서에 있던 Open Question(AWS 엔드포인트 형식 A/B, 비전결과 생성 주체, task-vision 매칭 방식)들도 지금 결정할 필요가 없어졌다 — AWS 작업을 시작하는 시점에 다시 다룬다. 참고로 `strew-backend/main.py`는 여전히 빈 파일이라 어차피 지금은 호출할 서버 자체가 없다.

## 7. Decision Engine 규칙 (Chapter 05-4 그대로 재사용)

| Detection Status | Task | Robot Command |
|---|---|---|
| Healthy | OBSERVE | OBSERVE |
| Powdery Mildew | REPLACE | REPLACE |
| Missing Plant | REPLACE | REPLACE |
| Nutrition Needed | NUTRITION | NUTRITION |
| Empty Cell | NONE | SKIP |

## 8. 디렉터리 구조 (수정판 — Operation 003 대체)

Notion `OPERATION 003`의 `mkdir -p engine camera models weights benchmark configs utils pipeline`은 지금 실행하지 않는다. 대신 기존 구조를 그대로 활용한다.

```text
ai/
└─ detector/
   └─ result.py     ← VisionResult 데이터 모델만 재사용 (카메라 종속 코드는 미사용)
robot/
├─ planner.py        ← Decision Engine 규칙 구현 대상 (최우선)
├─ command.py        ← 이미 구현됨
├─ uart.py            ← 이미 구현됨
└─ state_machine.py  ← run_once() 수정 대상
cloud/
└─ api_client.py     ← 비전결과 조회 함수 추가 대상
```

`ai/engine/`, `ai/models/`, `ai/weights/`, `ai/benchmark/`, `ai/camera/`, `ai/pipeline/`은 PHASE 2~6을 재개하는 시점에 생성한다.

## 9. 구현 순서 제안 (AWS/AI 둘 다 보류 기준)

1. `robot/planner.py`를 7절 Rule Table대로 구현 (AWS/AI 없이 바로 착수 가능, 최우선)
2. `tests/test_decision.py`를 OBSERVE/REPLACE/NUTRITION/SKIP 4개 케이스로 확장해 Decision Engine 검증
3. `robot/state_machine.py`를 Mock Task + `MockVisionSource` 조합으로 돌려서 Decision Engine → Robot Command 연결 확인
4. Arduino 하드웨어가 준비되면 `robot/uart.py`로 실제 UART 송수신까지 연결해 End-to-End 로컬 테스트 (AWS 없이, `cloud.post_response()` 호출은 건너뛰거나 로그만 남기도록 임시 처리)
5. **(보류 해제 시점)** AWS 서버 구현 착수 → 6절 Open Question 재논의 → `cloud/api_client.py`에 비전결과 조회 함수 추가 → Mock을 실제 AWS 호출로 교체
6. **(보류 해제 시점)** 여유가 생기면 PHASE 2~6(AI Engine 온디바이스 구축) 재개

## 10. 요약

지금 단계에서는 AI 추론도 AWS 연동도 만들지 않는다. 대신 이미 있는 `MockVisionSource`를 입력으로 삼아 **Decision Engine(`robot/planner.py`) → Robot Command(`robot/command.py`) → UART(`robot/uart.py`)** 구간만 먼저 완성하고 검증한다. `VisionResult`·Task 인터페이스는 그대로 유지되므로, 나중에 AWS가 준비되면 Mock을 실제 호출로 교체하기만 하면 되고, 그 다음 PHASE 2~6(온디바이스 AI)을 붙일 때도 Decision Engine 이후 코드는 다시 손댈 필요가 없다.
