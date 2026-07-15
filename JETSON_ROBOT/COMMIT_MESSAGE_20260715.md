# Jetson→Mega 결정권/순회 관리 이전 아키텍처 전환(4차 개정) + YOLOv8 파이프라인 결정 + 레거시 정리

## 요약

외부 팀 회의 결과로 REPLACE/OBSERVE/SKIP 판단 권한을 Jetson에서 Mega로 이전하는 아키텍처
전환을 진행함. 하루 동안 4차례 요구사항이 추가되며 (1) 기본 결정권 이전 → (2) 작업 진행상황
중계(`PROGRESS_UPDATE`) → (3) 1~4번 셀 전체 순회 사이클 자체 관리(`START_CYCLE`/
`CYCLE_COMPLETE`, IDLE/RUN/ERROR) → (4) ERROR severity 기반 복구 경로(`RESET`) + 무응답
워치독 + 시리얼 쓰기 동시성 보호까지 확장됨. 별도로 YOLOv8 학습 가중치(`models/best.pt`)를
어떻게 배포할지 결정(v5 재학습 대신 ONNX 경유 TensorRT 빌드)하고 `camera.py`에 TensorRT
엔진 초기화 코드를 작성함. 마지막으로 이번 라운드에서 설정값 불일치와 죽은 코드를 정리하고,
4개 프로젝트 문서를 최신 아키텍처에 맞게 갱신함.

## 변경 사항

### robot/command.py
- 메시지 상수를 8종으로 확장: `MSG_START_CYCLE`, `MSG_REQUEST_VISION`, `MSG_VISION_RESULT`,
  `MSG_PROGRESS_UPDATE`, `MSG_REPORT_RESULT`, `MSG_CYCLE_COMPLETE`, `MSG_ERROR`, `MSG_RESET`.
- 셀 하나만 지정하던 `MSG_ASSIGN_TARGET`은 순회 전체를 트리거하는 `MSG_START_CYCLE`로 대체(폐기,
  추적용으로 상수만 보존).
- 구버전 2필드(`command`/`target`) 프로토콜의 `ArduinoCommand` 데이터클래스 — 코드 전체에서
  참조 없음을 grep으로 확인 후 **삭제**.

### robot/uart.py
- `ArduinoLink.__init__`에 `self._write_lock = threading.Lock()` 추가.
- `send_json_line()` 본문을 `with self._write_lock:` 블록으로 감쌈 — `run_once()`(메인 스레드)와
  `_uart_listener_loop()`(별도 스레드) 양쪽에서 발생하는 쓰기 경합(바이트 섞임 위험)을 해결.
- 구버전 `stream_progress()`(명령 1회 전송 → RECEIVED~COMPLETE 응답을 직접 읽던 제너레이터) —
  새 양방향 프로토콜(Mega가 먼저 말을 거는 구조)과 구조적으로 안 맞아 **삭제**. 읽기는
  `_read_json_line()` 하나로 통일하고 `_uart_listener_loop()`가 전담(단일 소유자).
- 미사용 `Iterator` 타입 임포트 제거.

### robot/state_machine.py
- `RobotAgent.__init__`에 `cycle_active`, `last_uart_message_time`, `last_error_severity`
  상태 추가 + `_uart_listener_loop()`를 데몬 스레드로 시작.
- `run_once()`: 이미 순회 중(`cycle_active`)이면 무응답 워치독만 검사(마지막 UART 수신 후
  `MEGA_SILENCE_TIMEOUT_SEC`=120초 경과 시 암묵적 critical 실패로 간주, AWS에 `TIMEOUT` 보고)
  하고 리턴. 순회 중이 아니면 task 확보 후 `START_CYCLE` 전송(응답 대기 없음).
- `_uart_listener_loop()`: UART 읽기와 `vision.read()`(TensorRT)를 전담하는 단일 소유자 스레드.
  `REQUEST_VISION`(비전 결과 회신+AWS 릴레이), `PROGRESS_UPDATE`(정보성 릴레이),
  `REPORT_RESULT`(셀당 결과 릴레이, 순회 지속), `CYCLE_COMPLETE`(IDLE 복귀 처리),
  `ERROR`(severity 기록+릴레이) 5종 메시지 처리.
- `send_reset()` 신규 추가 — `last_error_severity == "minor"`일 때만 `RESET` 전송 허용, 아니면
  거부(critical은 물리 리셋만 유효하다는 설계 원칙을 Jetson 쪽에서도 강제).

### robot/planner.py
- 변경 없음(의도적). `ACTION_MAP`/`plan_task()`는 이제 런타임에서 안 쓰이지만 Mega 펌웨어
  포팅용 "정답 스펙" + 기존 테스트 커버리지 보존 목적으로 그대로 유지.

### ai/detector/camera.py
- `CsiCameraVisionSource.__init__`에 TensorRT 초기화 코드 작성: `trt.Runtime.
  deserialize_cuda_engine()` → `create_execution_context()` → `cuda.Stream()` → 바인딩별
  host/device 버퍼 할당(`pagelocked_empty`/`mem_alloc`) → `bindings` 리스트 구성.
- `tensorrt`/`pycuda` 임포트는 `yolo_model_path`가 있을 때만 지연 임포트(mock 환경 호환).
- 엔진/버퍼 로드 실패 시 `RuntimeError` 즉시 발생(폴백 없음, 기존 fail-hard 정책 유지).
- 실제 추론(`_read_with_yolo_placeholder`)은 컨투어 폴백 그대로 — 팀원 ONNX 파일 대기 중(범위 제외).

### config/settings.py
- `yolo_model_path` 기본값을 `"models/best.pt"` → `"models/best.engine"`으로 수정 — TensorRT
  로더가 실제로 읽는 파일 형식과 기본값을 일치시킴.

### README.md / JETSON_ROBOT_구조_기능_요약.md / JETSON_ROBOT_수정_구축_계획.md / JETSON_AWS_MEGA_INTEGRATION_PLAN.md
- 1차 개정(결정권 이전, `ASSIGN_TARGET` 단일 셀 지정) 상태에서 멈춰있던 4개 문서를 2~4차 개정
  전체(진행상황 중계, 순회 사이클 관리, ERROR 복구+워치독, 시리얼 락, 설정값/레거시 정리)까지
  반영해 전면 갱신.

### ARDUINO_MEGA2560_프로토콜.md
- 이번 라운드에서 추가 변경 없음(4차 개정까지 이미 실시간으로 갱신되어 최신 상태였음).

### JETSON_NANO_YOLOV5_환경세팅.md
- "6-B. YOLOv8 → ONNX → TensorRT 경로(현재 채택)" 절 추가 — `ultralytics` ONNX export
  스니펫 + `trtexec --onnx=... --saveEngine=... --fp16` 명령. 기존 "6-A"(v5 C++ 변환 경로)는
  "현재 미사용"으로 표시하고 보존.

### tests/test_uart.py
- `stream_progress()` 관련 테스트 6개 삭제(대상 메서드 삭제에 따름).
- `_read_json_line()`(실제 런타임에서 쓰이는 읽기 경로) 검증 테스트 4개 신규 추가: 정상 JSON
  파싱, 빈 응답 시 `None`, 비JSON 응답 시 `{"raw": ...}` 래핑, 시리얼 없을 때 `None`.

### 외부 산출물 — Mega 개발자용 안내 PDF
- `Jetson_Mega_프로토콜_변경_안내.pdf`(v1, 6p) → `_v2.pdf`(7p, PROGRESS_UPDATE+동시성 경고
  추가) → `_v3.pdf`(7p, 순회 사이클 관리 추가) → `_v4.pdf`(6p, ERROR/RESET/워치독 + Mega 필수
  구현 체크리스트 ①~⑪) 순으로 4회 개정. v4가 최종본.
- v1~v3은 stale 상태 — 이번 라운드에서 삭제 시도했으나 워크스페이스 폴더 쓰기 권한 문제로
  실제 삭제는 아직 안 됨(사용자 수동 삭제 필요할 수 있음).

## 검증

```
pytest -q --ignore=tests/manual
15 passed
```

(기존 16개 중 `stream_progress` 테스트 6개 삭제 + `_read_json_line` 테스트 4개 추가로 순감소 1개)

## 알려진 이슈 / 다음 작업

- YOLO 실제 추론(`_read_with_yolo_placeholder()`) — 팀원 `.onnx` export 대기 중, 이번 라운드
  범위에서 명시적으로 제외.
- `mega_firmware.ino` 신규 프로토콜(8종 메시지 + IDLE/RUN/ERROR) 반영 안 됨 — 후순위,
  외부 개발자에게 PDF(v4)로 안내만 완료.
- `vision.read()` 타임아웃 — 아직 미구현(시리얼 쓰기 Lock을 먼저 선택함).
- `models/labels.yaml`의 `names: []` — 팀원 확인 후 채워야 함.
- stale PDF v1~v3 — 워크스페이스 폴더 삭제 권한 문제로 남아있음.
