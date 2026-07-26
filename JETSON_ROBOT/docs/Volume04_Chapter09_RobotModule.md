# Chapter 9. Robot Communication Module (`robot/`)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `robot/` 디렉터리 구현을 기준으로 작성되었다.
>
> **Chapter 7과의 역할 분리 (중복 방지)**
> - Chapter 7 (Event Processing) : 수신한 이벤트를 **어떻게 분기·처리**하는가 (RobotAgent)
> - Chapter 9 (Robot Module) : RobotAgent와 Mega 사이의 **통신 계층 구현** (UART/Packet/Command)
>
> **역할 분담 (불변)**
> - Robot Module은 **Motion을 수행하지 않는다.** Motion State Machine·Inspection Strategy·Replace 판단·Cycle 제어는 Arduino Mega가 담당한다.
> - Robot Module은 RobotAgent와 Arduino Mega 사이의 **통신 계층(Communication Layer)**만 제공한다.

---

## 9.1 Overview

`robot/` 디렉터리는 RobotAgent가 Arduino Mega와 통신하기 위한 계층이다. UART로 패킷을 주고받고, 패킷을 인코딩하고, 프로토콜 메시지 상수를 정의한다.

RobotAgent(Chapter 4~7)가 "무엇을 보낼지/받은 것을 어떻게 처리할지"를 결정한다면, Robot Module은 "그 메시지를 실제로 어떻게 시리얼로 주고받는지"를 담당한다. 두 계층은 명확히 분리되어 있으며, Robot Module은 이벤트의 전체 제어 흐름을 결정하지 않는다. UART 통신, 패킷 인코딩, 프로토콜 메시지 정의와 같은 통신 계층을 제공하며, 이벤트 처리와 작업 분기는 RobotAgent가 담당한다.

Robot Module이 Motion을 수행하지 않는 이유는 STREW_VISION v2.0의 역할 분담 원칙 때문이다. Motion과 작업 판단은 실시간성이 요구되므로 Arduino Mega Firmware가 담당하고, Jetson은 통신·AI·데이터 계층만 담당한다.

---

## 9.2 Robot Module Architecture

```
                RobotAgent
                     │  (cmd 송신 / event 수신)
        ┌────────────┼────────────┐
        ▼            ▼            ▼
     uart.py     packet.py    command.py
   (송수신 I/O)  (인코딩 규칙)  (메시지 상수)
        │
        ▼
   Arduino Mega
```

각 파일의 책임:
- **`uart.py`** : 시리얼 포트 I/O (실제 바이트 송수신)
- **`packet.py`** : dict ↔ 전송 바이트 인코딩 규칙
- **`command.py`** : 프로토콜 메시지 상수 정의
- **`task_manager.py`** : Jetson 내부 작업 큐 (Motion 아님)
- **`planner.py`** : 레거시 판단 로직 (현재 미사용, 보존)

Robot Module은 Motion을 수행하지 않고, RobotAgent와 Arduino Mega 사이의 통신 계층을 제공한다.

---

## 9.3 UART Communication (`uart.py`)

`ArduinoLink` 클래스가 시리얼 통신을 담당한다. 핵심은 **쓰기와 읽기의 책임 분리**다.

### 실제 메서드

| 메서드 | 역할 |
| --- | --- |
| `__init__(port, baudrate, timeout)` | 시리얼 포트 연결 + 2초 대기 후 입력 버퍼 초기화 |
| `send_json_line(payload)` | 메시지를 **보내기만** 함 (쓰기 전용, 응답 안 읽음) |
| `_read_json_line()` | 시리얼에서 한 줄 읽어 dict로 파싱 |
| `close()` | 포트 닫기 |

### 쓰기 (`send_json_line`)

쓰기는 `_write_lock`으로 보호된다. 메인 스레드와 리스너 스레드가 동시에 쓸 수 있으므로, 한 번에 한 스레드만 시리얼에 쓰도록 보장하여 바이트가 섞이는 것을 방지한다.

```python
def send_json_line(self, payload: Dict[str, Any]) -> bool:
    if self.serial is None or not self.serial.is_open:
        return False
    with self._write_lock:
        try:
            line = encode_packet(payload)   # 인코딩은 packet.py에 위임
            self.serial.write(line)
            self.serial.flush()
            return True
        except serial.SerialException as e:
            print(f"시리얼 통신 오류: {e}")
            return False
```

### 읽기 (`_read_json_line`)

읽기는 **리스너 스레드 한 곳에서만** 호출된다(Single UART Owner). `readline()`으로 한 줄을 받아 JSON으로 파싱하며, 빈 줄(타임아웃)이면 `None`을 반환한다.

> **설계 참고.** 구버전에는 쓰기와 읽기를 한 함수에서 처리했으나, 새 프로토콜은 Mega가 먼저 말을 거는 양방향 구조라 "쓰기(`send_json_line`)"와 "읽기(`_read_json_line`)"의 책임을 완전히 분리했다.

---

## 9.4 Packet Processing (`packet.py`)

`packet.py`는 전송용 **인코딩 규칙만** 담당한다. 하드웨어를 전혀 모르며, dict를 어떤 바이트 형식으로 바꿀지의 규칙만 안다. 함수는 `encode_packet()` 하나다.

```python
def encode_packet(payload: Dict[str, Any]) -> bytes:
    """딕셔너리를 "한 줄 JSON + 개행문자" 형태의 UTF-8 바이트로 변환한다.
    예: {"cmd": "RUN"} -> b'{"cmd":"RUN"}\n'
    """
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
```

인코딩 규칙:
- `separators=(",", ":")` — 공백 없는 압축 JSON (전송량 절감)
- `ensure_ascii=False` — 한글을 이스케이프하지 않고 그대로 전송
- 끝의 `\n` — Arduino가 한 줄(패킷)의 끝을 인식하는 구분자

> **주의(코드 기준).** 현재 프로토콜은 **Checksum이나 Protocol Version 필드를 사용하지 않는다.** 패킷은 "압축 JSON + 개행" 형식이며, 무결성 검증은 JSON 파싱 성공 여부로 갈음한다. (파싱 실패 시 해당 줄은 무시된다.)

이렇게 인코딩 규칙을 `uart.py`(I/O)에서 분리한 이유는, 인코딩 방식이 바뀌어도 I/O 코드는 건드릴 필요가 없고, UART가 아닌 다른 전송 수단(MQTT 등)에서도 `encode_packet()`을 재사용할 수 있기 때문이다.

---

## 9.5 Command Definition (`command.py`)

`command.py`는 프로토콜 메시지 문자열을 상수로 정의한다. 하드코딩 오타를 방지하고, Volume 03(Mega Firmware)과 이름을 일치시키기 위한 것이다.

### Jetson → Mega (`cmd`)

| 상수 | 값 | 의미 |
| --- | --- | --- |
| `CMD_RUN` | "RUN" | 새 Cycle 시작 (cycle_id 포함) |
| `CMD_RESUME` | "RESUME" | 복구 재개 (예약, 미구현) |
| `CMD_ACK` | "ACK" | STATE 저장 완료 통보 (seq) |
| `CMD_TASK` | "TASK" | AI/관리자 결정 작업 전달 (OBSERVE/REPLACE/SKIP) |
| `CMD_PING` | "PING" | 하트비트 요청 |

### Mega → Jetson (`event`)

| 상수 | 값 | 의미 |
| --- | --- | --- |
| `EV_READY` | "READY" | 부팅/리셋 완료 |
| `EV_STATE` | "STATE" | 상태 보고 (seq, cell, state). `STATE_VISION_READY`에서는 현재 Inspection View(TOP/LEFT/RIGHT/FRONT) 정보가 함께 전달된다. |
| `EV_COMPLETE` | "COMPLETE" | Cell 작업 완료 |
| `EV_ERROR` | "ERROR" | 내부 오류 (code) |
| `EV_PONG` | "PONG" | PING 응답 |

### 상태값 / 매핑

- `STATE_VISION_READY = "VISION_READY"` — STATE의 특수 값(Inspection AI 요청 동기화 상태). Phase C에서는 현재 Inspection View(TOP / LEFT / RIGHT / FRONT) 정보와 함께 사용된다.
- `status_to_task()` — vision status → TASK 매핑 (healthy→OBSERVE, powdery_mildew/missing_plant→REPLACE, 그 외→SKIP)

```python
STATUS_TO_TASK = {
    "healthy": TASK_OBSERVE,
    "powdery_mildew": TASK_REPLACE,
    "missing_plant": TASK_REPLACE,
}
def status_to_task(status: str) -> str:
    return STATUS_TO_TASK.get(status, TASK_SKIP)
```

`status_to_task()`는 Vision Module이 생성한 `status` 값을 RobotAgent가 사용하는 `TASK` 값으로 변환하기 위한 공통 매핑 함수이다. 실제 작업 순서나 Motion을 결정하는 기능은 아니며, RobotAgent의 이벤트 처리 과정(Chapter 7)에서 호출된다. 즉 이 함수는 "인식(status) → 변환(TASK)"의 변환 단계에 해당하며, 그 TASK로 실제 Motion을 수행하는 것은 Arduino Mega다.

> **주의.** `command.py`의 매핑(`status_to_task`)은 RobotAgent가 사용하는 **현행** 로직이며, 뒤의 `planner.py`(9.7)의 레거시 매핑과는 별개다.

---

## 9.6 Task Manager (`task_manager.py`)

`TaskQueue`는 Jetson 내부에서 작업(dict)을 담아두는 단순 큐다. **Motion과 무관**하며, 작업 항목을 push/pop하는 자료구조 역할만 한다.

```python
class TaskQueue:
    def __init__(self) -> None:
        self._items: List[dict] = []

    def push(self, task: dict) -> None:
        self._items.append(task)

    def pop(self) -> Optional[dict]:
        return self._items.pop(0) if self._items else None
```

또한 폴링 주기 판단 유틸(`should_poll`)을 제공한다. Task Manager는 "작업을 어떻게 보관/순서화하는가"만 담당하고, 그 작업을 물리적으로 수행하는 것은 Arduino Mega다.

---

## 9.7 Legacy Decision Module (`planner.py`)

`planner.py`는 초기 버전에서 AI 판독 결과(status)로 작업을 결정하던 판단 모듈이다. 아키텍처 변경(결정권이 Jetson → Mega로 이전)에 따라 **현재 런타임 경로에서는 호출되지 않는다.**

```python
ACTION_MAP = {
    "healthy": "OBSERVE",
    "powdery_mildew": "REPLACE",
    "missing_plant": "REPLACE",
}
def plan_task(task: dict, vision: dict) -> dict:
    status = vision.get("status")
    execute_task = ACTION_MAP.get(status, "SKIP")
    return {"task": task, "vision": vision, "execute_task": execute_task}
```

삭제하지 않고 보존하는 이유(코드 주석 근거):
1. `tests/test_decision.py`가 이 로직을 테스트하고 있어, 삭제 시 커버리지가 사라진다.
2. 이 `ACTION_MAP`이 곧 Mega 펌웨어(C++)로 옮겨 심을 **"정답 스펙"** 역할을 한다.

즉 `planner.py`는 현재 제어 구조의 핵심 모듈이 아니라 **레거시 호환성(Backward Compatibility)을 위한 보존 모듈**이다.

```
VisionResult(status)
        │
        ▼
    planner.py
 (Legacy Mapping: ACTION_MAP)
        │
        ▼
   execute_task
        │
        ▼
  현재 Runtime에서 사용하지 않음 (미호출)
```

현재 Runtime에서는 RobotAgent가 `command.py`의 `status_to_task()`를 사용하며, `planner.py`는 레거시 호환성과 테스트를 위해 저장소에 유지된다.

---

## 9.8 Robot Module Design Principles

| 원칙 | 설명 |
| --- | --- |
| Communication Layer | Robot Module은 RobotAgent와 Mega 사이의 통신만 담당한다. |
| Protocol Fidelity | command.py의 메시지 이름을 Volume 03과 동일하게 사용한다. |
| Motion Separation | Motion·Cycle·Replace 판단은 Mega가 담당하고 Robot Module은 다루지 않는다. |
| Single UART Owner | UART 읽기는 리스너 스레드만 수행한다. 쓰기는 write_lock으로 보호한다. |
| Separation of Encoding | 인코딩 규칙(packet.py)과 I/O(uart.py)를 분리한다. |
| Loose Coupling | RobotAgent는 시리얼 세부를, uart.py는 메시지 의미를 서로 모른다. |
| Backward Compatibility | `planner.py`와 기존 프로토콜 정의를 유지하여 이전 버전과의 호환성을 확보한다. |

---

## 9.9 Summary

Robot Module(`robot/`)은 RobotAgent와 Arduino Mega 사이의 통신 계층이다. `uart.py`가 시리얼 I/O를, `packet.py`가 인코딩 규칙을, `command.py`가 프로토콜 메시지 상수를 담당한다. `task_manager.py`는 내부 작업 큐이며 Motion과 무관하고, `planner.py`는 현재 미사용 레거시 모듈로 보존된다.

Robot Module은 어떤 경우에도 Motion을 수행하거나 작업 사이클을 결정하지 않는다. 이러한 통신 계층의 분리를 통해 Jetson(통신·AI·데이터)과 Arduino Mega(실시간 Motion 제어)의 역할이 명확히 유지된다.

Phase C에서는 Multi-View Inspection을 지원하기 위해 `STATE(VISION_READY)` 메시지에 현재 Inspection View(TOP, LEFT, RIGHT, FRONT) 정보가 포함될 수 있다. 이러한 확장은 기존 Robot Module의 통신 구조를 변경하지 않으며, View 순서(TOP→LEFT→RIGHT→FRONT)는 Motion Sequence로서 Arduino Mega가 담당한다. Jetson은 각 View의 판독 결과를 누적하여 최종 판정만 수행하므로, 별도의 View 제어 메시지(예: NEXT_VIEW)는 도입하지 않는다.

---

## 부록. robot/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 역할 | Motion? |
| --- | --- | --- |
| `uart.py` | 시리얼 I/O (`ArduinoLink`: send_json_line / _read_json_line) | ✗ |
| `packet.py` | dict → 압축 JSON+개행 인코딩 (`encode_packet`) | ✗ |
| `command.py` | 프로토콜 상수 (CMD_*/EV_*) + `status_to_task` | ✗ |
| `task_manager.py` | 내부 작업 큐 (`TaskQueue`) | ✗ |
| `planner.py` | 레거시 판단 (`ACTION_MAP`, 미사용·보존) | ✗ |
| `state_machine.py` | RobotAgent (Chapter 4~7에서 다룸) | ✗ |
