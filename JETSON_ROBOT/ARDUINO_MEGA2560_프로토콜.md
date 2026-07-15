# Arduino Mega2560 UART 프로토콜 (2026-07-15 3차 개정 — ERROR 복구 경로 + 무응답 워치독 추가)

`mega_firmware/mega_firmware.ino`, `robot/command.py`, `robot/uart.py`, `robot/state_machine.py`가 이 스펙과 정합되어야 한다. **이번 2차 개정은 같은 날 있었던 1차 개정(제어 권한 이전)을 대체하는 게 아니라 그 위에 쌓는 것이다** — 1차 개정에서는 "판단은 Mega가 한다"까지만 정했는데, 이번 2차 개정에서 "1~4번 셀 전체 순회 자체를 Mega가 관리한다"는 것과 Mega의 상위 동작 상태(IDLE/RUN/ERROR)가 추가로 확정됨.

## 이번 2차 개정 사유 (핵심 변경)

Mega가 1번부터 4번 셀까지 순서대로 순회하고, 전부 정상이면 초기 위치(1번)로 복귀해 대기하는 것까지 전부 Mega가 자체 관리하는 것으로 확정됨. 이에 따라 1차 개정에서 정의했던 `ASSIGN_TARGET`(셀 하나씩 지정)은 **더 이상 맞지 않음** — Jetson은 이제 셀을 지정하지 않고 "순회 시작해"라는 트리거(`START_CYCLE`)만 보낸다. 또한 Mega의 상위 동작 상태 3가지가 확정됨:

| Mega 상태 | 의미 | 전환 조건 |
|---|---|---|
| `IDLE` | Jetson의 명령을 기다리는 대기 상태 | 순회 완료 후, 또는 시작 시 기본값 |
| `RUN` | 1~4번 순회 실행 중 | `START_CYCLE` 수신 시 IDLE → RUN |
| `ERROR` | 내부 문제로 비상 정지 | 하드웨어/센서 이상 등 감지 시 즉시 전환 (RUN/IDLE 무관) |

검사 도중 병해충(또는 결주)이 발견되면 그 즉시 그 셀에서 보식(REPLACE) 작업을 수행하고 다음 셀로 넘어간다 — 1차 개정에서 정한 "REQUEST_VISION으로 물어보고 자체 판단"이라는 메커니즘 자체는 그대로 유지되고, 이걸 셀마다(1~4번) 반복하는 것이 이번 개정의 핵심이다.

## 통신 형식 공통

- 한 줄 JSON + 개행(`\n`). UTF-8. (`robot/packet.py`의 `encode_packet()` 그대로 유지 — 인코딩 방식 자체는 안 바뀜.)
- 모든 새 메시지는 `"type"` 필드로 종류를 구분한다 (기존 `"command"`/`"task"` 필드명 규칙과 별개).
- 상수는 `robot/command.py`에 정의되어 있다: `MSG_START_CYCLE`, `MSG_REQUEST_VISION`, `MSG_VISION_RESULT`, `MSG_PROGRESS_UPDATE`, `MSG_REPORT_RESULT`, `MSG_CYCLE_COMPLETE`, `MSG_ERROR`, `MSG_RESET`. (`MSG_ASSIGN_TARGET`은 1차 개정에서 정의했으나 **이번 2차 개정으로 사용 중단** — 하위 호환/이력 추적 목적으로 상수만 남아있음.)

## 메시지 8종 (`ASSIGN_TARGET`은 사용 중단, 목록에서 제외)

| type | 방향 | 필드 | 의미 |
|---|---|---|---|
| `START_CYCLE` | Jetson → Mega | (없음) | "순회 시작해"만 알려줌. **셀 지정 없음** — 1~4번 중 어디로 갈지는 전부 Mega가 자체 관리. Mega는 이 메시지를 받으면 IDLE → RUN 전환. 한 순회당 1회, `run_once()`가 보냄(단, Mega가 이미 RUN 중이면 Jetson은 다시 보내지 않음 — `cycle_active` 플래그로 방지). |
| `REQUEST_VISION` | **Mega → Jetson** | (없음) | Mega가 순회 중 셀마다 필요할 때 보냄(위치 도착 직후, REPLACE 완료 후 검증 시 등). 한 순회에 여러 번(최대 8회: 4개 셀 × 최초 확인 + REPLACE 시 재확인). |
| `VISION_RESULT` | Jetson → Mega | `status`(문자열: `healthy`/`powdery_mildew`/`missing_plant`/`empty_cell`) | `REQUEST_VISION`에 대한 응답. **날것의 vision 판단 결과만** 담음. |
| `PROGRESS_UPDATE` | **Mega → Jetson** | `target`(문자열, 셀 라벨), `state`(문자열, Mega 내부 상태머신 상태), `progress`(정수 0~100, 선택) | 순회 중 "지금 몇 번 셀에서 무슨 단계인지"를 알려주는 **정보성 메시지 — 응답 불필요**. |
| `REPORT_RESULT` | **Mega → Jetson** | `target`, `execute_task`(REPLACE/OBSERVE/SKIP), `completion`, `success`(선택) | **셀 하나 처리 결과.** 한 순회(1~4번)당 최대 4회 옴(셀마다 1번씩). |
| `CYCLE_COMPLETE` | **Mega → Jetson** | (없음, 필요하면 요약 필드 추가 협의 가능) | **전체 순회(1~4번) 완료 + 초기 위치 복귀 + IDLE 전환** 신호. 한 순회당 1회. Jetson은 이 신호를 받아야 다음 `START_CYCLE`을 보낼 수 있음. |
| `ERROR` | **Mega → Jetson** | `reason`(문자열, 선택), `severity`(문자열, `"minor"` 또는 `"critical"` — **없으면 Jetson은 critical로 간주**) | 내부 문제로 비상 정지(ERROR 상태 전환) 시 즉시 전송. Jetson은 이걸 받으면 **자동으로 다음 순회를 트리거하지 않음**(안전을 위해 사람 개입 전까지 대기). `severity`에 따라 복구 방식이 갈림 — 아래 "ERROR 복구 경로" 참고. |
| `RESET` | Jetson → Mega | (없음) | 사람이 ERROR를 확인하고 재시작을 승인했을 때 Jetson이 보냄(`RobotAgent.send_reset()`). **직전 ERROR의 `severity`가 `"minor"`였을 때만 Jetson이 이 메시지를 보낸다.** Mega는 `"critical"` 상태에서 받은 RESET을 반드시 무시해야 함(아래 참고). |

### ERROR 복구 경로 (신규)

ERROR를 두 등급으로 나눈다 — 이 등급 구분과 대응은 Mega 펌웨어가 스스로 판단해서 `severity` 필드에 실어 보내야 한다.

| severity | 예시 | 복구 방법 |
|---|---|---|
| `minor` | 일시적 센서 노이즈, 짧은 통신 끊김 등 물리적으로 안전하게 재시작 가능한 경우 | Jetson이 `RESET` 메시지를 보내면 Mega가 ERROR → IDLE 전환 (원격 복구 가능) |
| `critical` (또는 `severity` 필드 자체가 없음) | 그리퍼 걸림, 모터 이상, 충돌 감지 등 물리적 확인이 필요한 경우 | **Mega는 RESET 메시지를 반드시 무시**하고, 전원 재시작/물리 리셋 버튼으로만 복구되도록 구현해야 함 |

Jetson 쪽에서도 `RobotAgent.last_error_severity`가 `"minor"`가 아니면 `send_reset()` 자체가 `RESET`을 보내지 않고 거부하도록 이중으로 막아뒀다. 하지만 **최종 안전장치는 Mega 쪽에 있어야 한다** — Jetson 코드에 버그가 있거나 누군가 실수로 RESET을 보내더라도, `critical` 상태의 Mega가 스스로 거부해야 진짜 안전하다.

### 무응답 워치독 (신규, Jetson 쪽에 이미 구현됨)

Mega가 `ERROR`조차 보내지 못하고 그냥 응답 없이 멈추는 경우(크래시, 완전 정지 등)를 대비해, Jetson은 순회 중(`cycle_active=True`) 마지막으로 UART 메시지를 받은 시각을 계속 추적한다. `MEGA_SILENCE_TIMEOUT_SEC`(현재 120초, 실측 후 조정 필요) 동안 아무 메시지도 없으면 무응답 정지로 간주해 AWS에 알리고, `severity=critical`과 동일하게 취급해 자동 재시작을 막는다. **이건 Jetson 단독으로 구현 가능한 부분이라 이미 반영했고, Mega 쪽에서 별도로 할 일은 없다** — 다만 Mega가 살아있는 한 어떤 형태로든 주기적으로 무언가(`PROGRESS_UPDATE` 등)를 보내주면 이 워치독이 오작동(정상인데 오래 조용해서 타임아웃)할 가능성이 줄어든다.

### 흐름 예시 (1~4번 순회 중 3번에서 REPLACE가 발생하는 경우)

```
Jetson --START_CYCLE-------------------> Mega                (IDLE -> RUN)
                                          Mega: 1번 셀로 이동
Mega   --REQUEST_VISION----------------> Jetson
Jetson --VISION_RESULT(status=healthy)-> Mega                (1번: 이상 없음)
Mega   --REPORT_RESULT(target=cell_1, execute_task=OBSERVE, completion=COMPLETE)--> Jetson
                                          Mega: 2번 셀로 이동 (2번도 healthy라고 가정, 위와 동일 패턴 반복)
                                          Mega: 3번 셀로 이동
Mega   --REQUEST_VISION----------------> Jetson
Jetson --VISION_RESULT(status=powdery_mildew)--> Mega
                                          Mega: 자체 판단 -> REPLACE, 즉시 보식 작업 수행
                                          (필요하면 REQUEST_VISION을 한 번 더 보내 교체 후 검증)
Mega   --REPORT_RESULT(target=cell_3, execute_task=REPLACE, completion=COMPLETE, success=true)--> Jetson
                                          Mega: 4번 셀로 이동 (healthy라고 가정)
                                          Mega: 전체 순회 끝 -> 초기 위치(1번) 복귀
Mega   --CYCLE_COMPLETE-----------------> Jetson              (RUN -> IDLE)
                                          Jetson: cycle_active = False, 다음 START_CYCLE 트리거 가능해짐
```

## Jetson↔Mega 역할 분담 원칙

- **무엇을 할지(WHAT)와 "어느 셀을 언제 갈지"는 전부 Mega가 결정한다.** `robot/planner.py`의 `ACTION_MAP`(status → REPLACE/OBSERVE/SKIP)을 Mega 펌웨어(C++)로 그대로 이식해야 하며, 1~4번 순회 순서/타이밍도 Mega 내부 로직이 관리한다.
- **비전 판단(status 계산)은 여전히 Jetson이 한다.** 카메라/TensorRT가 물리적으로 Jetson에 있으므로 이건 안 바뀜.
- **Jetson은 이제 "순회 시작 트리거 + 비전 결과 제공 + 진행상황/결과 AWS 중계"만 한다.** 셀 지정도, 판단도 하지 않는다.
- **Jetson은 AWS 게이트웨이 역할은 그대로 유지한다.** Mega는 인터넷이 없으므로, Mega가 무엇을 하든 그 결과를 AWS에 보고하는 건 여전히 Jetson(`_uart_listener_loop()`)의 책임.

## 알려진 미해결 사항 (TODO)

- ~~세부 진행상황(progress) 스트리밍이 없어짐~~ → **해결됨.** `PROGRESS_UPDATE`로 처리.
- ~~순회 개념(1~4번 자동 순회) 미반영~~ → **해결됨(2차 개정).** `START_CYCLE`/`CYCLE_COMPLETE`로 처리.
- ~~`ERROR` 수신 후 재시작 방법 미설계~~ → **해결됨(3차 개정).** `severity`(minor/critical) 구분 + `RESET` 메시지로 처리(위 "ERROR 복구 경로" 참고). **단, Mega 펌웨어가 critical일 때 RESET을 거부하는 로직은 반드시 Mega 쪽에서 구현해야 함 — 아직 안 됨.**
- ~~Mega가 응답 없이 조용히 멈추는 경우 미대응~~ → **Jetson 쪽은 해결됨(3차 개정, 무응답 워치독).** Mega 쪽은 별도로 할 일 없음(위 참고).
- **데드락/타임아웃 위험 — 부분 미해결.** `_uart_listener_loop()`의 `vision.read()` 호출 자체엔 아직 타임아웃이 없다(Jetson 쪽 보완 예정). **Mega 펌웨어는 `REQUEST_VISION` 전송 후 일정 시간(예: 5~10초) 안에 `VISION_RESULT`가 안 오면 반드시 타임아웃 처리(ERROR 전환 등)를 구현해야 한다** — 이건 여전히 Mega 쪽 구현이 필요함.
- ~~시리얼 쓰기 동시 접근 위험~~ → **해결됨(4차 개정).** `robot/uart.py`의 `ArduinoLink`에 `threading.Lock`을 추가해 `send_json_line()` 전체를 감쌈 — 어느 스레드가 부르든 한 번에 한 스레드만 쓸 수 있음. Mega 쪽에서도 JSON 파싱 실패 시 그냥 무시하고 다음 줄을 기다리는 방어 코드는 여전히 권장.
- **구버전(1차 개정 포함)의 상태머신/`ArduinoCommand`/`stream_progress()`는 새 흐름에서 더 이상 호출되지 않는다.** 삭제 여부는 별도 결정 필요.
- **Mega 펌웨어(`mega_firmware.ino`) 자체는 아직 이 신규 프로토콜에 맞춰 재작성 전.** 이 문서가 목표 스펙이고, 실제 펌웨어 반영은 별도 작업(시간 될 때 진행 예정).

## 레거시 수동 점검용 명령 / 오류 처리 / 확인된 이력 (구버전 그대로 유지)

레거시 수동 점검용 명령(PING/STATUS/HOME/MOVE/STOP/SERVO/GRIP_OPEN/GRIP_CLOSE/WATER/NUTRITION/PUMP_ON/PUMP_OFF/LED)과 그 오류 처리 규칙은 이번 개정과 무관하므로 그대로 유지된다 — 상세 표는 구버전 프로토콜(아래) 참고.

## 구버전 프로토콜 (2026-07-10, Jetson이 결정하던 시절 — 참고용으로 보존)

이 절 아래는 새 아키텍처 이전(REPLACE/OBSERVE/SKIP을 Jetson이 결정하던 시절)의 문서를 그대로 보존한 것이다. 위 신규 메시지 4종이 이 구버전 명령 3종(`OBSERVE`/`REPLACE`/`SKIP`, `command`/`task` 필드)을 대체하는 관계다. 펌웨어 포팅 시 구버전의 상태머신(세부 단계 표)이 여전히 참고 자료로 쓰일 수 있어 지우지 않았다.

- **요청(Jetson → Mega, 구버전)**: `{"command": "...", "target": "..."}` — 2필드 고정.
- **응답(Mega → Jetson, 구버전)**: `{"task": "...", "target": "...", "state": "...", "progress": N}` — 4필드.

### 명령 3종 (구버전 — `robot/planner.py`의 `plan_task()`가 결정하던 값)

| command | 트리거 (vision status) | Mega 내부 동작 (물리적 의미) |
|---|---|---|
| `OBSERVE` | `healthy` | 대상 셀로 이동 → 카메라 자세 정렬 → 정밀 검사 → 대기 위치 복귀 |
| `REPLACE` | `powdery_mildew` 또는 `missing_plant` | 대상 셀 이동 → 기존 화분 집기 → 폐기 위치로 이동 → 내려놓기 → 새 화분 위치로 이동 → 집기 → 대상 셀에 배치 |
| `SKIP` | `empty_cell`(빈 셀) 또는 그 외 매핑 안 된 값 | 물리 동작 없음 |

### OBSERVE 상태머신 (구버전)

| state | progress | 의미 |
|---|---|---|
| `RECEIVED` | 0 | 명령 수신 확인 |
| `MOVE_TO_CELL` | 20 | 대상 셀로 이동 |
| `POSITION_CAMERA` | 40 | 검사 위치로 카메라 자세 정렬 |
| `INSPECTION` | 70 | 6축을 이용한 정밀 검사 수행 |
| `RETURN_HOME` | 90 | 대기 위치 복귀 |
| `COMPLETE` | 100 | 종료 |

### REPLACE 상태머신 (구버전)

| state | progress | 의미 |
|---|---|---|
| `RECEIVED` | 0 | 명령 수신 확인 |
| `MOVE_TO_CELL` | 10 | 대상 셀로 이동 |
| `PICK_OLD_POT` | 25 | 기존 화분 집기 |
| `MOVE_TO_DISPOSAL` | 40 | 폐기 위치로 이동 |
| `DROP_OLD_POT` | 50 | 기존 화분 내려놓기 |
| `MOVE_TO_NEW_POT` | 60 | 새 화분 위치로 이동 |
| `PICK_NEW_POT` | 75 | 새 화분 집기 |
| `PLACE_NEW_POT` | 90 | 대상 셀에 새 화분 배치 + 포토센서로 위치 확인 |
| `COMPLETE` | 100 | 종료 |

### SKIP 상태머신 (구버전)

| state | progress | 의미 |
|---|---|---|
| `RECEIVED` | 0 | 명령 수신 확인 |
| `SKIPPED` | 100 | 종료 |

### 레거시 수동 점검용 명령 (예전 단발 응답 형식, 지금도 유효)

`sendResponse(status, command)` → `{"status": "...", "command": "..."}` 단발 응답.

| command | 추가 필드 | 응답 status | 비고 |
|---|---|---|---|
| PING | - | PONG | 순수 연결 확인용 |
| STATUS | - | READY | |
| HOME | - | DONE | |
| MOVE | `target`(int, 좌표) | DONE | LCD에 `TARGET:%d` 표시 |
| STOP | - | DONE | |
| SERVO | `angle`(int) | DONE | LCD에 `ANGLE:%d` 표시 |
| GRIP_OPEN | - | DONE | |
| GRIP_CLOSE | - | DONE | |
| WATER | - | DONE | |
| NUTRITION | - | DONE | 실제 펌프 하드웨어 없음 |
| PUMP_ON | - | DONE | |
| PUMP_OFF | - | DONE | |
| LED | `state`(string, 기본값 "UNKNOWN") | DONE | 진행상황 스트리밍의 `state`와 무관한 별개 필드 |

### 오류 처리 (지금도 유효)

| 상황 | 응답 |
|---|---|
| JSON 파싱 실패 | `{"status": "ERROR"}` |
| `command` 키 자체가 없음 | `sendResponse("ERROR", "NONE")` |
| 목록에 없는 명령 | `sendResponse("UNKNOWN_COMMAND", command)` |

## 확인된 이력

- 2026-07-07: 2필드(`command`/`target`) + 스트리밍 인터페이스로 Jetson 쪽 설계 완료.
- 2026-07-08: 실제 Mega 펌웨어와의 불일치 발견, 1차 재작성.
- 2026-07-10: 공식 문서 기준 상태머신/필드명 확정 (`command`/`task` 구분, SKIP 종료 상태 `SKIPPED`).
- **2026-07-15: 외부 회의 결과로 제어 권한이 Jetson → Mega로 이전. 신규 메시지 4종(`ASSIGN_TARGET`/`REQUEST_VISION`/`VISION_RESULT`/`REPORT_RESULT`) 도입, `robot/state_machine.py`에 UART Listener Thread 추가(단일 소유자 원칙으로 vision/UART 동시 접근 문제 방지). Mega 펌웨어 반영과 progress 스트리밍 재설계는 아직 TODO.**
