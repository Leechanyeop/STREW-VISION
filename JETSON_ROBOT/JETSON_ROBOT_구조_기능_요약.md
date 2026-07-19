# JETSON_ROBOT 구조와 기능 요약 (v5, 2026-07-15 4차 개정 반영)

대상 폴더: `C:\STREW_VISION\JETSON_ROBOT`

> 이전 버전(v4)은 아키텍처 전환의 1차 개정(결정권만 Mega로 이전, `ASSIGN_TARGET` 단일 셀 지정)까지만 반영되어 있었다. 그 사이 실시간으로 2~5차 개정이 추가로 진행되어: (2차) Mega가 작업 중 셀 번호+상태를 `PROGRESS_UPDATE`로 중계, (3차) 1~4번 셀 전체 순회 사이클 자체를 Mega가 관리(`START_CYCLE`/`CYCLE_COMPLETE`, IDLE/RUN/ERROR 최상위 상태), (4차) ERROR에 `severity` 필드 + `RESET` 복구 경로 + Jetson 측 무응답 워치독 + 시리얼 쓰기 Lock 추가, (5차) 물리 센서가 없어 severity 구분이 불가능하다는 게 확인되어 `severity`/`RESET`을 통째로 제거하고 "ERROR는 항상 물리 리셋"으로 단순화. 이번 버전은 이 전부를 반영한다.

## 1. 이 폴더는 무엇인가?

`JETSON_ROBOT`은 Jetson 보드에서 돌아가는 로봇 에이전트다.

```text
AWS/API 서버 (또는 mock)
  -> Jetson: RobotAgent.run_once() — task 받아서 Mega에 START_CYCLE(셀 지정 없이 "순회 시작해") 전송
             (이미 순회 중이면 다시 보내지 않음, cycle_active로 관리)
  -> Mega: IDLE -> RUN 전환, 1~4번 셀을 자체적으로 순회. 필요할 때마다 REQUEST_VISION으로 확인 요청
  -> Jetson: _uart_listener_loop() — vision.read()(현재 mock 또는 단순 컨투어, YOLO 미연결) 돌려서
             날것 status만 VISION_RESULT로 회신
  -> Mega: 그 status로 REPLACE/OBSERVE/SKIP 자체 판단 + 물리 동작 수행 (아직 미구현, TODO)
  -> Mega: 작업 중 PROGRESS_UPDATE(셀 번호+상태)를 수시로 중계 (응답 불필요, 정보성)
  -> Mega: 셀 하나 끝날 때마다 REPORT_RESULT (순회당 최대 4회)
  -> Jetson: 그 결과를 그대로 AWS에 post_response로 릴레이 (AWS_ENABLED일 때만)
  -> Mega: 4번 셀까지 다 돌고 초기 위치 복귀하면 CYCLE_COMPLETE 전송 -> IDLE 복귀
  -> (오류 시) Mega: ERROR(reason) 전송 -> 항상 물리 리셋(전원 재시작 등)으로만 복구
             (severity 구분/원격 RESET은 5차 개정에서 제거됨 - 물리 센서가 없어 구분 불가)
  -> (Mega가 아예 응답을 멈추면) Jetson: 120초간 무응답 시 워치독이 critical 실패로 간주, AWS에 TIMEOUT 보고
```

## 2. 최상위 폴더 구조

```text
JETSON_ROBOT
├─ ai/
│   ├─ detector/        camera.py + result.py + validator.py
│   ├─ qr/ segmentation/ tracker/   전부 빈 폴더 (미착수)
├─ robot/               로봇 제어 로직
├─ cloud/               AWS 서버 통신
├─ config/              설정 (.env 기반 Config, logging.conf, uart.yaml)
├─ mega_firmware/       Arduino Mega2560 C++ 펌웨어 (신규 프로토콜 반영 전, 후순위)
├─ JETSON/              IMX708 카메라 커널 드라이버 설치 자료 (DKMS)
├─ models/              best.pt(YOLOv8n) + config.yaml + labels.yaml(비어있음)
├─ scripts/             run_agent.sh
├─ systemd/             strew-robot-agent.service
├─ tests/               단위 테스트 + tests/manual
├─ README.md / ARDUINO_MEGA2560_프로토콜.md / JETSON_AWS_MEGA_INTEGRATION_PLAN.md / JETSON_ROBOT_수정_구축_계획.md
├─ Jetson_Mega_프로토콜_변경_안내_v4.pdf   Mega 개발자용 안내 문서(최종본)
├─ JETSON_NANO_YOLOV5_환경세팅.md   (이름은 YOLOv5지만 실제로는 v8→ONNX 경로도 6-B로 추가돼있음)
├─ requirements.txt
└─ .env / .env.example
```

## 3. `robot/` 상세

| 파일 | 상태 | 설명 |
|---|---|---|
| `state_machine.py` | 재작성됨(5차) | `RobotAgent`. `run_once()`는 이미 순회 중이 아닐 때만 `START_CYCLE` 전송 + 무응답 워치독 검사. `_uart_listener_loop()`가 `__init__`에서 스레드로 시작되어 `REQUEST_VISION`/`PROGRESS_UPDATE`/`REPORT_RESULT`/`CYCLE_COMPLETE`/`ERROR`를 비동기 처리 — UART 읽기와 `vision.read()`를 이 스레드 하나만 담당(단일 소유자). ERROR는 항상 물리 리셋으로만 복구(원격 `send_reset()`은 5차 개정에서 제거됨). |
| `command.py` | 정리됨 | `MSG_START_CYCLE`/`MSG_REQUEST_VISION`/`MSG_VISION_RESULT`/`MSG_PROGRESS_UPDATE`/`MSG_REPORT_RESULT`/`MSG_CYCLE_COMPLETE`/`MSG_ERROR`(신규 7종) + `MSG_ASSIGN_TARGET`(폐기, 상수만 추적용 보존). `MSG_RESET`은 4차 개정에서 도입했다가 5차 개정에서 제거됨. 구버전 `ArduinoCommand` 데이터클래스는 참조 없음 확인 후 **삭제됨**(2026-07-15). |
| `uart.py` | 정리됨 | `ArduinoLink`. `send_json_line()`(쓰기, `_write_lock`으로 동시 쓰기 보호), `_read_json_line()`(한 줄 읽기 — `_uart_listener_loop()` 전용, 단일 소유자). 구버전 `stream_progress()`(진행상황 스트리밍)는 새 양방향 프로토콜과 안 맞아 **삭제됨**(2026-07-15). |
| `packet.py` | 그대로 | `encode_packet()` — JSON 인코딩 규칙만 전담. |
| `planner.py` | **런타임 미사용, 스펙으로 보존** | `ACTION_MAP`: `healthy`→`OBSERVE`, `powdery_mildew`/`missing_plant`→`REPLACE`, 그 외→`SKIP`. Mega 펌웨어(C++)로 포팅해야 할 "정답 스펙"이자 `tests/test_decision.py` 커버리지 보존 목적으로 남겨둠 — Mega 작업 자체가 후순위라 이 파일도 그대로 유지. |
| `task_manager.py` | 구현됨, 미사용 | `TaskQueue`(FIFO). 현재 REST 폴링 구조에선 불필요, 추후 push 방식 도입 시 필요해질 예정. |

## 4. `RobotAgent` 실제 흐름 (4차 개정 반영)

```text
[run_once() — 주기적으로 호출]
1. cycle_active가 True면: 무응답 워치독만 검사(마지막 UART 수신 후 120초 경과 시 critical 실패 처리) 후 리턴
2. task 확보: AWS_ENABLED면 cloud.next_task(), 아니면 build_mock_task()
3. self.current_task = task, self.cycle_active = True
4. arduino.send_json_line({"type": "START_CYCLE"}) -> 응답 기다리지 않고 바로 리턴

[_uart_listener_loop() — __init__에서 시작된 별도 스레드, 계속 돌고 있음]
1. self.arduino._read_json_line()으로 한 줄씩 계속 읽음, 받을 때마다 last_uart_message_time 갱신
2. REQUEST_VISION: vision.read() -> VISION_RESULT로 status만 회신 (AWS_ENABLED면 post_vision_event도 호출)
3. PROGRESS_UPDATE: AWS_ENABLED면 post_progress로 릴레이 (정보성, cycle_active/current_task 안 건드림)
4. REPORT_RESULT: AWS_ENABLED면 post_response로 릴레이 (순회 안 끝났을 수 있어 cycle_active 그대로 둠)
5. CYCLE_COMPLETE: post_response(CYCLE 완료)로 릴레이, current_task=None, cycle_active=False
6. ERROR: AWS_ENABLED면 post_response(ERROR)로 릴레이. cycle_active는 계속 True로 유지 -
   사람이 물리적으로 확인하고 전원을 재시작하기 전까지 다음 순회를 자동 트리거하지 않음
   (원격 소프트웨어 재시작 경로는 5차 개정에서 제거됨 - 물리 센서가 없어 심각도를
   구분할 근거가 없다는 게 확인되어, 항상 물리 리셋만 유효하도록 단순화)
```

구버전의 `plan_task()` 호출, `ASSIGN_TARGET`(단일 셀 지정), `stream_progress()` 루프는 전부 이 흐름에서 빠졌다 — 그 판단과 순회 관리는 이제 전부 Mega 쪽 책임.

## 5. `cloud/` — AWS 통신

| 파일 | 상태 | 설명 |
|---|---|---|
| `api_client.py` | 구현됨 | `CloudClient` — `next_task`(GET), `post_response`(POST), `post_vision_event`(POST), `post_progress`(POST, 이제 `PROGRESS_UPDATE` 수신 시 호출됨 — 3차 개정 전엔 호출 지점이 없었으나 지금은 있음). |
| `mqtt.py` | 구현 완료 | `MqttClient.connect()` — 브로커 연결, `on_message`로 `emergency_stop_flag` 설정. 백그라운드 스레드(`loop_start()`)가 이 콜백만 처리 — vision/UART 코드는 건드리지 않음. |
| `sync.py` | 구현 완료 | `CloudSync` — `try_send(report_func, *args, **kwargs)`로 실패 시 큐에 저장, `flush_queue()`로 재시도. `state_machine.py`의 `post_progress`/`post_response`/`post_vision_event` 호출이 전부 이걸 거침. |

AWS 서버 자체(백엔드)는 이 저장소에 없다 — `AWS_ENABLED=false`(mock)로만 검증됨.

## 6. `ai/detector/` — 비전 처리

| 파일 | 상태 |
|---|---|
| `camera.py` | `MockVisionSource`(랜덤 status: healthy/powdery_mildew/missing_plant/empty_cell), `CsiCameraVisionSource` — `__init__`에 TensorRT 엔진 로딩/버퍼 할당 코드 작성됨(`yolo_model_path` 있을 때만, lazy import, `pycuda.autoinit`이 현재 스레드에 CUDA 컨텍스트 바인딩). 실제 추론(`_read_with_yolo_placeholder`)은 아직 컨투어 폴백 그대로 — `.engine` 파일 확보 후 마무리 예정(task #19). |
| `result.py` | `VisionResult` 데이터클래스(`label`, `confidence`, `x_center`, `y_center`, `width`, `height`, `status`). |
| `validator.py` | `is_valid_detection()` — `tests/test_detection.py`가 사용. |
| ~~`detector.py`, `capture.py`, `engine.py`, `inference.py`, `parser.py`, `preprocess.py`, `calibration.py`, `json_builder.py`~~ | **삭제됨** — 미착수 스텁, 참조 없음 확인 후 정리. |

## 7. YOLO 모델 — 진행 상황 (변경 없음, 2026-07-15 기준)

| 항목 | 내용 |
|---|---|
| 학습 결과 | `models/best.pt` — YOLOv8n(ultralytics) 기반, 학습 완료. |
| 배포 경로 | v5 재학습 대신 v8 유지 + ONNX 경유로 결정(시간 제약). `.pt` → (팀원 PC, ultralytics) → `.onnx` → (젯슨, `trtexec`) → `.engine`. 자세한 건 `JETSON_NANO_YOLOV5_환경세팅.md` 6-B절. |
| 리스크 | TensorRT 8.2.1.8이 오래된 버전이라 v8 export의 일부 연산을 못 읽을 수 있음 — `trtexec` 1차 시도로 검증 예정, 실패 시 opset 조정. |
| `camera.py` 진행 상황 | 엔진 로딩/컨텍스트 생성/host+device 버퍼 할당/`bindings` 구성까지 초기화 코드 작성됨. 실제 추론(전처리→`execute_async_v2`→후처리+NMS)은 `.engine` 파일과 실제 출력 shape 확인 후 작성 예정 — 이 부분은 이번 정리 라운드에서도 그대로 남겨둠(팀원 파일 대기). |
| `models/labels.yaml` | 여전히 `names: []`로 비어있음 — 학습 시 클래스 순서를 팀원에게 확인해서 채워야 함(YOLO 작업과 함께 후순위). |

## 8. 설정/실행 파일

| 파일 | 설명 |
|---|---|
| `config/settings.py` | `.env` 기반 `Config`. `yolo_model_path` 기본값을 `models/best.pt` → **`models/best.engine`으로 수정함**(2026-07-15) — TensorRT 로더는 `.pt`가 아니라 `.engine`을 읽으므로. 실제 `.engine` 파일은 아직 없음(팀원 export 대기). |
| `config/uart.yaml` | 로드되는 곳 없는 죽은 설정 파일. 삭제 권장(그대로 보류 중, 낮은 우선순위). |
| `scripts/run_agent.sh`, `systemd/strew-robot-agent.service` | 그대로. |

Python 버전 주의: Jetson `python3`는 3.6.9 — PEP 585 문법 불가.

## 9. `tests/`

| 파일 | 대상 | 비고 |
|---|---|---|
| `test_camera.py` | `ai.detector.camera` | |
| `test_decision.py` | `robot.planner.plan_task` | planner.py 자체는 런타임 미사용이지만 테스트는 여전히 유효(포팅 스펙 검증용) |
| `test_detection.py` | `ai.detector.validator` | |
| `test_uart.py` | `robot.uart` | 2026-07-15 정리: `stream_progress()` 관련 테스트 삭제, `_read_json_line()`(실제 사용되는 읽기 경로) 테스트로 대체 |
| `test_robot.py` | `robot.packet.encode_packet` | |
| `test_task.py` | `robot.task_manager.TaskQueue` | |
| `tests/manual/webcam_test.py` | 독립 스크립트, `ultralytics.YOLO` 직접 사용 | `pytest -q` 전체 실행 시 `--ignore=tests/manual` 필요 |

**새 아키텍처(순회 사이클 관리, ERROR/물리 리셋, 워치독)에 대한 `state_machine.py` 자체 단위 테스트는 아직 없음** — 필요하면 추가 검토(현재는 통합 시나리오를 코드 리뷰/수동 확인으로만 검증).

## 10. 정리 필요 사항 (Action Items, 2026-07-15 갱신)

1. ~~`robot/uart.py`의 `stream_progress()`, `robot/command.py`의 `ArduinoCommand`~~ — **삭제 완료**(참조 없음 확인).
2. ~~`config/settings.py`의 `yolo_model_path` 기본값~~ — **`.engine` 기준으로 수정 완료**.
3. `config/uart.yaml` — 삭제 권장(그대로 보류, 낮은 우선순위).
4. `mega_firmware.ino` — 신규 프로토콜(8종 메시지 + IDLE/RUN/ERROR) 반영 안 됨. 후순위, Mega 개발자에게는 PDF(v4)로 안내 완료.
5. YOLO `.onnx`→`.engine` 확보 후 `camera.py` 추론 로직 완성(task #19), `labels.yaml` 채우기 — 팀원 파일 대기.
6. `robot/planner.py` — Mega 포팅 완료되면 삭제 여부 재검토(현재는 의도적으로 보존).
7. `vision.read()` 타임아웃 — 아직 미구현(시리얼 쓰기 Lock을 먼저 구현함, 다음 우선순위).

## 11. 한 줄 요약

`JETSON_ROBOT`은 Jetson이 (AWS 또는 mock으로부터) 작업을 받아 Mega에 순회 시작만 지시하고, 이후 Mega가 1~4번 셀을 자체적으로 순회하며 필요할 때마다 요청하는 비전 확인에 응답하고, 진행상황·결과·오류를 AWS로 중계하며, Mega가 응답 없이 멈추는 것까지 감시(워치독)하는 로봇 에이전트다. 소프트웨어 설계·구현은 (Mega 펌웨어 자체 반영과 YOLO 실제 추론 연결을 제외하고) 사실상 마무리됐고, 남은 큰 항목은 팀원의 YOLO 파일 도착과 Mega 펌웨어 반영 두 가지다.
