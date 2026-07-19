# STREW Jetson Robot

Jetson 보드에서 도는 로봇 에이전트. AWS에서 작업을 받아오고(또는 mock으로 대체), Mega가 순회 사이클을 자체 관리하도록 시작 신호만 보내고, Mega가 요청할 때마다 카메라로 식물 상태를 확인해 날것 결과를 알려주고, Mega가 보고하는 진행상황/최종 결과/오류를 AWS로 중계한다.

**2026-07-15 기준 핵심 변경(5차에 걸쳐 진행됨)**: 외부 팀 회의 결과로 REPLACE/OBSERVE/SKIP **결정 권한이 Jetson에서 Mega로 이전**되었고, 이후 순회 사이클 관리(1~4번 셀)까지 전부 Mega 쪽으로 넘어갔다. Jetson은 이제 "판단"하지 않고 (1) 순회 시작 트리거, (2) 비전 결과 제공(요청 시), (3) 진행상황/최종 결과/오류를 AWS로 릴레이, (4) Mega가 응답 없이 멈췄는지 감시(워치독)만 한다. ERROR 복구는 항상 물리 리셋(전원 재시작 등)만으로 이루어진다 — 원격 소프트웨어 재시작(RESET) 경로는 도입했다가 물리 센서가 없어 심각도 구분이 불가능하다는 게 확인되어 제거했다. 자세한 건 `ARDUINO_MEGA2560_프로토콜.md` 참고.

## 실제 폴더 구조 (2026-07-15 갱신)

```text
main.py              진입점 — Config() 생성 → RobotAgent(cfg).run_forever()
config/              .env 기반 설정 (Config dataclass), logging.conf, uart.yaml(현재 미사용 레거시 파일)
robot/               로봇 제어 핵심
  command.py          MSG_* 7종 상수(신규 프로토콜, RESET은 5차 개정에서 제거됨). 구버전 ArduinoCommand 데이터클래스는 미사용 확인 후 삭제됨.
  packet.py           JSON 인코딩 규칙만 (하드웨어 모름)
  uart.py             ArduinoLink — 시리얼 I/O. send_json_line()은 write_lock으로 동시 쓰기 보호, _read_json_line()은 단일 소유자(listener 스레드)만 호출. 구버전 stream_progress()는 신규 흐름과 안 맞아 삭제됨(레거시).
  planner.py          ACTION_MAP — 런타임에서 안 씀. Mega 펌웨어 포팅용 "정답 스펙"으로 보존(Mega 작업은 후순위)
  state_machine.py    RobotAgent — run_once()(순회 시작 트리거 + 무응답 워치독) + _uart_listener_loop()(Mega 요청/보고 전담 스레드, vision·UART 읽기의 단일 소유자)
  task_manager.py     TaskQueue — 구현됨, 현재 파이프라인에서는 미사용(향후 push 방식 도입 시 필요)
cloud/               AWS 통신
  api_client.py        CloudClient — next_task/post_response/post_vision_event/post_progress
  mqtt.py               구현됨 — MqttClient (emergency_stop 등 구독)
  sync.py               구현됨 — CloudSync (오프라인 시 재시도 큐, try_send/flush_queue)
ai/
  detector/            camera.py(비전 소스, TensorRT 초기화 코드 작성됨·추론 로직은 아직), result.py(VisionResult), validator.py
  qr/ segmentation/ tracker/   전부 빈 폴더 (미착수)
mega_firmware/        Arduino Mega2560 펌웨어 (C++) — 신규 프로토콜 반영 전(후순위 TODO)
JETSON/               IMX708 카메라 커널 드라이버 설치 자료 (DKMS)
models/               best.pt(YOLOv8n, 학습 완료) + config.yaml/labels.yaml(labels.yaml은 아직 비어있음)
tests/                 유닛 테스트 (pytest) + tests/manual (웹캠 등 수동 스크립트)
scripts/               run_agent.sh
systemd/               strew-robot-agent.service (부팅 시 자동 실행)
```

## 실행

```bash
python3 main.py
```

`.env`(프로젝트 루트, `robot/` 아님)에 최소 아래 값 필요:

```
VISION_MODE=mock        # 실카메라 없이 테스트할 때. 실제 카메라는 csi
ARDUINO_PORT=/dev/ttyUSB0  # 실제 Mega가 잡힌 포트
```

`AWS_ENABLED`을 안 적으면 기본값 `false`.

## 현재 상태 요약 (2026-07-15, 4차 개정 반영)

- **Jetson↔Mega 프로토콜: 제어 권한 + 순회 사이클 관리 + 오류 보고까지 전부 Mega로 이전됨.** 신규 메시지 7종(`START_CYCLE`/`REQUEST_VISION`/`VISION_RESULT`/`PROGRESS_UPDATE`/`REPORT_RESULT`/`CYCLE_COMPLETE`/`ERROR`, `ASSIGN_TARGET`은 폐기). Jetson은 `START_CYCLE`(셀 지정 없이 "순회 시작해"만 전송)만 보내고, 1~4번 셀 순회·복귀·재시도는 전부 Mega 내부 로직. 구버전(2필드+스트리밍)은 문서에 참고용으로만 남아있음. 자세한 건 `ARDUINO_MEGA2560_프로토콜.md`.
- **Mega 최상위 상태(IDLE/RUN/ERROR)를 Jetson이 인지한다.** `START_CYCLE`로 RUN 진입, `CYCLE_COMPLETE`로 IDLE 복귀, 내부 오류 시 `ERROR` 수신. ERROR는 **항상 물리 리셋(전원 재시작 등)으로만 복구** — 한때 `severity`(minor/critical) 구분 + 원격 `RESET` 메시지 경로를 만들었으나, 물리 센서(전류/엔코더 등)가 없어 Mega가 "가벼운 문제인지 심각한 문제인지"를 스스로 판단할 근거가 없다는 게 확인되어 완전히 제거함(단순함이 곧 안전함).
- **무응답 워치독**: `cycle_active` 중 Mega로부터 `MEGA_SILENCE_TIMEOUT_SEC`(120초) 이상 아무 메시지도 없으면 Jetson이 응답 없이 멈춘 것으로 간주하고 AWS에 `TIMEOUT`으로 보고(ERROR와 동일하게 물리 확인 필요로 취급). Mega 쪽 구현 불필요(Jetson 단독 안전장치).
- **UART Listener Thread + 단일 소유자 원칙**: `_uart_listener_loop()`가 UART 읽기와 `vision.read()`(TensorRT)를 전담. 여기에 더해 **시리얼 쓰기는 `ArduinoLink._write_lock`으로 보호**됨(`run_once()`와 listener 스레드 양쪽에서 쓰기가 발생하므로) — 두 스레드의 쓰기가 겹쳐 바이트가 섞이는 문제 해결됨.
- **`cloud/sync.py`, `cloud/mqtt.py` 구현 완료.** 오프라인 시 재시도 큐(`CloudSync`)와 MQTT 구독(`MqttClient`) 모두 동작함.
- **AWS 서버 자체는 여전히 이 저장소에 없음** — `cloud/api_client.py`는 REST 호출 함수만 준비된 상태, mock 모드로만 검증됨.
- **AI 추론(YOLO)은 아직 로봇 파이프라인에 연결 안 됨.** `models/best.pt`는 YOLOv8n으로 학습 완료. Jetson의 TensorRT(8.2.1.8)가 오래된 버전이라 v8은 `.onnx` 경유로 `.engine` 빌드 예정(v5 C++ 변환 경로는 안 씀). `ai/detector/camera.py`에 TensorRT 엔진 로딩/버퍼 할당 초기화 코드는 작성됨(`__init__`), 실제 추론 로직(`_read_with_yolo_placeholder`)은 아직 컨투어 폴백 그대로임 — `.engine` 파일 확보 후 마무리 예정. `config/settings.py`의 `yolo_model_path` 기본값도 `.engine` 기준으로 갱신됨.
- **레거시 코드 정리 완료**: `robot/command.py`의 `ArduinoCommand`, `robot/uart.py`의 `stream_progress()` — 신규 흐름에서 참조 없음을 확인하고 삭제함. `robot/planner.py`는 예외 — Mega 펌웨어 포팅 스펙으로 의도적으로 보존.

## 지금 시점에 남은 것 (2026-07-15 기준)

1. YOLO 실제 추론 — 팀원 ONNX export 대기 중 (`config/settings.py`의 `yolo_model_path`, `models/labels.yaml` 클래스 순서도 함께 확정 필요).
2. `mega_firmware.ino` 신규 프로토콜(7종 메시지 + IDLE/RUN/ERROR, 항상 물리 리셋) 반영 — 후순위로 미룸, 대신 외부 개발자에게 PDF로 안내 예정(v5, ERROR severity/RESET 제거 반영).

Python 3.6.9(Jetson 기본) 호환 주의 — `dict[str, Any]` 같은 PEP 585 내장 제네릭 문법은 안 되므로 `typing.Dict` 사용.
