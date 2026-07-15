# JETSON_ROBOT 수정 구축 계획 (v4, 2026-07-15 4차 개정 반영)

이전 버전(v3)은 아키텍처 전환의 1차 개정(결정권 이전, `ASSIGN_TARGET` 단일 셀 지정)까지만 반영되어 있었다. 그 사이 실시간으로 2~4차 개정이 이어져 순회 사이클 관리 전체와 ERROR 복구 경로까지 확정됐고, 그 김에 남아있던 정리 항목(설정값 불일치, 죽은 코드)도 이번 라운드에서 함께 마무리했다. 이 버전은 그 전체를 반영한다.

## 0. v3 대비 완료된 것

| 항목 | 상태 |
|---|---|
| **PROGRESS_UPDATE 추가(2차 개정)** | **완료.** Mega가 작업 중 셀 번호(`target`)+상태머신(`state`)+진행률(`progress`)을 수시로 중계. Jetson은 `post_progress`로 AWS 릴레이만 함(응답 불필요). |
| **순회 사이클 관리 이전(3차 개정)** | **완료.** `ASSIGN_TARGET`(단일 셀 지정) 폐기, `START_CYCLE`(셀 지정 없이 트리거만)로 대체. Mega가 1~4번 셀 전체를 자체 순회하고 초기 위치 복귀 후 `CYCLE_COMPLETE` 전송. Mega 최상위 상태 IDLE/RUN/ERROR를 Jetson이 인지. |
| **ERROR 복구 경로(4차 개정)** | **완료.** `ERROR`에 `severity`(minor/critical, 기본 critical) 필드 추가. `severity=minor`일 때만 Jetson이 `RESET` 전송 가능 — critical이면 물리 리셋만 유효(Mega도 자체 거부해야 함, 이중 안전장치). |
| **무응답 워치독(4차 개정)** | **완료.** `cycle_active` 중 120초(`MEGA_SILENCE_TIMEOUT_SEC`) 이상 UART 메시지가 없으면 Jetson이 암묵적 critical 실패로 간주, AWS에 TIMEOUT 보고. Jetson 단독 구현, Mega 쪽 작업 불필요. |
| **시리얼 쓰기 Lock(4차 개정)** | **완료.** `run_once()`와 `_uart_listener_loop()` 양쪽에서 발생하던 쓰기 경합을 `ArduinoLink._write_lock`(`threading.Lock`)으로 해결. |
| **`config/settings.py` 설정값 불일치 수정** | **완료.** `yolo_model_path` 기본값을 TensorRT 로더 요구사항에 맞게 `models/best.pt` → `models/best.engine`으로 수정. |
| **레거시 죽은 코드 정리** | **완료.** `robot/command.py`의 `ArduinoCommand`, `robot/uart.py`의 `stream_progress()` — 참조 없음 확인 후 삭제. `robot/planner.py`는 Mega 포팅 스펙으로 의도적 보존(제외). |
| **Mega 개발자용 PDF 안내** | **완료.** `Jetson_Mega_프로토콜_변경_안내_v4.pdf` — 전체 변경 이력, 8종 메시지 명세, Mega 필수 구현 체크리스트 포함. |

## 1. 신규 아키텍처 — 지금 실제로 설계/구현된 흐름 (4차 개정 최종)

```
Jetson: task 확보(AWS 또는 mock) -> 이미 순회 중 아니면 Mega에 START_CYCLE 전송, 응답 대기 안 함
Mega:   IDLE -> RUN 전환, 1~4번 셀 자체 순회 (내부 로직 아직 미구현/TODO)
Mega -> Jetson: REQUEST_VISION (셀마다, Mega가 필요할 때마다)
Jetson: vision.read() -> 날것 status만 VISION_RESULT로 회신 (_uart_listener_loop 스레드에서 처리)
Mega:   그 status로 REPLACE/OBSERVE/SKIP 자체 판단 + 물리 동작 (아직 미구현/TODO)
Mega -> Jetson: PROGRESS_UPDATE (작업 중 수시로, 정보성)
Mega -> Jetson: REPORT_RESULT (셀 하나 끝날 때마다, 순회당 최대 4회)
Jetson: AWS_ENABLED면 post_response/post_progress로 릴레이
Mega -> Jetson: CYCLE_COMPLETE (4번 다 돌고 초기 위치 복귀, IDLE 전환)
(오류 시) Mega -> Jetson: ERROR(reason, severity)
(minor면) Jetson -> Mega: RESET (critical이면 전송 자체를 거부)
(Mega가 응답을 완전히 멈추면) Jetson: 120초 후 워치독이 critical 실패로 간주, AWS에 TIMEOUT 보고
```

**UART 읽기와 `vision.read()`(TensorRT)는 전부 `_uart_listener_loop()` 스레드 하나가 담당한다(단일 소유자 원칙). 시리얼 쓰기는 `run_once()`와 listener 스레드 양쪽에서 발생하므로 `_write_lock`으로 별도 보호한다(단일 소유자가 아니라 Lock 방식).**

## 2. 여전히 보류 중인 것

| 항목 | 상태 | 비고 |
|---|---|---|
| AWS 서버 구현 자체 | **보류** | 여전히 이 저장소에 없음. mock으로만 검증. |
| **Mega 펌웨어 신규 프로토콜 반영** | **보류(최우선순위 아님)** | `mega_firmware.ino`가 아직 구버전 그대로. `ACTION_MAP` 로직 C++ 포팅 + 8종 메시지 송수신 + IDLE/RUN/ERROR 상태머신 + severity 판정 + critical일 때 RESET 거부 로직까지 필요. 외부 개발자에게 PDF로 안내 완료, 실제 반영은 시간 될 때. |
| `ai/detector/` 실제 YOLO 추론 | **진행 중** | task #19. `.onnx`→`.engine` 확보 대기 중(팀원이 export 예정). `labels.yaml` 클래스 순서도 함께 필요. |
| `vision.read()` 타임아웃 | **미구현** | 시리얼 쓰기 Lock을 먼저 구현하기로 선택함(둘 다 필요하다고 판단했던 항목 중 우선순위 낮은 쪽). |
| `ai/qr/`, `ai/segmentation/`, `ai/tracker/` | **보류** | 전부 빈 폴더, 미착수. |
| `config/uart.yaml` | **보류** | 로드하는 곳 없는 죽은 설정 파일, 삭제 권장이지만 낮은 우선순위. |
| stale PDF v1~v3 삭제 여부 | **결정 대기** | v4가 최종본이므로 이전 버전 삭제 검토 중. |

## 3. Decision Engine 규칙 — "Mega 포팅 스펙"으로 성격이 바뀐 채 유지

`robot/planner.py`의 규칙표는 안 바뀌었다. 여전히 Jetson이 실행하는 코드가 아니라 **Mega 펌웨어(C++)로 그대로 옮겨 심어야 할 스펙**이다.

| Vision Status | Robot Command |
|---|---|
| healthy | OBSERVE |
| powdery_mildew | REPLACE |
| missing_plant | REPLACE |
| empty_cell / 그 외 매핑 안 된 값 | SKIP (기본값) |

## 4. 코드 매핑 (2026-07-15 최종)

| 요소 | 파일 | 상태 |
|---|---|---|
| Task 조회 | `cloud/api_client.py`의 `next_task()` | 구현됨 |
| 순회 시작 트리거 | `robot/state_machine.py`의 `run_once()` | **재작성 완료** — `cycle_active`가 아닐 때만 `START_CYCLE` 전송, 무응답 워치독 검사 포함 |
| 비전 요청 응답 + 진행상황/결과/오류 릴레이 | `robot/state_machine.py`의 `_uart_listener_loop()` | **구현 완료** — `REQUEST_VISION`/`PROGRESS_UPDATE`/`REPORT_RESULT`/`CYCLE_COMPLETE`/`ERROR` 전부 처리 |
| ERROR 복구 | `robot/state_machine.py`의 `send_reset()` | **구현 완료** — severity=minor일 때만 RESET 허용 |
| 메시지 타입 상수 | `robot/command.py`의 `MSG_*` (8종) | **구현 완료**, 구버전 `ArduinoCommand`는 삭제됨 |
| 시리얼 쓰기 동시성 보호 | `robot/uart.py`의 `ArduinoLink._write_lock` | **구현 완료** |
| Decision Engine (참고 스펙) | `robot/planner.py`의 `plan_task()` | 런타임 미사용, 스펙으로 보존 |
| 오프라인 재시도 | `cloud/sync.py`의 `CloudSync` | 구현 완료 |
| MQTT 비상정지 | `cloud/mqtt.py`의 `MqttClient` | 구현 완료 |
| YOLO 추론 | `ai/detector/camera.py` | 초기화 완료, 추론 로직 진행 중(task #19) |
| 설정값 | `config/settings.py`의 `yolo_model_path` | `.engine` 기준으로 수정 완료 |

## 5. 다음 순서 제안

1. 팀원이 `.onnx` export해서 넘겨주면 → 젯슨에서 `trtexec`로 `.engine` 빌드 → `camera.py`의 `_read_with_yolo_placeholder()` 실제 추론 구현(task #19).
2. `models/labels.yaml` 클래스 순서 채우기(팀원 확인 필요).
3. 시간 되면 `mega_firmware.ino`에 신규 프로토콜(8종 메시지 + IDLE/RUN/ERROR + severity 판정 + critical RESET 거부) 포팅.
4. `vision.read()` 타임아웃 구현(다음 우선순위 항목).
5. stale PDF(v1~v3) 삭제 여부 확정.
6. AWS 서버 구현 착수 시점 결정 → `JETSON_AWS_MEGA_INTEGRATION_PLAN.md` 재검토.
