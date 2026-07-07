# JETSON_ROBOT 단위 기능 테스트 & 트러블슈팅 보고서

포트폴리오용 기록 문서. 테스트를 진행할 때마다 아래 형식으로 항목을 추가한다.
코드는 본인이 직접 작성하고, Claude는 개념 설명(코칭)과 이 보고서 작성만 담당한다.

## 기록 형식

각 테스트 항목은 다음을 포함한다.

- 대상 모듈/파일
- 목적 (왜 이 테스트가 필요한가)
- 구현 내용 요약 (본인이 작성한 코드가 무엇을 하는지)
- 실행 명령
- 결과 (성공/실패, 실제 출력)
- 발생한 에러 (있었다면 그대로)
- 트러블슈팅 과정 (원인 파악 → 시도 → 해결)
- 최종 결론

---

<!-- 아래부터 테스트 항목이 순서대로 추가됩니다 -->

## 테스트 1. robot/uart.py — ArduinoLink.send_json_line()

**대상 모듈/파일**: `robot/uart.py`

**목적**: Jetson이 아두이노로 JSON 명령을 보내고, 아두이노가 보낸 응답을 안전하게 파싱하는지 검증한다. 실제 아두이노 하드웨어 없이도 로직만 먼저 검증하기 위해 `unittest.mock.MagicMock`으로 시리얼 포트를 가짜로 대체했다 (AWS 데이터와는 무관 — 여기서 "mock"은 아두이노 시리얼 포트를 흉내낸 것이지, AWS 응답을 흉내낸 게 아니다).

**구현 내용 요약**: 본인이 작성한 `ArduinoLink`는
- 생성자에서 시리얼 포트 연결을 `try/except`로 감싸서 실패 시 명확한 `RuntimeError`로 변환
- `close()`/`send_json_line()` 둘 다 `self.serial`이 `None`이거나 닫혀있는지 먼저 확인하는 방어 코드 포함
- `send_json_line()`은 I/O 에러(`SerialException`/`OSError`)와 JSON 파싱 에러(`JSONDecodeError`)를 서로 다른 `try/except`로 분리해서 처리
- JSON 파싱에 실패해도 예외를 던지지 않고 `{"raw": 원본문자열}`로 감싸서 반환

**실행 명령** (임시 검증 스크립트, `tests/test_uart.py`로 정식 추가 예정):
```python
link = ArduinoLink.__new__(ArduinoLink)  # __init__ 건너뛰고 인스턴스만 생성
# case1: mock_serial.readline.return_value = b'{"completion_sign":"DONE"}\r\n'
# case2: mock_serial.readline.return_value = b''
# case3: mock_serial.readline.return_value = b'garbage-not-json\r\n'
# case4: link.serial = None
```

**결과**: 4개 케이스 전부 통과
```
case1 (valid json): {'completion_sign': 'DONE'}
case2 (empty response): None
JSON 디코딩 오류: garbage-not-json
case3 (invalid json): {'raw': 'garbage-not-json'}
case4 (no serial): None
ALL CASES PASSED
```

**발생한 에러**: 리뷰 도중 `robot/uart.py` 파일이 897바이트에서 멀티바이트 UTF-8 문자 중간에 끊긴 채로 저장되어 있었다 (`UnicodeDecodeError: 'utf-8' codec can't decode byte 0xeb in position 896: unexpected end of data`).

**트러블슈팅 과정**: `wc -c`로 파일 크기를 확인하고 마지막 바이트를 직접 열어봐서 한글 문자 하나가 인코딩 중간에 잘려있는 걸 확인 → 저장이 도중에 끊긴 것으로 판단 → 다시 저장 요청 → 재확인 후 정상 파싱 확인.

**최종 결론**: 로직 자체는 통과. 다만 리뷰 중 발견한 미해결 이슈 하나가 남아있음 — 지금 코드는 "응답 없음(타임아웃)"과 "진짜 통신 에러"를 둘 다 `None`으로 반환해서, `state_machine.py`에서 `arduino_response = send_json_line(...) or {"completion_sign": "DONE", ...}` 처리 시 두 경우가 똑같이 "성공(DONE)"으로 취급된다. 실제 통신 실패 시에도 AWS에 완료 보고가 갈 수 있다는 뜻이라, 이 구분을 명시적으로 할지는 다음 단계에서 결정 필요.

---

## 테스트 2. tests/test_uart.py — 실제 Mega2560 펌웨어 기준 정식 테스트 작성

**대상 모듈/파일**: `tests/test_uart.py` (신규 생성)

**목적**: 테스트 1에서는 `completion_sign` 키를 쓰는 임시 mock 데이터로 검증했는데, 실제 Mega2560 펌웨어 소스코드(`sendResponse()` 함수)를 확인해보니 응답 형식이 `{"status": ..., "command": ...}`이지 `completion_sign`이 아니었다. 정식 테스트 파일은 실제 프로토콜 기준으로 다시 작성했다.

**실제 프로토콜 확인 결과** (`ARDUINO_MEGA2560_프로토콜.md` 참고):
- 응답은 항상 `{"status": "...", "command": "..."}` 형태 (단, JSON 파싱 실패시 `{"status":"ERROR"}`만 오고 `command` 키가 없음)
- 목록에 없는 명령을 보내면 Arduino가 아예 응답을 안 보냄 (`sendResponse()` 미호출) → Jetson 입장에서는 타임아웃과 동일하게 보임
- `robot/state_machine.py`가 찾고 있는 `completion_sign` 키는 실제 응답에 존재하지 않는 키 — 원래 코드에 있던 버그로 확인됨 (별도 조치 필요, 아직 미수정)

**구현 내용 요약**: `tests/test_uart.py`에 6개 케이스 작성
1. MOVE 명령 → `{"status":"DONE","command":"MOVE"}`
2. PING 명령 → `{"status":"PONG","command":"PING"}`
3. Arduino 측 JSON 파싱 실패 → `{"status":"ERROR"}` (command 키 없음까지 검증)
4. 목록에 없는 명령 → 응답 없음(빈 바이트) → `None`
5. JSON이 아닌 이상한 문자열 → `{"raw": "..."}`
6. 시리얼 연결 자체가 없음 → `None`

**실행 명령**:
```bash
pytest tests/test_uart.py -v
```

**결과**: 6개 전부 통과
```
tests/test_uart.py::test_move_command_returns_done_status PASSED
tests/test_uart.py::test_ping_command_returns_pong_status PASSED
tests/test_uart.py::test_json_parse_failure_on_arduino_side_returns_error_status_without_command PASSED
tests/test_uart.py::test_unknown_command_gets_no_response_from_arduino PASSED
tests/test_uart.py::test_non_json_garbage_from_arduino_is_wrapped_as_raw PASSED
tests/test_uart.py::test_no_serial_connection_returns_none PASSED
6 passed in 0.08s
```
전체 스위트 기준 11 passed (기존 5개 + 신규 6개).

**발생한 에러**: 없음 (한 번에 통과).

**트러블슈팅 과정**: 해당 없음 — 다만 이 테스트를 작성하게 된 계기 자체가 테스트 1에서 쓴 mock 데이터가 실제 하드웨어 스펙과 달랐다는 걸 발견한 것이었으므로, "테스트를 실제 사양과 대조 검증하는 것"의 중요성을 보여주는 사례로 기록.

**최종 결론**: 통과. 단, `robot/state_machine.py`의 `completion_sign` 키 버그는 이번 테스트로 존재가 확인됐을 뿐 아직 수정되지 않음 — 다음 작업으로 남겨둠. 또한 Decision Engine의 `OBSERVE`/`SKIP`이 Arduino 명령 목록에 없다는 점도 설계 확인 필요 항목으로 남아있음.

---

## 테스트 3. robot/state_machine.py — completion_sign → status 버그 수정

**대상 모듈/파일**: `robot/state_machine.py` (`run_once()` 메서드)

**목적**: 테스트 2에서 발견한 "아두이노 실제 응답 키(`status`)와 코드가 찾는 키(`completion_sign`)가 다른" 버그를 수정한다.

**문제 원인 재정리**: `robot/uart.py`의 `send_json_line()`은 아두이노가 보낸 JSON을 `json.loads()`로 그대로 딕셔너리化한다 — 키 이름을 바꾸거나 새로 만들지 않는다. 즉 실제 응답이 `{"status":"DONE","command":"MOVE"}`면 이 딕셔너리에는 `status`/`command` 두 키만 존재한다. 그런데 `state_machine.py`는 `arduino_response.get("completion_sign", "DONE")`으로 존재하지 않는 키를 찾고 있어서, 아두이노가 `DONE`을 보내든 `ERROR`를 보내든 매번 기본값 `"DONE"`으로 처리되고 있었다. `uart.py`에는 잘못이 없고, 버그는 `state_machine.py`의 키 이름 하나에 있었다.

**구현 내용 요약**: `run_once()` 안 두 곳을 수정
- 응답 없을 때 쓰는 기본 딕셔너리의 키: `"completion_sign": "DONE"` → `"status": "DONE"`
- 응답에서 값을 꺼내는 부분: `arduino_response.get("completion_sign", "DONE")` → `arduino_response.get("status", "DONE")`

`cloud.post_response(..., completion_sign=completion, ...)`의 `completion_sign`은 건드리지 않음 — 이건 아두이노 응답을 읽는 코드가 아니라 AWS API로 보낼 때 쓰는 파라미터 이름이라 별개의 것.

**실행 명령**:
```bash
pytest tests/ -q --ignore=tests/manual
```

**결과**: 11 passed (기존 전체 스위트 그대로 유지)

수정이 실제로 의미가 있는지 별도로 재현 확인:
```
DONE 응답 -> DONE
ERROR 응답 -> ERROR
수정 확인: DONE과 ERROR가 이제 서로 다르게 처리됨
```
수정 전이었다면 두 경우 모두 `DONE`으로 나왔을 상황.

**발생한 에러**: 없음.

**트러블슈팅 과정**: 로컬(Windows) 환경에서 `pytest` 실행 시 `pip install pytest` 도중 `WinError 2` (실행 파일 생성 실패)로 설치가 일부 꼬여서, 검증은 별도 Linux 환경에서 대신 수행함. Windows 쪽 `pytest` 설치는 추후 별도로 해결 필요.

**최종 결론**: 수정 완료 및 검증 통과. 이 이슈는 마무리됨.

---

## 테스트 4. robot/planner.py — Decision Engine 규칙표 구현

**대상 모듈/파일**: `robot/planner.py` (`plan_task()` 함수), `tests/test_decision.py` (신규)

**목적**: Notion Chapter 05-4가 정의한 규칙표(healthy→OBSERVE, powdery_mildew→REPLACE, missing_plant→REPLACE, nutrition_needed→NUTRITION, empty_cell→SKIP)를 실제 코드로 구현하고, 애매하거나 목록에 없는 상태는 안전하게 SKIP 처리되는지 검증한다.

**개발 과정에서 발견된 3가지 문제**:

1. **딕셔너리(`ACTION_MAP`)를 만들어놓고 if/elif로 다시 중복 판단** — `ACTION_MAP`을 정의해놓고도 실제로는 `if status == "healthy": execute_task = "OBSERVE"` 같은 if/elif 체인으로 따로 판단하고 있었음. `ACTION_MAP.get(status, "SKIP")` 한 줄로 대체.
2. **모르는 상태의 기본값이 `SKIP`이 아니라 `OBSERVE`로 되어 있었음** — `status`가 없거나(`None`) 규칙표에 없는 값이면 안전하게 아무 것도 안 해야 하는데(`SKIP`), 기본값이 `OBSERVE`로 처리되고 있었음. AI가 아직 없어 `status`가 항상 비어있는 지금 상황에서는 이 버그 때문에 매번 `OBSERVE`가 나오는 셈이었음.
3. **반환값에서 원래 `task` 정보가 사라짐 (가장 심각)** — `return {"task": execute_task, "vision": vision}`처럼 `"task"` 키에 원래 task 딕셔너리(`id`, `cell_id` 등)가 아니라 판단 결과 문자열이 덮어써지고 있었음. 나중에 `state_machine.py`가 이 결과를 쓸 때 원래 task 정보(예: task id)가 통째로 사라진 상태였음.

**최종 코드**:
```python
ACTION_MAP = {
    "healthy": "OBSERVE",
    "powdery_mildew": "REPLACE",
    "missing_plant": "REPLACE",
    "nutrition_needed": "NUTRITION",
    "empty_cell": "SKIP",
}

def plan_task(task: dict, vision: dict) -> dict:
    status = vision.get("status")
    execute_task = ACTION_MAP.get(status, "SKIP")
    return {"task": task, "vision": vision, "execute_task": execute_task}
```

**구현 내용 요약**: `tests/test_decision.py`를 7개 케이스로 재작성
1. healthy → OBSERVE
2. powdery_mildew → REPLACE
3. missing_plant → REPLACE
4. nutrition_needed → NUTRITION
5. empty_cell → SKIP
6. status 없음/모르는 값 → SKIP (2가지 하위 케이스)
7. execute_task가 추가돼도 원래 task/vision 정보는 그대로 보존되는지 확인

**실행 명령**:
```bash
pytest tests/ -q --ignore=tests/manual
```

**결과**: 17 passed (test_decision.py 7개 포함 전체 스위트)

**발생한 에러**: 검증 과정에서 bash 마운트 쪽 `robot/planner.py` 파일에 널바이트(`\x00`)가 356개 섞여 들어가 있어 `ValueError: source code string cannot contain null bytes`로 테스트 수집 자체가 실패했음 (이전에도 있었던 Windows-Linux 마운트 동기화 지연 문제의 재발).

**트러블슈팅 과정**: `wc -c` / `open(...,'rb').read().count(b'\x00')`로 파일을 직접 바이트 단위로 확인해 널바이트 오염을 확인 → 정상 상태인 Read 결과 기준으로 heredoc(`cat > file << 'EOF'`)으로 파일을 강제로 다시 씀 → `__pycache__` 삭제 후 재검증 → 정상 통과.

**최종 결론**: `planner.py`는 규칙표대로 정확히 동작하며 3가지 문제 모두 수정 완료. Notion 트러블슈팅 페이지에도 동일 내용 기록함.

---

## 테스트 5. robot/ 폴더 정리 — 죽은 코드 3개 처리 및 packet.py 설계의도 명확화

**대상 모듈/파일**: `robot/protocol.py`(삭제), `robot/packet.py`, `robot/uart.py`, `robot/task_manager.py`

**목적**: `robot/` 폴더 전체를 점검해 "만들어놓고 실제로는 아무 데서도 안 쓰이는" 파일이 있는지 확인하고, 있다면 삭제하거나 역할을 명확히 한다.

**점검 결과**: `grep`으로 프로젝트 전체에서 import 여부를 확인한 결과 3개 파일이 자기 자신의 테스트 파일에서만 쓰이고 실제 실행 흐름에는 전혀 연결돼 있지 않았음.

1. `protocol.py` — `COMPLETION_DONE/FAILED/RUNNING` 상수 3개. 값 자체도 실제 Mega2560 프로토콜(`DONE`/`PONG`/`READY`/`ERROR`)과 안 맞음 → **삭제**.
2. `packet.py` — `encode_packet()`이 하는 일(dict→JSON→UTF-8 bytes)을 `uart.py`가 자체적으로 중복 구현하고 있었음 → `packet.py` 상단에 설계 의도(역할 분리: packet.py=인코딩 규칙, uart.py=시리얼 I/O) 문서화, `uart.py`가 실제로 `from robot.packet import encode_packet`을 가져다 쓰도록 수정하여 중복 제거.
3. `task_manager.py` — `TaskQueue`/`should_poll()`. 분석 결과 지금 연결된 `cloud/api_client.py`(REST 폴링, 호출 1번에 작업 1개만 반환)에서는 병목이 구조적으로 발생할 수 없어 현재는 미사용 상태가 맞음. 다만 아직 미구현인 `cloud/mqtt.py`(push 방식)로 전환하면 서버가 로봇 처리 속도와 무관하게 메시지를 계속 보낼 수 있어 그때는 완충 역할로 필요해짐 → **삭제하지 않고 보류**, `should_poll()`은 `run_forever()`의 `time.sleep()`과 완전히 중복이라 제거 후보로 남김.

**실행 명령**:
```bash
pytest tests/ -q --ignore=tests/manual
```

**결과**: 17 passed (packet.py/uart.py 수정 후에도 전체 스위트 그대로 통과)

**발생한 에러**: `packet.py` 수정 과정에서 두 가지 에러가 겹쳐 발생함.
1. bash 마운트 동기화 지연 재발 — `uart.py`/`packet.py`가 파일 끝부분이 잘린 채로 마운트에 반영되어 `SyntaxError: expected 'except' or 'finally' block`, `SyntaxError: unterminated triple-quoted string literal` 발생.
2. `packet.py` docstring 안에 적은 `\uXXXX`, `\n` 같은 표기가 실제 Python 유니코드 이스케이프로 해석되어 `SyntaxError: (unicode error) 'unicodeescape' codec can't decode bytes... truncated \uXXXX escape` 발생 — 이건 마운트 문제가 아니라 raw string(`r"""`)을 안 써서 생긴 순수 작성 실수.

**트러블슈팅 과정**: 1번은 기존과 동일하게 Read 도구로 확인한 정상 내용을 heredoc으로 재기록해 해결. 2번은 docstring을 `"""`에서 `r"""`(raw string)로 바꿔서 백슬래시 표기가 문자 그대로 유지되도록 수정.

**최종 결론**: `protocol.py` 삭제 완료, `packet.py`↔`uart.py` 중복 제거 및 설계 의도 문서화 완료, `task_manager.py`는 미래(MQTT push 전환 시) 필요성이 확인되어 보류 결정. Notion 트러블슈팅 페이지에도 동일 내용 기록함.

---

## 설계 변경 1. Jetson↔Mega 명령 인터페이스 — 7필드 구조에서 2필드(command/target) 구조로 전환

**배경**: 사용자가 정식 인터페이스 명세서("Jetson(Python) ↔ Arduino Mega 인터페이스 및 역할 분담 명세")를 제시함. 핵심 원칙은 "Jetson은 무엇을 할지(Task)만 결정, Mega는 어떻게 수행할지(모터/하드웨어 제어)를 전담"이며, 명령 형식이 `{"command": "...", "target": "cell_x"}` 2개 필드뿐이고, 응답도 단발성이 아니라 `RECEIVED`(0%)부터 `COMPLETE`(100%)까지 여러 번에 걸쳐 진행상황(state/progress)을 보내는 구조임.

**기존 계획과의 차이**:
- 기존: `robot/motion.py`가 `execute_task`를 보고 `move_sign`(MOVE/STOP)을 직접 판단해서 `ArduinoCommand`(7개 필드: task_id/execute_task/move_sign/target_label/detected_label/x_center/y_center)에 실어 보냄. `uart.py`는 한 번 보내고 한 번 읽으면 끝.
- 신규: 이동 여부 판단 자체가 필요 없음 — `{"command": execute_task, "target": target_label}` 2개 필드만 보내면, 이동을 포함한 모든 물리적 절차는 Mega의 내장 상태머신이 알아서 수행. 대신 Jetson은 `COMPLETE` 응답이 올 때까지 진행상황을 계속 읽어야 함.

**장단점 분석**: (상세는 Notion 참고)
- 장점: 역할 분리가 더 명확해짐, 진행상황 실시간 파악 가능(기존의 "타임아웃과 진짜 에러를 구분 못 하는 문제"가 완화됨), 명령 자체가 단순해져 테스트/디버깅 쉬움, 로봇/셀별 물리 오차는 Mega의 EEPROM만 조정하면 됨.
- 단점: `uart.py`가 "한 번 쓰고 한 번 읽기"에서 "COMPLETE까지 반복해서 읽기"로 복잡도 증가, 중간에 멈췄을 때 "작업 중"과 "고장"을 구분할 타임아웃 전략이 새로 필요, `state_machine.py`의 `run_once()` 흐름도 재설계 필요.

**최종 결정**: 디버깅 용이성을 우선시하여 **2필드(command/target) 구조로 확정**.

**영향받는 파일**:
- `robot/planner.py` — 변경 없음 (이미 이 명세와 일치: healthy→OBSERVE, powdery_mildew/missing_plant→REPLACE, 그 외 기본값 SKIP. `empty_cell`/`nutrition_needed`는 이번 인터페이스에서 완전히 제외하기로 확정)
- `robot/motion.py` — 기존 계획(MOVE/STOP 판단) 폐기
- `robot/command.py` — `ArduinoCommand`를 `command`/`target` 2개 필드로 축소 예정 (다음 작업)
- `robot/uart.py` — 진행상황 스트리밍 응답 처리로 재설계 예정 (다음 작업)
- `robot/state_machine.py` — `run_once()` 흐름 재설계 예정 (다음 작업)

**최종 결론**: 설계가 확정됐고, 다음 단계로 `command.py` 필드 정리 → `uart.py` 스트리밍 응답 처리 → `state_machine.py` 흐름 재설계 순으로 진행 예정. Notion 트러블슈팅 페이지에도 동일 내용 기록함.

---

## 테스트 6. command.py 2필드 전환 + uart.py stream_progress() 구현 (20260707)

**대상 모듈/파일**: `robot/command.py`, `robot/uart.py`, `tests/test_uart.py`, `tests/test_decision.py`, `robot/planner.py`

**목적**: 전날 확정한 2필드(command/target) 인터페이스를 실제 코드로 구현한다.

**command.py**: `ArduinoCommand`를 7개 필드에서 `command`/`target` 2개로 축소. `asdict()`를 쓰기 때문에 필드 이름이 곧 JSON 키가 된다는 점이 중요 포인트였음 (단순히 개수만 줄이는 게 아니라 이름 자체를 `execute_task`→`command`, `target_label`→`target`으로 맞춰야 함). `task_id`는 삭제해도 안전 — AWS 보고는 `ArduinoCommand`가 아니라 `task["id"]`를 직접 읽는 별개 경로이기 때문.

**planner.py 추가 정리**: 2필드 인터페이스가 `command`로 `OBSERVE`/`REPLACE`/`SKIP` 3개만 지원하므로, `ACTION_MAP`에 남아있던 `"nutrition_needed": "NUTRITION"`도 삭제 (NUTRITION은 펌프 하드웨어 자체가 없어 이번 인터페이스에서 완전히 제외 확정). `tests/test_decision.py`의 관련 테스트도 삭제.

**uart.py — 코칭 진행 과정**: `send_json_line()`이 "쓰기 1번 + 읽기 1번"을 묶어서 처리하던 구조였는데, 새 프로토콜은 명령 1번에 응답이 `RECEIVED`(0%)부터 `COMPLETE`(100%)까지 여러 번(REPLACE 기준 9번) 온다는 걸 사용자가 먼저 스스로 파악함. 이후 소크라테스식 질문(반복문 종료 조건, `yield`의 필요성, `decode()`와 `json.loads()`의 차이, `send_json_line()`을 몇 번 불러야 하는지 등)으로 설계를 코칭했고, 최종적으로 "`send_json_line()`은 쓰기 전용으로 단순화하고, 읽기는 새 메서드(`stream_progress()`) 하나에서 전부 처리"하는 구조로 사용자가 직접 결론 냄. 다만 실제 타이핑 과정에서 문법 오류(`errors="SKIP"` 오타, `bytes.encode()` 이중 인코딩, 정의 안 된 변수 사용, 딕셔너리 인덱싱 문법 오류 등)가 누적되어 꼬였고, 사용자가 지쳐서("코드 한번만 봐줘") 이번엔 Claude가 직접 정리함 (사용자 사전 동의).

**최종 코드 구조**:
- `send_json_line(payload) -> bool`: 인코딩(`packet.py`) 후 쓰기만 하고 성공 여부만 반환
- `_read_json_line() -> Optional[dict]`: 시리얼 한 줄 읽기 → `decode()` → `json.loads()` (내부 헬퍼)
- `stream_progress(payload, timeout_sec=30.0) -> Iterator[dict]`: `send_json_line()` 1번 호출 후, `_read_json_line()`을 반복 호출하며 메시지를 하나씩 `yield`. `state == "COMPLETE"`면 종료. 마지막 메시지 이후 `timeout_sec` 초과 시 타임아웃으로 종료 (단계별 정밀 타임아웃 대신 공통 기준 채택 — 하드웨어 실측 데이터 부재로 인한 실용적 선택).

**tests/test_uart.py 재작성** (7개 케이스): 쓰기 성공/실패, `stream_progress`가 여러 상태를 순서대로 yield하는지, COMPLETE 이후 더 이상 안 읽는지, JSON 파싱 실패시 `{"raw":...}` 처리, 무응답 시 타임아웃, 전송 자체 실패 시 빈 결과.

**실행 명령**:
```bash
pytest tests/ -q --ignore=tests/manual
```

**결과**: 16 passed

**발생한 에러**: 이 작업 도중에도 bash 마운트 동기화 지연이 반복 발생함 — `robot/planner.py`, `tests/test_decision.py`, `cloud/api_client.py`가 각각 다른 시점에 마운트 쪽에서 널바이트 오염 또는 파일 끝 잘림으로 `SyntaxError`/`ValueError`를 일으킴. 매번 Read 도구(정상 상태)를 기준으로 heredoc으로 재기록해서 해결.

**최종 결론**: 2필드 인터페이스(command.py) + 스트리밍 응답(uart.py) 구현 완료, 16 passed. 다음은 `robot/state_machine.py`의 `run_once()`를 `stream_progress()` + `planner.plan_task()` 호출 구조로 재설계하는 것 (task #11로 등록).

---

## 테스트 7. state_machine.py run_once() 재설계 — planner.plan_task() 최초 연결 (20260707)

**대상 모듈/파일**: `robot/state_machine.py` (`build_mock_task()`, `run_once()`), `ai/detector/result.py`, `ai/detector/camera.py`

**목적**: 프로젝트 시작부터 계속 "만들어놓고 한 번도 안 불리던" `planner.plan_task()`를 실제로 연결하고, `command.py`/`uart.py`의 2필드+스트리밍 변경사항에 맞춰 `run_once()` 전체를 재설계한다.

**사전 작업 — 랜덤 목업으로 전환**: AWS/실제 카메라가 아직 없는 상태에서도 파이프라인 전체(Decision Engine 포함)를 검증하기 위해, 고정값이던 `MOCK_TASK`를 매번 다른 값을 만드는 `build_mock_task()` 함수로 전환. 이 과정에서 `task`(AWS가 줄 정보: `id`, `target_label`)와 `vision`(카메라가 줄 정보: `status`)이 서로 다른 데이터라는 걸 재확인 — 처음엔 `execute_task`/`move_sign`/`status`가 전부 `task` 쪽에 섞여 들어가는 시도가 있었으나, "task와 vision은 별개의 입력이고 execute_task는 plan_task()가 계산하는 출력"이라는 점을 짚어 정리함.

- `ai/detector/result.py`: `VisionResult`에 `status: Optional[str] = None` 필드 추가 (task #3의 핵심 요구사항 선반영)
- `ai/detector/camera.py`: `MockVisionSource.read()`가 `status`를 `random.choice(["healthy","powdery_mildew","missing_plant"])`로 랜덤 생성하도록 수정
- `state_machine.py`: `build_mock_task()`가 `id`(랜덤 숫자를 문자열로)와 `target_label`(랜덤 셀)만 반환하도록 정리

**run_once() 재설계 — 코칭 진행 과정**: 5단계 변경 사항을 각각 "왜 필요한지"와 "안 하면 어떤 에러가 나는지"를 사용자가 직접 추론하도록 질문형으로 코칭함.

1. `task = MOCK_TASK` → `task = build_mock_task()`
2. `decision = plan_task(task, vision)` 신규 추가 — Decision Engine 최초 연결
3. `command = {"command": decision["execute_task"], "target": task.get("target_label")}`로 교체 (예전 7필드 `build_command()`/`ArduinoCommand` 호출 제거)
4. `send_json_line()` 단발 호출을 `for message in self.arduino.stream_progress(command):` 반복문으로 교체
5. `task["execute_task"]`를 참조하던 모든 곳(`post_response`, `print`)을 `decision["execute_task"]`로 교체

이 과정에서 실제로 발생한 버그와 코칭 포인트:
- **빈 반복 문제**: `stream_progress()`가 메시지를 하나도 못 받고 끝나면(전송 실패/타임아웃), `for` 블록 안쪽이 통째로 한 번도 실행되지 않아 `arduino_response` 변수가 아예 생성되지 않는 문제 발견. 반복문 시작 전에 `arduino_response`에 기본값(`{"state":"RECEIVED","progress":0}`)을 미리 넣어두는 방식으로 해결. (처음엔 기본값을 엉뚱한 변수(`message`)에 넣는 실수가 있었음 — "반복문이 0번 돌 때 어떤 변수가 실제로 안전한가"를 예시로 짚어 교정)
- **필드명 오류 재발**: `arduino_response.get("status", ...)` — 새 프로토콜의 실제 키는 `"status"`가 아니라 `"state"`인데 예전 프로토콜 이름이 남아있던 것을 발견, 수정 (테스트 3의 `completion_sign`→`status` 버그와 같은 종류의 실수가 반복됨).
- **`.get()` 기본값 오용**: `arduino_response.get("state", "progress")`처럼 두 번째 인자(기본값 자리)에 엉뚱하게 다른 필드 이름을 넣은 실수 발견, `"error"`로 수정.
- **`.upper()` 오해**: 사용자가 `.upper()`를 "오름차순 정렬"로 오해 — 실제로는 "문자열을 대문자로 변환"하는 기능이며, 나중에 `completion == "COMPLETE"` 같은 비교가 대소문자와 무관하게 항상 성립하도록 하기 위한 안전장치라는 점을 설명.

**최종 검증**:
```bash
pytest tests/ -q --ignore=tests/manual
```
```
16 passed
```

추가로 `run_once()`의 핵심 로직만 떼어 직접 실행하는 스모크 테스트로 파이프라인 전체가 실제로 이어지는지 확인:
```python
build_mock_task(): {'id': '838', 'target_label': 'cell_2'}
decision: {'task': {...}, 'vision': {'status': 'healthy'}, 'execute_task': 'OBSERVE'}
command: {'command': 'OBSERVE', 'target': 'cell_2'}
```
`status: healthy` → `execute_task: OBSERVE`로 정확히 계산되어 `planner.py`가 실제로 작동함을 확인.

**발생한 에러**: 이번에도 bash 마운트 동기화 지연이 재발 — `state_machine.py`가 pytest 스위트엔 직접 import하는 테스트가 없어 발견이 늦어졌고, 별도 스모크 테스트로 직접 import했을 때 `SyntaxError: '(' was never closed`로 뒤늦게 발견됨. heredoc으로 재기록해 해결. (교훈: 핵심 파일은 테스트 스위트에 없어도 주기적으로 직접 import해서 마운트 상태를 확인할 필요가 있음.)

**남은 사항**: `build_command()` 메서드(예전 7필드 방식)는 이제 아무 데서도 호출되지 않는 죽은 코드로 남음 — 삭제 여부는 보류.

**최종 결론**: `planner.plan_task()`가 프로젝트 최초로 실제 실행 흐름에 연결됨. `run_once()`가 새 2필드+스트리밍 인터페이스에 맞게 완전히 재설계 완료. 16 passed.

