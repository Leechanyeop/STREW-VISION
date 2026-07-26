# Chapter 4. RobotAgent (Application Core)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 파일 `robot/state_machine.py`의 구현을 기준으로 작성되었으며,
> 인용된 코드는 저장소의 실제 코드와 1:1로 대응한다.
> (Minimum Change Policy: 문서 구조 = 코드 구조)

---

## 4.1 Overview

`RobotAgent`(`robot/state_machine.py`)는 Jetson Nano Software의 **애플리케이션 코어(Application Core)**다. `main.py`가 생성하는 이 객체 하나가 시스템의 모든 하위 모듈을 초기화하고, Arduino Mega와의 이벤트 통신을 관리하며, AI·저장·클라우드 처리를 오케스트레이션한다.

파일명은 `state_machine.py`이지만, 실제로는 자체 상태 기계(State Machine)를 실행하지 않는다. Arduino Mega가 전송하는 이벤트를 수신하여 적절한 처리 모듈로 분배하는 **Event Dispatcher**로 동작한다. Motion State Machine은 Arduino Mega가 담당하며, Jetson은 상태를 두 곳에서 관리하지 않는다.

클래스 docstring이 이 역할을 명시한다.

```python
class RobotAgent:
    """Jetson(Master) 측 UART Protocol v1.0 구현.

    역할: AI(vision) 수행, DB(AWS) 저장, 관리자 승인 처리, UART 관리, 하트비트.
    모터/물리 동작은 전혀 안 한다(그건 Mega). Jetson은 명령(cmd)을 주고 상태(event)를 받는다.
    """
```

---

## 4.2 Initialization (`__init__`)

`RobotAgent` 생성 시 하위 모듈이 **다음 순서**로 초기화된다. 이 순서는 실제 코드의 순서이며, 통신·저장·AI가 모두 준비된 뒤에만 스레드가 시작된다.

| 순서 | 초기화 대상 | 구현 | 담당 모듈 |
| --- | --- | --- | --- |
| 1 | 설정 | `self.cfg = cfg` | config/settings.py |
| 2 | AWS REST | `CloudClient(...)` | cloud/api_client.py |
| 3 | AI 추론 소스 | `create_vision_source(...)` | ai/detector/camera.py |
| 4 | UART | `ArduinoLink(...)` | robot/uart.py |
| 5 | MQTT | `MqttClient()` | cloud/mqtt.py |
| 6 | AWS 재시도 큐 | `CloudSync(...)` | cloud/sync.py |
| 7 | ESP32 센서 브리지 | `SensorBridge(...)` (조건부) | cloud/sensor_bridge.py |
| 8 | OTA 서비스 | `OtaService(...)` (조건부) | updater/ |
| 9 | MQTT 연결/구독 | `mqtt_client.connect(...)` | cloud/mqtt.py |
| 10 | 상태 DB (SQLite) | `StateDB(cfg.state_db_path)` | storage/state_db.py |
| 11 | 스레드 2개 시작 | Listener + Heartbeat | (본 클래스) |

핵심 초기화 코드는 다음과 같다.

```python
def __init__(self, cfg: Config) -> None:
    self.cfg = cfg
    self.cloud = CloudClient(cfg.aws_api_base, cfg.api_key)
    self.vision = create_vision_source(
        cfg.vision_mode, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path,
    )
    self.arduino = ArduinoLink(cfg.arduino_port, cfg.arduino_baudrate)
    self.mqtt_client = MqttClient()
    self.cloud_sync = CloudSync(self.cloud)
```

### 4.2.1 상태 DB (Source of Truth)

SQLite는 v2.0에서 추가된 상태 관리 계층이며, 상태의 기준(Source of Truth)이다. DB 초기화에 실패하더라도 로봇 동작 자체는 멈추지 않도록 예외를 흡수한다.

```python
# [2026-07-25 v2.0] 상태 관리 SQLite (Source of Truth). STATE 받을 때마다 저장하고
# Recovery의 기준으로 삼는다. DB 초기화 실패해도 로봇 동작은 계속(무시)한다.
self.state_db = None
try:
    from storage.state_db import StateDB
    self.state_db = StateDB(cfg.state_db_path)
except Exception as e:
    print(f"[SQLite] 초기화 실패(무시하고 계속): {e}")
```

### 4.2.2 운영 상태 변수

초기화 마지막에 런타임 상태 변수가 설정된다.

```python
self.current_task = None        # 현재 Cycle의 AWS task (COMPLETE/ERROR 릴레이 기준)
self.cycle_active = False
self.awaiting_decision = False  # 관리자 판단 대기 중 여부 (하트비트 유예용)
self.last_pong_time = time.monotonic()
self.mega_online = True
self._offline_reported = False
```

---

## 4.3 Threads (Listener & Heartbeat)

초기화 마지막에 두 개의 데몬 스레드가 시작된다. **UART 읽기는 Listener 스레드 하나만 수행**하여(단일 소유자) 동시성 충돌을 원천 차단한다.

```python
# UART 읽기는 리스너 스레드 하나만 한다(단일 소유자). 쓰기는 write_lock으로 보호됨.
self._listener = threading.Thread(target=self._uart_listener_loop, daemon=True)
self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
self._listener.start()
self._heartbeat.start()
```

### 4.3.1 Heartbeat Thread

1초 주기로 `PING`을 전송하고, `HEARTBEAT_TIMEOUT_SEC`(3초)를 초과해 `PONG`이 없으면 Mega Offline로 판정한다. 단, 관리자 판단 대기(`awaiting_decision`) 중에는 Listener 스레드가 폴링으로 블로킹되어 PONG을 못 읽는 정상 상황이므로 오프라인 판정을 유예한다.

```python
HEARTBEAT_INTERVAL_SEC = 1.0
HEARTBEAT_TIMEOUT_SEC = 3.0

def _heartbeat_loop(self) -> None:
    while True:
        time.sleep(HEARTBEAT_INTERVAL_SEC)
        self.arduino.send_json_line({"cmd": CMD_PING})

        if self.awaiting_decision:
            continue  # 판단 대기 중엔 오프라인 판정 유예

        silence = time.monotonic() - self.last_pong_time
        if silence > HEARTBEAT_TIMEOUT_SEC:
            ...  # Offline 판정 + AWS 보고 (1회만)
```

### 4.3.2 UART Listener Thread

Mega가 보내는 이벤트를 수신하여 종류별로 분배한다. `PONG`은 하트비트 시각만 갱신하고, 나머지는 각 핸들러로 넘긴다.

```python
def _uart_listener_loop(self) -> None:
    while True:
        msg = self.arduino._read_json_line()
        if msg is None:
            continue

        event = msg.get("event")
        if event == EV_PONG:
            self.last_pong_time = time.monotonic()
            continue
        if event == EV_READY:
            self._on_ready()
        elif event == EV_STATE:
            self._on_state(msg)
        elif event == EV_COMPLETE:
            self._on_complete(msg)
        elif event == EV_ERROR:
            self._on_error(msg)
        # 알 수 없는 event는 무시.
```

---

## 4.4 Event Dispatch

수신 이벤트별 처리 흐름을 요약하면 다음과 같다.

```
Wait UART Packet → Decode → Event Dispatch
   ├─ READY               → RUN 전송 (SQLite: 새 Cycle 기록)
   ├─ STATE(VISION_READY) → SQLite 저장 → ACK → AI 추론 → TASK 전송
   ├─ STATE               → SQLite 저장 → ACK 전송
   ├─ COMPLETE            → SQLite 저장 → Cloud 업로드
   ├─ ERROR               → Cloud 보고
   └─ PONG                → Heartbeat 갱신
```

### 4.4.1 READY → RUN

Mega 부팅/리셋 완료 신호. AWS에서 task를 확보(미연동 시 mock cycle_id 생성)하고, SQLite에 새 Cycle을 기록한 뒤 `RUN`을 전송한다.

```python
def _on_ready(self) -> None:
    self.last_pong_time = time.monotonic()  # READY도 살아있음의 신호
    print("[READY] Mega 부팅 완료 - Cycle 준비")
    if self.cfg.aws_enabled:
        task = self.cloud.next_task(self.cfg.robot_id)
        if not task:
            print("[READY] 대기 중인 작업 없음 - RUN 보류")
            return
    else:
        task = {"id": build_mock_cycle_id()}

    self.current_task = task
    self.cycle_active = True
    cycle_id = task["id"]
    # SQLite: 새 Cycle 시작을 Source of Truth에 기록.
    self._db_update(cycle_id=cycle_id, cell_id=None, state="RUN", status="RUNNING")
    self.arduino.send_json_line({"cmd": CMD_RUN, "cycle_id": cycle_id})
    print(f"[RUN] cycle_id={cycle_id} 전송")
```

### 4.4.2 STATE → SQLite → ACK

모든 STATE는 우선 **로컬 SQLite에 먼저 저장**된다. AWS/네트워크가 끊겨도 Recovery가 가능해야 하므로, AWS 릴레이보다 로컬 저장이 우선이다. 이후 `ACK`를 전송하며, `VISION_READY`인 경우에만 AI 추론 단계로 진입한다.

```python
def _on_state(self, msg: Dict[str, Any]) -> None:
    seq = msg.get("seq")
    cell = msg.get("cell")
    state = msg.get("state")

    # [v2.0] Source of Truth 먼저 갱신 - AWS/네트워크가 끊겨도 Recovery 가능해야 하므로
    # AWS 릴레이보다 로컬 SQLite 저장이 우선이다.
    cycle_id = self.current_task["id"] if self.current_task else None
    self._db_update(cycle_id=cycle_id, cell_id=cell, state=state, status="RUNNING")

    # 진행상황을 AWS로 릴레이(있으면 좋은 정보 - 실패해도 무시).
    ...

    # 스펙: STATE는 반드시 ACK. VISION_READY도 ACK를 먼저 보낸다.
    self.arduino.send_json_line({"cmd": CMD_ACK, "seq": seq})

    # VISION_READY는 "완료 보고"가 아니라 "AI 요청 동기화 지점".
    if state == STATE_VISION_READY:
        self._handle_vision_ready()
```

### 4.4.3 VISION_READY → AI → TASK

`VISION_READY`는 완료 보고가 아니라 **AI 요청 동기화 지점**이다. Jetson은 이 시점에 AI 추론을 수행하고, 병해충 의심 판독이면 관리자 판단을 대기한 뒤, 최종 결정을 `TASK`(OBSERVE/REPLACE/SKIP)로 Mega에 내려준다. Mega는 TASK를 받아야 물리 동작을 시작한다.

```python
def _handle_vision_ready(self) -> None:
    vision = self.vision.read().to_payload()
    status = vision.get("status")
    ...
    # 병해충 의심이면 관리자 판단(승인)을 기다린 뒤 TASK 결정
```

> **참고.** v2.0에서 관리자 승인 대상은 **REPLACE에 한정**되며, 라이브 스트리밍(WebRTC) 대신 Inspection 사진 5장 캡처 방식으로 대체될 예정이다(해당 로직은 Chapter 5 Vision Manager에서 상세히 다룬다).

### 4.4.4 COMPLETE / ERROR

`COMPLETE`는 셀 작업 완료로, SQLite 저장 후 Cloud로 업로드한다. `ERROR`는 Mega 내부 오류로, 에러 코드와 함께 Cloud에 보고한다.

---

## 4.5 SQLite Helper (`_db_update`)

`current_task` 갱신은 이 헬퍼로 일원화한다. DB가 없거나 실패해도 **로봇 동작은 절대 막지 않는다**(예외 흡수).

```python
def _db_update(self, cycle_id=None, cell_id=None, state=None, task=None, view=None, status="RUNNING"):
    if self.state_db is None:
        return
    try:
        self.state_db.update_current_task(
            cycle_id=cycle_id, cell_id=cell_id, state=state, task=task, view=view, status=status
        )
    except Exception as e:
        print(f"[SQLite] 상태 저장 실패(무시): {e}")
```

---

## 4.6 Main Loop (`run_forever`)

`run_forever()`는 실제 작업 루프가 아니다. Listener·Heartbeat 스레드가 모든 실질 작업을 수행하므로, 이 메서드는 프로세스를 살아있게 유지하는 역할만 한다.

```python
def run_forever(self) -> None:
    # 리스너/하트비트 스레드가 모든 일을 하므로 메인은 살아있기만 하면 된다.
    try:
        while True:
            time.sleep(1.0)
    finally:
        self.close()
```

---

## 4.7 Orchestration Role & Summary

`RobotAgent`는 각 모듈의 내부 구현을 알지 못한 채, 정의된 인터페이스만으로 이들을 조율하는 **오케스트레이터**다.

- **초기화**: Config → Cloud → AI → UART → MQTT → SQLite → 스레드
- **이벤트 수신·분배**: Listener 스레드가 READY/STATE/COMPLETE/ERROR/PONG를 처리
- **연결 감시**: Heartbeat 스레드가 PING/PONG로 Mega 생사 확인
- **상태 관리**: 모든 STATE를 SQLite(Source of Truth)에 우선 저장
- **오케스트레이션**: AI·Storage·Cloud 모듈을 이벤트 흐름에 따라 호출

Jetson Nano Software의 실질적 동작은 대부분 이 클래스에서 이루어진다. 이후 Chapter 5~11에서 다루는 각 모듈(`ai/`, `robot/`, `storage/`, `cloud/`, `updater/`, `config/`)은 모두 `RobotAgent`가 호출하는 기능 단위로 연결된다.

---

## 부록 A. RobotAgent 공개 메서드 맵 (GPT/협업자 참고용)

| 메서드 | 역할 | 호출 시점 |
| --- | --- | --- |
| `__init__(cfg)` | 전체 초기화 + 스레드 시작 | main.py에서 1회 |
| `run_forever()` | 프로세스 유지 루프 | main.py에서 호출 |
| `_uart_listener_loop()` | 이벤트 수신·분배 (스레드) | 상시 |
| `_heartbeat_loop()` | PING/PONG 감시 (스레드) | 상시 |
| `_on_ready()` | READY→RUN | READY 수신 |
| `_on_state(msg)` | STATE→SQLite→ACK(→AI) | STATE 수신 |
| `_handle_vision_ready()` | AI 추론→관리자 승인→TASK | VISION_READY 시 |
| `_on_complete(msg)` | 완료 저장→Cloud | COMPLETE 수신 |
| `_on_error(msg)` | 에러 Cloud 보고 | ERROR 수신 |
| `_db_update(...)` | current_task 갱신 (예외 흡수) | 상태 변경 시 |
| `_await_admin_decision(...)` | 판단요청 생성 + 관리자 응답 폴링 | 병해충 의심 시 |
| `close()` | 자원 정리 | 종료 시 |

## 부록 B. 향후 확장 지점 (Roadmap)

- **Phase B (Recovery)**: `_on_ready()`에서 SQLite `current_task`(status=RUNNING) 조회 → `RESUME` 전송 분기 추가. Mega 펌웨어 EEPROM 제거.
- **Phase C (Inspection)**: `_handle_vision_ready()`를 다중 View(TOP/LEFT/RIGHT/LOW/FRONT) + confidence threshold 반복 추론으로 확장. `inspection_images` 저장 및 사진 5장 캡처.
- **WebRTC 제거**: `_await_admin_decision()`의 라이브 스트림 로직을 사진 5장 캡처로 대체. `robot/webrtc_publisher.py` 제거.
