# Arduino Mega2560 실제 펌웨어 기준 UART 프로토콜

Jetson-Arduino 간 통신 스펙을 실제 Mega2560 코드(스크린샷)에서 역으로 정리한 문서.
`robot/command.py`, `robot/uart.py`, `robot/state_machine.py`가 이 스펙과 정합되어야 한다.

## 요청 (Jetson → Arduino)

한 줄 JSON, 개행(`\n`)으로 끝남. 공통 키는 `command`. 명령별 추가 키는 아래 표 참고.

## 명령 목록 및 응답

| command | 추가 필드 | 응답 status | 비고 |
|---|---|---|---|
| PING | - | PONG | |
| STATUS | - | READY | |
| HOME | - | DONE | |
| MOVE | `target`(int) | DONE | LCD에 `TARGET:%d` 표시 |
| STOP | - | DONE | |
| SERVO | `angle`(int) | DONE | LCD에 `ANGLE:%d` 표시 |
| GRIP_OPEN | - | DONE | |
| GRIP_CLOSE | - | DONE | |
| WATER | - | DONE | |
| NUTRITION | - | DONE | 현재 코드상 target 등 추가 필드 안 읽음 |
| PUMP_ON | - | DONE | |
| PUMP_OFF | - | DONE | |
| LED | `state`(string, 기본값 "UNKNOWN") | DONE | |
| REPLACE | `target`(int) | DONE | LCD에 `POT:%d` 표시 |
| (JSON 파싱 실패) | - | ERROR | `command` 키 없이 `{"status":"ERROR"}`만 반환 |
| (목록에 없는 command) | - | **응답 없음** | LCD에만 "UNKNOWN" 표시, `sendResponse()` 호출 자체가 없음 — Jetson은 타임아웃/빈 응답을 받게 됨 |

## 응답 공통 형식

```json
{"status": "DONE", "command": "MOVE"}
```

`completion_sign`이라는 키는 존재하지 않는다. 지금 `robot/state_machine.py`가 읽는 키(`completion_sign`)는 실제 응답에 없으므로 항상 매칭 실패 → 매번 기본값으로 처리되고 있었다 (버그, 원래 코드에 있었음).

## 미해결 설계 질문

Decision Engine(`robot/planner.py`)의 규칙표는 `OBSERVE`/`REPLACE`/`NUTRITION`/`SKIP` 4가지 값을 쓰는데, Arduino 명령 목록에는 `REPLACE`, `NUTRITION`은 있지만 **`OBSERVE`, `SKIP`에 대응하는 명령이 없다.**

가능한 해석:
- `OBSERVE`/`SKIP`은 애초에 Arduino에 아무 것도 보내지 않는 "소프트웨어 전용" 결정이다 (물리적으로 할 일이 없으므로)
- 아니면 Arduino 쪽에 `OBSERVE`/`SKIP` 명령을 나중에 추가해야 한다

확인 필요.
