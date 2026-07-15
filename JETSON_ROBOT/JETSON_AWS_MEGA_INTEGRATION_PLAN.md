# Jetson-AWS-Mega 통합 계획 (2026-07-15 4차 개정 반영)

이전 버전은 아키텍처 전환의 1차 개정(결정권만 Mega로 이전)까지만 반영되어 있었다. 그 사이 2~4차 개정(진행상황 중계, 순회 사이클 관리, ERROR 복구+워치독)이 이어져 확정됐다. 이 버전은 그 전체를 반영한다.

## 역할 분담 (2026-07-15 최종 — 이전 버전과 반대 방향)

- **AWS 서버** (이 저장소에는 포함되어 있지 않음): 작업 큐, 대시보드, 승인 워크플로, 장기 로그를 소유. **변경 없음.**
- **Jetson** (`JETSON_ROBOT`, 이 저장소): AWS와 Mega 사이의 현장 게이트웨이. 작업을 받아와 Mega에 **순회 시작만 트리거**하고(셀 지정 없음), Mega가 요청할 때마다 카메라로 상태를 확인해 **날것 결과만** 알려주고, Mega가 중계하는 진행상황·최종 결과·오류를 그대로 AWS에 릴레이한다. 추가로 **Mega가 응답 없이 멈췄는지 감시(워치독)**하는 역할도 맡는다. **"무엇을 할지"도, "언제 몇 번 셀로 갈지"도 결정하지 않는다** — 이전 버전과 정반대.
- **Arduino Mega**: 실시간 모터/그리퍼/센서 제어는 그대로이고, 여기에 더해 **REPLACE/OBSERVE/SKIP 판단(Decision)** 뿐 아니라 **1~4번 셀 전체 순회 사이클 관리**(IDLE/RUN/ERROR 상태머신, 순회 시작~복귀~재대기)까지 Mega가 자체적으로 한다. Jetson에 먼저 말을 걸어(비전 확인 요청, 진행상황 보고) 필요한 정보를 주고받은 뒤 스스로 판단·순회·실행한다. 내부 오류 시 `severity`(minor/critical)를 스스로 판정해 보고해야 하고, critical일 때는 원격 `RESET`을 반드시 자체 거부해야 한다(물리 리셋만 유효) — 이전 버전의 "Mega는 명령받기 전엔 절대 스스로 움직이지 않는다"는 원칙이 완전히 폐기됨.

## 실제 확정된 Jetson↔Mega 프로토콜 (8종, 최종)

자세한 건 `ARDUINO_MEGA2560_프로토콜.md` 참고. 요약:

| 메시지 | 방향 | 필드 | 비고 |
|---|---|---|---|
| `START_CYCLE` | Jetson→Mega | 없음 | 순회 시작 트리거. `cycle_active`가 아닐 때만 전송 |
| `REQUEST_VISION` | Mega→Jetson | 없음 | 순회 중 셀마다, 여러 번 가능 |
| `VISION_RESULT` | Jetson→Mega | `status` | 판단 없이 날것 그대로 회신 |
| `PROGRESS_UPDATE` | Mega→Jetson | `target`, `state`, `progress` | 정보성, 응답 불필요 |
| `REPORT_RESULT` | Mega→Jetson | `target`, `execute_task`, `completion`, `success` | 셀 하나당, 순회당 최대 4회 |
| `CYCLE_COMPLETE` | Mega→Jetson | 없음 | 순회당 1회, IDLE 복귀 신호 |
| `ERROR` | Mega→Jetson | `reason`(선택), `severity`(minor\|critical, 기본 critical) | 최상위 상태 ERROR 진입 |
| `RESET` | Jetson→Mega | 없음 | `severity=minor`일 때만 전송, critical이면 Mega가 자체 거부 |

(`ASSIGN_TARGET`은 1차 개정에서 쓰였던 단일 셀 지정 메시지 — `START_CYCLE`로 대체되어 폐기됨, 상수만 추적용 보존)

구버전 프로토콜(`command`/`task` 필드, 2필드+진행상황 스트리밍)은 `ARDUINO_MEGA2560_프로토콜.md`에 참고용으로만 남아있고 실행 경로에서는 안 쓴다.

## 실제 확정된 Jetson↔AWS 엔드포인트 (`cloud/api_client.py` 기준) — 호출 시점 갱신

| 함수 | 메서드 | 엔드포인트 | 호출 시점 (최종) |
|---|---|---|---|
| `next_task(robot_id)` | GET | `/robot/next` | `run_once()`에서 순회 중이 아닐 때만(AWS_ENABLED일 때만) |
| `post_vision_event(robot_id, event)` | POST | `/vision/event` | `_uart_listener_loop()`가 `REQUEST_VISION`에 응답할 때마다 |
| `post_progress(robot_id, task_id, target, state, progress)` | POST | `/robot/progress` | **이제 호출 지점 있음** — `PROGRESS_UPDATE` 수신 시마다. 3차 개정 이전엔 이 엔드포인트를 쓸 데이터가 없었으나, 이제 Mega가 작업 중 셀+상태를 중계하므로 정상적으로 쓰임 |
| `post_response(robot_id, task_id, execute_task, completion_sign, message, payload)` | POST | `/robot/response` | `REPORT_RESULT`(셀당, 최대 4회), `CYCLE_COMPLETE`(순회당 1회), `ERROR`(발생 시), 무응답 워치독 발동 시(`TIMEOUT`) — 총 4가지 경우에 호출 |

**AWS 서버(백엔드) 자체는 이 저장소에 없다.** 위 4개 함수는 REST 호출 코드만 준비되어 있고, 실제 검증은 전부 `AWS_ENABLED=false`(mock) 상태로 이루어졌다.

## 지금 시점에 정해지지 않은 것

- 실제 인증 방식(`X-API-Key` 헤더는 Jetson 쪽에 구현되어 있으나 서버 쪽 검증 로직은 없음) — 변경 없음.
- 승인 대기(WAIT_APPROVAL) 같은 작업 상태 흐름 — 변경 없음, 여전히 미정.
- 오프라인 시 재전송 캐시 — **완료.** `cloud/sync.py`의 `CloudSync`(`try_send`/`flush_queue`)로 구현됨.
- push 방식(MQTT) — **부분 완료.** `cloud/mqtt.py`의 `MqttClient`가 비상정지 수신용으로 구현됨(작업 큐 push는 아님, REST 폴링은 그대로 유지).
- `/robot/progress` 엔드포인트 재활용 — **해결됨.** `PROGRESS_UPDATE` 메시지로 3차 개정에서 다시 쓰이게 됨.
- Mega가 `REQUEST_VISION` 보냈는데 Jetson이 응답을 못 주는 경우 — **부분 해결.** `vision.read()` 자체의 타임아웃은 아직 미구현(다음 우선순위). 다만 Mega가 아예 응답을 멈추는 반대 방향 실패는 Jetson 측 무응답 워치독(`MEGA_SILENCE_TIMEOUT_SEC`)으로 커버됨.
- ERROR 복구 흐름 — **완료.** `severity` 필드 + `RESET` 메시지 + Mega 측 critical 자체 거부(이중 안전장치)로 설계 확정. Mega 펌웨어 반영은 아직(외부 개발자 몫).
- AWS 서버 자체 구현 — 여전히 착수 안 됨.

## 다음 순서

1. Mega 펌웨어에 신규 프로토콜(8종 메시지 + IDLE/RUN/ERROR + severity 판정 + critical RESET 거부) 반영(시간 될 때, 최우선순위 아님) — 외부 개발자에게 PDF(v4)로 안내 완료.
2. AWS 서버를 실제로 만들 때 위 4개 엔드포인트 기준으로 구현 — `/robot/progress`도 이제 실제로 쓰이니 함께 구현.
3. 서버 준비되면 `.env`의 `AWS_ENABLED=true`로 전환해 mock 없이 end-to-end 검증.
4. `vision.read()` 타임아웃 구현, YOLO 실제 추론 연결(팀원 ONNX 대기), 승인 워크플로는 이후 다시 논의.
