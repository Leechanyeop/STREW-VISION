# Chapter 7. Event Processing

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 파일 `robot/state_machine.py`의 이벤트 처리 구현을 기준으로 작성되었으며,
> 인용된 코드·이벤트 이름은 Volume 03(Mega Firmware) 및 UART Protocol과 1:1로 대응한다.
>
> **역할 분담 원칙 (본 장 전체에서 불변)**
> - Arduino Mega : Motion State Machine, Inspection Strategy, Replace 판단, **Cycle 제어**
> - Jetson (RobotAgent) : 이벤트 수신, AI 추론, **TASK 생성**, SQLite 저장, Cloud 연동
> RobotAgent는 검사 사이클을 **결정하지 않는다**. Cycle의 시작·진행·종료는 Mega가 주도하며,
> RobotAgent는 Mega가 보낸 이벤트에 반응할 뿐이다.

---

## 7.1 Overview

Chapter 6에서는 RobotAgent가 두 개의 백그라운드 스레드로 운영되는 Runtime Architecture를 설명하였다. 본 장에서는 그중 **UART Listener Thread**가 수신한 이벤트를 RobotAgent가 어떻게 분기·처리하는지를 다룬다.

STREW_VISION v2.0의 Jetson은 스스로 작업을 만들지 않는다. Arduino Mega가 Cycle을 주도하며 상태 변화가 있을 때마다 이벤트(Packet)를 전송하고, RobotAgent는 그 **이벤트 종류에 따라** 필요한 모듈을 호출한다. 따라서 Event Processing은 Jetson Software의 실질적 제어 흐름이 시작되는 지점이다.

본 장은 SQLite·AI·UART의 내부 구현이 아니라, **"이벤트가 들어왔을 때 RobotAgent가 어떻게 분기하는가"**만을 설명한다.

---

## 7.2 Event Dispatcher

모든 이벤트는 `_uart_listener_loop()` 하나에서 수신·분배된다. UART 읽기는 이 스레드만 수행한다(Single UART Owner). 수신 패킷은 `event` 필드로 종류를 판별하여 각 핸들러로 분기한다.

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

분기 대상 이벤트는 Volume 03에서 정의한 이벤트 이름을 그대로 사용한다: `READY`, `STATE`, `COMPLETE`, `ERROR`, `PONG`. 새 이벤트는 만들지 않는다. (`VISION_READY`는 별도 이벤트가 아니라 `STATE`의 `state` 값이다 — 7.5 참고.)

---

## 7.3 READY Event

Mega 부팅/리셋 완료 신호. RobotAgent는 AWS에서 작업(task)을 확보하고(미연동 시 mock cycle_id 생성), SQLite에 새 Cycle을 기록한 뒤 `RUN` 명령을 전송한다.

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
    self._db_update(cycle_id=cycle_id, cell_id=None, state="RUN", status="RUNNING")
    self.arduino.send_json_line({"cmd": CMD_RUN, "cycle_id": cycle_id})
    print(f"[RUN] cycle_id={cycle_id} 전송")
```

```
READY (Mega → Jetson)
   → task 확보 + SQLite 기록
   → RUN (Jetson → Mega)
```

RUN을 받은 이후의 Cycle 진행은 전적으로 Mega가 관리한다.

---

## 7.4 STATE Event

Mega가 한 상태를 완료할 때마다 전송한다. RobotAgent는 **로컬 SQLite에 먼저 저장**하고(네트워크가 끊겨도 Recovery가 가능해야 하므로 AWS 릴레이보다 우선), `ACK`를 회신한다. UART Protocol의 STATE→ACK 핸드셰이크를 그대로 따른다.

```python
def _on_state(self, msg: Dict[str, Any]) -> None:
    seq = msg.get("seq")
    cell = msg.get("cell")
    state = msg.get("state")

    # Source of Truth 먼저 갱신 (AWS 릴레이보다 로컬 SQLite 저장이 우선)
    cycle_id = self.current_task["id"] if self.current_task else None
    self._db_update(cycle_id=cycle_id, cell_id=cell, state=state, status="RUNNING")

    # 진행상황 AWS 릴레이 (실패해도 무시)
    ...

    # STATE는 반드시 ACK
    self.arduino.send_json_line({"cmd": CMD_ACK, "seq": seq})

    # VISION_READY만 AI 단계로 진입
    if state == STATE_VISION_READY:
        self._handle_vision_ready()
```

```
STATE (Mega → Jetson)
   → SQLite 저장
   → ACK (Jetson → Mega)
   → (state == VISION_READY 인 경우에만) AI 처리
```

---

## 7.5 VISION_READY Event (핵심)

`VISION_READY`는 별도 이벤트가 아니라 **STATE의 `state` 값**이며, "완료 보고"가 아니라 **AI 요청 동기화 지점**이다. Mega가 특정 셀에서 촬영 준비를 마쳤음을 알리는 시점으로, 이때 RobotAgent가 AI 추론을 수행한다.

처리 순서:
1. Vision 추론 수행 (`self.vision.read()`)
2. Vision 이벤트를 AWS에 기록 (id 확보 — 병해충 판단요청용)
3. 병해충 의심이면 **관리자 판단(승인)** 대기, 정상 판독이면 자동 진행
4. 최종 status를 TASK(OBSERVE/REPLACE/SKIP)로 변환하여 Mega에 전송

```python
def _handle_vision_ready(self) -> None:
    vision = self.vision.read().to_payload()
    status = vision.get("status")

    vision_event_id = None
    if self.cfg.aws_enabled:
        try:
            event = self.cloud.post_vision_event(self.cfg.robot_id, vision)
            vision_event_id = event.get("id")
        except Exception as e:
            print(f"[!] vision 이벤트 기록 실패(무시하고 진행): {e}")

    # 병해충 의심이면 관리자 판단을 기다린다(정상 판독은 그대로 자동 진행).
    if self.cfg.aws_enabled and status in DISEASE_SUSPECT_STATUSES:
        status = self._await_admin_decision(status, vision_event_id)

    task = status_to_task(status)
    self.arduino.send_json_line({"cmd": CMD_TASK, "task": task})
    print(f"[TASK] vision={status} -> {task} 전송")
```

```
Mega → STATE(VISION_READY)
   → AI Detection (Jetson)
   → Inspection Result (status)
   → (병해충 의심 시) 관리자 승인 대기
   → TASK (Jetson → Mega)
   → Mega가 물리 동작 수행
```

> **중요.** RobotAgent는 여기서 **Replace 여부를 스스로 결정하지 않는다.** 판독 결과(status)를 규칙에 따라 TASK로 변환할 뿐이며, 병해충 의심 케이스의 최종 결정은 관리자 승인(AWS Dashboard)이 담당한다. Replace를 실행하는 Motion 판단·수행은 Mega가 담당한다.
>
> **로드맵(Phase C).** 향후 이 단계는 다중 View(TOP/LEFT/RIGHT/LOW/FRONT) + confidence threshold 반복 추론으로 확장되며, 관리자 승인은 라이브 스트리밍 대신 Inspection 사진 5장 캡처를 검토하는 방식으로 대체된다.

---

## 7.6 COMPLETE Event

셀 작업이 완료되면 Mega가 전송한다. RobotAgent는 SQLite에 완료 상태를 기록하고 AWS로 결과를 업로드한다.

```python
def _on_complete(self, msg: Dict[str, Any]) -> None:
    print(f"[COMPLETE] {msg}")
    cell = msg.get("cell")
    cycle_id = self.current_task["id"] if self.current_task else None
    self._db_update(cycle_id=cycle_id, cell_id=cell, state="COMPLETE", status="COMPLETE")
    if self.cfg.aws_enabled and self.current_task is not None:
        self.cloud_sync.try_send(
            self.cloud.post_response, ...,
            completion_sign="DONE", message="Mega cell complete", payload={"mega_report": msg},
        )
```

```
COMPLETE (Mega → Jetson)
   → SQLite 저장 (status=COMPLETE)
   → Cloud Upload
```

---

## 7.7 ERROR Event

Mega 내부 런타임 오류. RobotAgent는 에러 코드와 함께 AWS로 보고한다(로컬 로그 출력 포함). 오류 자체의 물리적 복구는 사람/Mega의 몫이며, Jetson은 이를 기록·전파한다.

```python
def _on_error(self, msg: Dict[str, Any]) -> None:
    code = msg.get("code", "UNKNOWN")
    print(f"[!!!] Mega ERROR: code={code} raw={msg}")
    if self.cfg.aws_enabled and self.current_task is not None:
        self.cloud_sync.try_send(
            self.cloud.post_response, ...,
            execute_task="ERROR", completion_sign="ERROR", message=f"Mega error: {code}",
        )
```

```
ERROR (Mega → Jetson)
   → Log
   → Cloud 보고
```

---

## 7.8 PONG Event

Heartbeat 응답. Dispatcher에서 최우선으로 처리되며, 마지막 수신 시각만 갱신하고 즉시 다음 패킷을 기다린다.

```python
if event == EV_PONG:
    self.last_pong_time = time.monotonic()
    continue
```

PING 전송과 Offline 판정(3초 무응답)은 별도의 Heartbeat Thread가 수행한다(Chapter 6 참고). PONG 수신은 Listener Thread에서, PING 전송·감시는 Heartbeat Thread에서 이루어지는 분리 구조다.

---

## 7.9 Event Processing Principles

| 원칙 | 설명 |
| --- | --- |
| Event-Driven | 이벤트가 수신된 경우에만 해당 처리를 수행한다. |
| Single UART Owner | UART 읽기는 Listener Thread만 수행한다. |
| Local-First State | STATE는 AWS 릴레이보다 로컬 SQLite에 먼저 저장한다. |
| Protocol Fidelity | READY/STATE/COMPLETE/ERROR/PONG/ACK/TASK/RUN 이름·시퀀스를 Volume 03 그대로 사용한다. |
| Motion = Mega | Cycle 제어·Inspection Strategy·Replace 판단·Motion은 Mega가 담당한다. |
| AI = Jetson | AI 추론·TASK 생성·SQLite 저장·Cloud 연동은 Jetson이 담당한다. |

---

## 7.10 Summary

Event Processing은 RobotAgent의 핵심 제어 흐름이다. `_uart_listener_loop()`가 Mega의 이벤트를 수신하여 `READY→RUN`, `STATE→SQLite→ACK`, `VISION_READY→AI→TASK`, `COMPLETE→Cloud`, `ERROR→보고`, `PONG→Heartbeat` 로 분기한다.

이 과정에서 RobotAgent는 검사 사이클을 결정하지 않는다. Cycle의 주도권은 Arduino Mega에 있으며, Jetson은 이벤트에 반응하여 AI 추론과 데이터 처리를 수행하는 상위 제어 계층으로 동작한다. 이러한 역할 분담을 통해 Volume 03(Mega)과 Volume 04(Jetson)가 하나의 시스템으로 정합된다.

---

## 부록. 이벤트 → 핸들러 → 응답 매핑 (GPT/협업자 참고용)

| 수신 이벤트 (Mega→Jetson) | 핸들러 | Jetson 처리 | 응답 (Jetson→Mega) |
| --- | --- | --- | --- |
| `READY` | `_on_ready` | task 확보 + SQLite 기록 | `RUN` (cycle_id) |
| `STATE` | `_on_state` | SQLite 저장 | `ACK` (seq) |
| `STATE(VISION_READY)` | `_handle_vision_ready` | AI 추론 + (승인) | `ACK` + `TASK` |
| `COMPLETE` | `_on_complete` | SQLite + Cloud 업로드 | — |
| `ERROR` | `_on_error` | Log + Cloud 보고 | — |
| `PONG` | (dispatcher inline) | last_pong_time 갱신 | — |

> **주의(문서 검증용).** 실제 코드의 AI 처리 핸들러 이름은 `_handle_vision_ready()`다. (`_handle_detection()`이라는 함수는 존재하지 않는다.)
