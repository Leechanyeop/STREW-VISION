# 03. Mega 펌웨어 + UART v1.0 프로토콜

## 통신 개요
Jetson(Master) ↔ Mega(Slave), 시리얼 115200, JSON 한 줄(`\n` 종료). 필드 분리:
- **Jetson→Mega = `"cmd"`**, **Mega→Jetson = `"event"`**.
- 파일: Jetson `robot/uart.py`(ArduinoLink), `robot/command.py`(상수), Mega `mega_firmware/mega_firmware.ino`.
- 포트: `ARDUINO_PORT=/dev/ttyACM0`, `ARDUINO_BAUDRATE=115200`.

## 메시지
**Jetson → Mega (cmd):**
| cmd | 필드 | 의미 |
|---|---|---|
| RUN | cycle_id | 새 사이클(항상 Cell 1부터) |
| RESUME | cell, task, state | 복구 재개(SQLite 기준 cell부터) |
| ACK | seq | STATE 저장 완료 → 다음 진행 허용 |
| TASK | task(OBSERVE/REPLACE/SKIP) | 4-View 검사 후 최종 결정 |
| PING | - | 하트비트 |

**Mega → Jetson (event):**
| event | 필드 | 의미 |
|---|---|---|
| READY | - | 부팅 완료 → Jetson이 RUN/RESUME 응답 |
| STATE | seq, cell, state, (view) | 상태 완료 보고. ACK 받아야 다음 진행 |
| COMPLETE | cell | 셀 작업 완료(ACK 불필요) |
| ERROR | code | 내부 오류 |
| PONG | - | PING 응답 |

`state` 값: `MOVE_CELL`, `VISION_READY`(AI 요청 동기화 지점), `TASK_DONE`.

## 핵심 핸드셰이크 규칙
- 모든 STATE는 **seq**를 달고, Jetson이 **같은 seq로 ACK**해야 Mega가 다음으로 진행.
- **VISION_READY**는 "완료 보고"가 아니라 "AI 요청 트리거". Jetson이 AI 판독 후 **TASK**를 내려야 물리 동작 시작.
- PING/PONG 하트비트: 1초 주기, 3회(≈5초) 무응답 = Mega Offline.

## 4-View Multi-View Inspection (Phase C)
- 모든 셀에서 **TOP/LEFT/RIGHT/FRONT 4개 View 고정 촬영**. NEXT_VIEW 명령 없음 — STATE→ACK만으로 순회.
- Mega가 View마다 `STATE(VISION_READY, view)` 보냄 → Jetson ACK → 다음 View. **마지막(4번째) View 후에만
  Jetson이 TASK를 추가로 보냄**(종합 판정 `aggregate_views`).
- Jetson `_target_view_count()` = SQLite `max_view`(기본 4). **Mega `VIEW_COUNT=4`와 반드시 일치.**

## Mega 상태머신 (runCycleStep, non-blocking)
```
CS_MOVE_TO_CELL → STATE(MOVE_CELL) → CS_WAIT_MOVE_ACK
 → CS_MOVE_TO_VIEW(4회) → STATE(VISION_READY,view) → CS_WAIT_VIEW_ACK
   (마지막 View + TASK 도착) → CS_EXECUTE_ACTION(ACTION_TOTAL_MS=2.5s)
 → CS_SEND_DONE → STATE(TASK_DONE) → CS_WAIT_DONE_ACK
 → CS_ADVANCE → COMPLETE(cell) → (cell<TOTAL_CELLS? 다음셀 : IDLE)
```
- `TOTAL_CELLS = 4` (펌웨어 상수). **Jetson `total_cells`와 반드시 일치** — 안 맞으면 사이클 데드락.
- 물리 동작 함수(`moveToCell/moveToView/executePhysicalTask/returnToHome`)는 **전부 TODO 빈 껍데기**.
  실제 모터 배선 전까지 시간만 흉내(ACTION_TOTAL_MS 지연만 있음). 그래서 셀이 빨리 지나감(정상).

## LCD 표시 (2026-08-04 추가)
16x2 I2C LCD(주소 0x27). `lcdStatus()`로 상태 표시. 반영하려면 **Arduino IDE로 재업로드** 필요.
```
STREW ROBOT / READY      (부팅)
Cell 1/4 / MOVE          (셀 이동)
Cell 1/4 / VIEW:TOP      (각 View)
Cell 1/4 / TASK:REPLACE  (작업 결정)
Cell 1/4 / DONE          (셀 완료)
STREW   IDLE / wait RUN  (사이클 끝)
```
LCD 안 바뀌면: 재업로드 확인 / I2C 배선·주소 / (통신 자체는 READY·STATE 로그로 확인).

## 연속 순회 (무한 반복)
- Jetson `_on_complete`: 마지막 셀(`cell >= total_cells`) COMPLETE 시 3초 뒤 `_begin_new_cycle()` 자동.
- `cycle_count=0`이면 무한, `>0`이면 그 횟수. **total_cells가 안 맞으면 마지막 셀 판정이 안 돼 무한순회 실패.**

## 시뮬레이터
`scripts/sim_mega_v1.py` - Mega 없이 프로토콜 테스트용 가짜 Mega. `scripts/diag_mega.py` - UART 진단.
