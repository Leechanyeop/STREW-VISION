# Arduino Mega2560 UART 프로토콜 (2026-07-16 6차 개정 — ERROR 복구 정책 v6: EEPROM 기반 nextCell 재개)

## 5차 개정 사유 (2026-07-16, 요약)

병해충 감시 중 AI가 의심 판독(`powdery_mildew`)을 내면, 이제 Jetson이 즉시 `VISION_RESULT`를 회신하지 않고 AWS에 "판단 요청"을 만들어 **관리자가 실제로 확인(치료/오탐)할 때까지 응답을 미룬다.** 자동 시퀀스가 기본 방향으로 확정되면서, 이 예외적인 경우에만 사람이 개입하도록 설계됨. **이건 `REQUEST_VISION`→`VISION_RESULT` 사이의 대기 시간이 몇 초가 아니라 몇 분(때로는 그 이상)까지 늘어날 수 있다는 뜻이라 Mega 펌웨어 쪽에 중요한 영향이 있다** — 아래 "병해충 의심 판단 대기" 절과 "알려진 미해결 사항"의 수정된 항목을 반드시 확인할 것.

`mega_firmware/mega_firmware.ino`, `robot/command.py`, `robot/uart.py`, `robot/state_machine.py`가 이 스펙과 정합되어야 한다. **이번 2차 개정은 같은 날 있었던 1차 개정(제어 권한 이전)을 대체하는 게 아니라 그 위에 쌓는 것이다** — 1차 개정에서는 "판단은 Mega가 한다"까지만 정했는데, 이번 2차 개정에서 "1~4번 셀 전체 순회 자체를 Mega가 관리한다"는 것과 Mega의 상위 동작 상태(IDLE/RUN/ERROR)가 추가로 확정됨.

## 6차 개정 사유 (2026-07-16, ERROR 복구 정책 v6 — 요약)

기존(v5) ERROR 복구는 항상 Cell1부터 다시 시작했다 — 가장 단순하고 안전하지만, Cell3에서 오류가 나도 Cell1→Cell2를 다시 반복해야 하는 낭비가 있었다. v6은 **"셀 하나가 정상적으로 완료될 때마다 EEPROM에 다음에 시작할 셀 번호(`nextCell`)를 저장"**해서, ERROR 복구 시 처음부터가 아니라 마지막으로 완료된 셀의 다음 셀부터 재개하도록 바꾼다.

**핵심 설계 원칙 — 복구 대상은 "현재 위치"가 아니라 "다음에 할 셀 번호"다.** 지금 하드웨어엔 엔코더/절대 위치 센서/토크 센서가 하나도 없어서, 모터 스텝 수나 서보 각도 같은 물리 좌표를 EEPROM에 저장해봤자 리셋 후 그게 실제로 맞는 위치인지 확인할 방법이 없다. 반면 "다음엔 몇 번 셀을 하면 되는지"는 순수 논리 상태라 신뢰할 수 있다 — 재개할 땐 항상 HOME으로 이동한 뒤 그 셀 번호로 이동해서 **처음부터**(비전 재확인 포함) 다시 작업한다.

- **EEPROM 갱신 시점**: 모터가 움직일 때마다가 아니라, 셀 하나의 `REPORT_RESULT` 전송 직후(= 그 셀 작업이 정상 완료된 시점)에만 1회 쓴다. 4번 셀까지 다 끝나면 `nextCell=1`로 되돌려 저장한다.
- **Jetson은 변경 없음**: `START_CYCLE`은 여전히 셀 지정 없이 보낸다. 어느 셀부터 시작할지는 전부 Mega가 부팅 시 EEPROM을 읽어서 스스로 판단한다.
- **SKIP도 "완료"로 취급**: 물리 동작이 없는 SKIP(예: `empty_cell`)이어도 그 셀 처리 자체는 끝난 것이므로 EEPROM을 갱신한다.
- **EEPROM 출고 초기값 처리(설계 문서에 없던 부분, 구현 시 추가)**: 한 번도 쓴 적 없는 EEPROM은 보통 0xFF(255)로 읽힌다. 저장된 값이 1~4 범위를 벗어나면(첫 부팅 등) 안전하게 1번부터 시작하도록 폴백한다.
- **EEPROM 쓰기 수명 고려**: AVR EEPROM은 주소당 쓰기 수명이 약 10만 회로 한정돼 있다. `EEPROM.write()` 대신 값이 바뀔 때만 실제로 쓰는 `EEPROM.update()`를 사용해 불필요한 마모를 줄인다 — 특히 같은 셀에서 ERROR가 반복돼 같은 `nextCell` 값을 계속 저장하려는 경우에 효과적이다. 다만 정상적인 순회는 매번 값이 바뀌므로(1→2→3→4→1) 이 최적화만으로 마모 문제가 완전히 사라지는 건 아니다 — 아주 빈번한 무인 운전이 예상되면 여러 주소를 돌려쓰는 웨어 레벨링 도입을 나중에 고려할 것.
- **병해충 판단 대기 중 ERROR가 나는 예외 상황(알려진 상호작용)**: Mega가 `VISION_RESULT`를 기다리는(=관리자 판단 대기 중인) 도중에 물리적으로 리셋되면, 그 시점의 판단 요청/스트림 세션은 그냥 버려진다. 재개 시 그 셀은 비전 재확인부터 처음부터 다시 하므로 안전은 유지되지만, 관리자가 이미 낸 판단(치료/오탐)은 낭비되고 새로 판독해서 필요하면 새 판단 요청이 다시 생성된다.

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
- 상수는 `robot/command.py`에 정의되어 있다: `MSG_START_CYCLE`, `MSG_REQUEST_VISION`, `MSG_VISION_RESULT`, `MSG_PROGRESS_UPDATE`, `MSG_REPORT_RESULT`, `MSG_CYCLE_COMPLETE`, `MSG_ERROR`. (`MSG_ASSIGN_TARGET`은 1차 개정에서 정의했으나 **이번 2차 개정으로 사용 중단** — 하위 호환/이력 추적 목적으로 상수만 남아있음. `MSG_RESET`은 3차 개정에서 도입했으나 **이번 4차 개정으로 완전히 제거됨** — 아래 "ERROR 복구 방법" 참고.)

## 메시지 7종 (`ASSIGN_TARGET`은 사용 중단, `RESET`은 4차 개정에서 제거됨 — 목록에서 제외)

| type | 방향 | 필드 | 의미 |
|---|---|---|---|
| `START_CYCLE` | Jetson → Mega | (없음) | "순회 시작해"만 알려줌. **셀 지정 없음** — 1~4번 중 어디로 갈지는 전부 Mega가 자체 관리. Mega는 이 메시지를 받으면 IDLE → RUN 전환. 한 순회당 1회, `run_once()`가 보냄(단, Mega가 이미 RUN 중이면 Jetson은 다시 보내지 않음 — `cycle_active` 플래그로 방지). |
| `REQUEST_VISION` | **Mega → Jetson** | (없음) | Mega가 순회 중 셀마다 필요할 때 보냄(위치 도착 직후, REPLACE 완료 후 검증 시 등). 한 순회에 여러 번(최대 8회: 4개 셀 × 최초 확인 + REPLACE 시 재확인). |
| `VISION_RESULT` | Jetson → Mega | `status`(문자열: `healthy`/`powdery_mildew`/`missing_plant`/`empty_cell`) | `REQUEST_VISION`에 대한 응답. **날것의 vision 판단 결과만** 담음. **(2026-07-16 5차 개정) `status`가 병해충 의심(`powdery_mildew`)이면 이 응답이 몇 초가 아니라 몇 분 이상 걸릴 수 있음** — Jetson이 관리자 판단을 기다리기 때문. 아래 "병해충 의심 판단 대기" 절 참고. |
| `PROGRESS_UPDATE` | **Mega → Jetson** | `target`(문자열, 셀 라벨), `state`(문자열, Mega 내부 상태머신 상태), `progress`(정수 0~100, 선택) | 순회 중 "지금 몇 번 셀에서 무슨 단계인지"를 알려주는 **정보성 메시지 — 응답 불필요**. |
| `REPORT_RESULT` | **Mega → Jetson** | `target`, `execute_task`(REPLACE/OBSERVE/SKIP), `completion`, `success`(선택) | **셀 하나 처리 결과.** 한 순회(1~4번)당 최대 4회 옴(셀마다 1번씩). |
| `CYCLE_COMPLETE` | **Mega → Jetson** | (없음, 필요하면 요약 필드 추가 협의 가능) | **전체 순회(1~4번) 완료 + 초기 위치 복귀 + IDLE 전환** 신호. 한 순회당 1회. Jetson은 이 신호를 받아야 다음 `START_CYCLE`을 보낼 수 있음. |
| `ERROR` | **Mega → Jetson** | `reason`(문자열, 선택 — 사람이 원인 파악할 때 참고용) | 내부 문제로 비상 정지(ERROR 상태 전환) 시 즉시 전송. Jetson은 이걸 받으면 **자동으로 다음 순회를 트리거하지 않음**(사람이 물리적으로 확인하고 재시작하기 전까지 대기). 복구는 항상 물리 리셋 — 아래 "ERROR 복구 방법" 참고. |

### ERROR 복구 방법 (2026-07-15 4차 개정 — 단순화됨)

> **이력**: 3차 개정에서는 ERROR에 `severity`(`"minor"`/`"critical"`) 필드를 붙이고 `minor`일 때만 Jetson이 `RESET` 메시지로 원격 재시작시키는 경로를 만들었었다. 그런데 실제 하드웨어에 전류 센서/엔코더/리밋스위치 등 **물리 상태를 확인할 센서가 하나도 없다는 게 확인되어**, "이 문제가 가벼운 건지 심각한 건지"를 Mega가 스스로 판단할 근거 자체가 없다는 결론에 도달했다. 구분 못 하는 걸 억지로 구분하는 척 하는 게 오히려 위험하다고 판단해, **severity 구분과 `RESET` 메시지를 4차 개정에서 완전히 제거**했다.

지금은 단순하다: **ERROR는 항상 물리적으로 확인이 필요한 상태**로 취급한다. 원격으로 소프트웨어만으로 재시작시키는 방법은 없다 — 사람이 로봇을 직접 확인하고 전원을 재시작(또는 리셋 버튼)해야만 ERROR에서 복구된다. Jetson도 ERROR를 받으면 `cycle_active`를 계속 `True`로 유지해서, 사람이 물리적으로 재시작하지 않는 한 다음 `START_CYCLE`을 자동으로 보내지 않는다(전원이 재시작되면 Jetson 쪽 프로세스도 처음부터 다시 뜨므로 자연스럽게 초기화됨).

**Mega 펌웨어가 신경 써야 할 건 딱 하나**: ERROR 상태로 들어가면 그 어떤 원격 메시지로도 자동 복구되지 않게(즉 별도 처리 없이 그냥 계속 ERROR 상태를 유지) 만들면 된다. 원격 RESET을 거부하는 로직 자체를 별도로 짤 필요도 없어졌다 — 애초에 그런 메시지가 안 온다.

**물리 리셋 이후 "어디서부터 재개할지"는 6차 개정(아래 참고)으로 달라졌다** — 이 절에서 정한 "복구는 항상 물리 리셋"이라는 원칙 자체는 그대로 유지되고, 리셋 이후 Cell1부터 할지 마지막에 완료된 셀의 다음부터 할지만 바뀐 것이다.

### ERROR 복구 시 재개 지점 — EEPROM 기반 nextCell (2026-07-16 6차 개정 — 신규)

**목적**: 구현 복잡도 최소화, 안전성 확보, 그리고 이미 끝낸 셀들을 처음부터 다시 반복하지 않도록 하는 것.

**EEPROM 저장 값**: `nextCell`(1~4) 하나만 저장한다. "다음에 시작할 셀 번호"를 의미하며, "지금 로봇이 물리적으로 어디 있는지"를 의미하지 않는다.

| EEPROM 값 | 의미 |
|---|---|
| 1 | Cell1부터 시작 |
| 2 | Cell2부터 시작 |
| 3 | Cell3부터 시작 |
| 4 | Cell4부터 시작 |

**정상 동작 시 갱신 흐름**:

```
START -> Cell1 완료 -> EEPROM=2 -> Cell2 완료 -> EEPROM=3
      -> Cell3 완료 -> EEPROM=4 -> Cell4 완료 -> EEPROM=1
```

즉 항상 "다음 셀"을 저장한다. 갱신 시점은 **셀 하나의 작업이 정상적으로 완료된 직후(`REPORT_RESULT` 전송 직후)뿐**이다 — 모터가 움직일 때마다 쓰는 게 아니다. 이렇게 하면 사이클당 EEPROM 쓰기가 딱 4회로 매우 적고, 중간에 오류가 나도 마지막으로 완료된 셀 기준으로 안전하게 복구할 수 있다.

**ERROR 발생 시 예시** (Cell2 작업 중 ERROR):

```
Cell1 완료 -> EEPROM=2 -> Cell2 작업 중 -> ERROR
   -> 사람 확인 -> Mega 물리 리셋 -> Arduino 부팅 -> setup()에서 EEPROM 읽기(nextCell=2)
   -> IDLE 대기 -> Jetson: START_CYCLE(셀 지정 없음, 평소와 동일)
   -> Mega: EEPROM의 nextCell=2를 그대로 써서 Cell2부터 재개(HOME 경유, 비전 재확인부터 처음부터)
   -> Cell2 완료 -> EEPROM=3 -> Cell3 진행 ...
```

**Jetson은 아무것도 몰라도 된다** — `START_CYCLE`은 이전과 똑같이 셀 지정 없이 보낸다. "Cell2부터 해" 같은 별도 명령을 Jetson이 만들어 보낼 필요가 전혀 없다. 어느 셀부터 시작할지는 전부 Mega가 부팅 시 EEPROM을 읽어서 내부적으로 판단한다.

**왜 "현재 위치"가 아니라 "다음 셀 번호"인가**: 지금 하드웨어엔 엔코더, 절대 위치 센서, 토크 센서가 하나도 없다. 예를 들어 "LM Guide = 3520step, Servo = 120°" 같은 물리 좌표를 저장해봤자, 리셋 후 실제로 그 위치에 있는지 확인할 방법이 없다(전원이 나갔다 들어오는 과정에서 물리적으로 밀렸을 수도 있음). 반면 "다음 Cell = 2"는 순수 논리 상태라 신뢰할 수 있고, EEPROM에 저장하기 적합하다. 대신 이 방식이 안전하려면 **각 셀의 작업이 처음부터 다시 실행되어도 문제가 없어야 한다** — 이미 만족되고 있음: Mega는 셀을 방문할 때마다 매번 `REQUEST_VISION`으로 비전을 새로 확인하지, 이전에 캐시된 판단을 재사용하지 않는다(재개든 최초 방문이든 동일한 코드 경로).

**구현상 추가로 필요했던 안전장치 두 가지** (설계 문서엔 없었지만 실제 구현 시 필요해서 추가함):
1. 출고 상태(한 번도 쓴 적 없는) EEPROM은 보통 0xFF(255)로 읽힌다. `nextCell` 값이 1~4 범위를 벗어나면 1번부터 시작하도록 안전하게 폴백한다.
2. `EEPROM.write()` 대신 `EEPROM.update()`를 쓴다 - 이전과 같은 값이면 실제 쓰기를 생략해 EEPROM 쓰기 수명(주소당 약 10만 회)을 아낀다.

**알려진 상호작용**: 병해충 의심 판단 대기(`REQUEST_VISION`→`VISION_RESULT` 사이에 관리자 응답을 몇 분씩 기다리는 상황) 도중 Mega가 물리적으로 리셋되면, 그 판단 요청/스트림 세션은 버려진다. 재개 시 그 셀은 비전 재확인부터 다시 하므로 안전은 유지되지만 관리자가 이미 낸 판단은 낭비된다 - 자주 발생하는 상황은 아니라고 보지만 알려진 사항으로 남겨둠.

### 무응답 워치독 (Jetson 쪽에 이미 구현됨, 변경 없음)

Mega가 `ERROR`조차 보내지 못하고 그냥 응답 없이 멈추는 경우(크래시, 완전 정지 등)를 대비해, Jetson은 순회 중(`cycle_active=True`) 마지막으로 UART 메시지를 받은 시각을 계속 추적한다. `MEGA_SILENCE_TIMEOUT_SEC`(현재 120초, 실측 후 조정 필요) 동안 아무 메시지도 없으면 무응답 정지로 간주해 AWS에 알리고, `ERROR`와 동일하게 취급해 자동 재시작을 막는다(사람이 물리적으로 확인 후 재시작해야 함). **이건 Jetson 단독으로 구현 가능한 부분이라 이미 반영했고, Mega 쪽에서 별도로 할 일은 없다** — 다만 Mega가 살아있는 한 어떤 형태로든 주기적으로 무언가(`PROGRESS_UPDATE` 등)를 보내주면 이 워치독이 오작동(정상인데 오래 조용해서 타임아웃)할 가능성이 줄어든다.

### 병해충 의심 판단 대기 (2026-07-16 5차 개정 — 신규)

`VISION_RESULT`의 `status`가 `powdery_mildew`(병해충 의심)로 나오면, Jetson은 즉시 회신하지 않고 다음을 한다:

1. AWS에 "판단 요청"을 생성한다(vision 이벤트 id + 의심 라벨 첨부).
2. 관리자가 이 요청을 보고 `treat`(병징 확정) 또는 `ignore`(오탐)로 응답할 때까지 **몇 초 간격으로 폴링하며 기다린다.** 응답 대기 시간엔 상한이 없다 — 관리자가 답할 때까지 기다린다.
3. 응답을 받으면 그제서야 `VISION_RESULT`를 Mega에 보낸다: `treat`면 원래 판독값(`powdery_mildew`) 그대로, `ignore`면 `healthy`로 바꿔서 보낸다(Mega는 오탐으로 보고 그냥 다음 셀로 넘어감).
4. (예외) AWS 연결 자체가 안 되거나 판단 요청 생성이 실패하면, 관리자에게 물어볼 방법이 없으므로 대기 없이 원래 판독값 그대로 즉시 회신한다.

**Jetson 쪽은 이 대기 시간 동안 무응답 워치독(위 절)을 꺼둔다** — Mega가 멈춘 게 아니라 사람 응답을 기다리는 정상 상황이기 때문. 하지만 **Mega 펌웨어 쪽은 이 사실을 반드시 알아야 한다**: `REQUEST_VISION`을 보낸 뒤 `VISION_RESULT`가 몇 초 안에 안 온다고 해서 절대 스스로 타임아웃 처리(ERROR 전환 등)를 하면 안 된다 — 특히 의심 판독 케이스에서는 응답이 수 분 이상 걸리는 게 정상이다. 아래 "알려진 미해결 사항"의 관련 항목이 수정됨(예전엔 5~10초 타임아웃을 권장했었는데, 이제는 그러면 안 됨).

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
- ~~`ERROR` 수신 후 재시작 방법 미설계~~ → **해결됨(3차 개정 → 4차 개정에서 단순화).** 처음엔 `severity`(minor/critical) 구분 + `RESET` 메시지를 만들었으나, 물리 센서가 없어 Mega가 그 구분을 스스로 할 근거가 없다는 게 확인되어 **4차 개정에서 전부 제거**. 지금은 ERROR = 항상 물리 리셋으로만 복구(위 "ERROR 복구 방법" 참고). Mega 쪽이 별도로 구현할 것도 없어짐(RESET 거부 로직 자체가 불필요해짐).
- ~~Mega가 응답 없이 조용히 멈추는 경우 미대응~~ → **Jetson 쪽은 해결됨(3차 개정, 무응답 워치독).** Mega 쪽은 별도로 할 일 없음(위 참고).
- **데드락/타임아웃 위험 — 부분 미해결, 2026-07-16 5차 개정으로 요구사항 변경됨.** `_uart_listener_loop()`의 `vision.read()` 호출 자체엔 아직 타임아웃이 없다(Jetson 쪽 보완 예정). ~~Mega 펌웨어는 `REQUEST_VISION` 전송 후 일정 시간(예: 5~10초) 안에 `VISION_RESULT`가 안 오면 반드시 타임아웃 처리(ERROR 전환 등)를 구현해야 한다~~ → **이 권장사항은 취소됨.** 병해충 의심 판독 시 관리자 판단을 기다리느라 `VISION_RESULT`가 수 분 이상 걸릴 수 있는 게 이제 정상 상황이라, Mega가 짧은 시간(5~10초) 안에 응답 없다고 타임아웃 처리하면 정상적인 관리자 대기 흐름을 오작동으로 끊어버리게 된다. **Mega 펌웨어는 `REQUEST_VISION` 이후 `VISION_RESULT`를 기다리는 동안 자체 타임아웃을 두지 말거나(권장), 꼭 둬야 한다면 최소 30분 이상의 매우 넉넉한 값으로 설정해야 한다.**
- ~~시리얼 쓰기 동시 접근 위험~~ → **해결됨(4차 개정).** `robot/uart.py`의 `ArduinoLink`에 `threading.Lock`을 추가해 `send_json_line()` 전체를 감쌈 — 어느 스레드가 부르든 한 번에 한 스레드만 쓸 수 있음. Mega 쪽에서도 JSON 파싱 실패 시 그냥 무시하고 다음 줄을 기다리는 방어 코드는 여전히 권장.
- **구버전(1차 개정 포함)의 상태머신/`ArduinoCommand`/`stream_progress()`는 새 흐름에서 더 이상 호출되지 않는다.** 삭제 여부는 별도 결정 필요.
- ~~Mega 펌웨어(`mega_firmware.ino`) 자체는 아직 이 신규 프로토콜에 맞춰 재작성 전~~ → **해결됨.** `mega_firmware/mega_firmware.ino`가 이 문서(5차/6차 개정 포함)와 정합되도록 새로 작성됨 — IDLE/RUN/ERROR, START_CYCLE~ERROR 메시지 7종, ACTION_MAP 포팅, EEPROM 기반 nextCell 복구까지 전부 반영. 단, 모터/그리퍼/카메라 자세 제어 등 물리 동작 함수들은 실제 배선 정보가 없어서 placeholder 상태 — 실제 로봇에 올리기 전 해당 함수들부터 채워야 함(파일 상단 TODO 목록 참고).
- **EEPROM 웨어 레벨링 미적용.** 6차 개정에서 `EEPROM.update()`로 불필요한 쓰기는 줄였지만, 정상 순회는 매 셀마다 값이 바뀌므로(1→2→3→4→1) 여전히 고정된 한 주소(주소 0)만 계속 쓴다. 아주 빈번한 무인 연속 운전이 예상되면(예: 하루 수십 회 이상 사이클) 여러 주소를 돌려쓰는 웨어 레벨링 도입을 고려할 것 - 지금 예상 운영 빈도에선 우선순위 낮음.

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
- **2026-07-15(같은 날, 2차): `PROGRESS_UPDATE` 추가.**
- **2026-07-15(같은 날, 3차): 순회 사이클 관리를 Mega로 이전. `ASSIGN_TARGET` → `START_CYCLE`/`CYCLE_COMPLETE`로 대체, IDLE/RUN/ERROR 상태 확정, ERROR에 `severity`(minor/critical) + `RESET` 메시지 + 무응답 워치독 추가, 시리얼 쓰기 Lock 추가.**
- **2026-07-15(같은 날, 4차): `severity`/`RESET`을 통째로 제거하고 단순화.** 물리 센서(전류/엔코더/리밋스위치 등)가 하나도 없어서 Mega가 "가벼운 문제인지 심각한 문제인지"를 스스로 판단할 근거가 없다는 게 확인됨 — ERROR는 이제 항상 물리 리셋으로만 복구.
- **2026-07-16(5차): 병해충 의심 판독 시 관리자 판단 대기 추가.** 자동 시퀀스가 기본으로 확정되면서, `powdery_mildew` 의심 판독이 나온 경우에만 예외적으로 Jetson이 AWS에 판단 요청을 만들고 관리자 응답(treat/ignore)을 기다렸다가 `VISION_RESULT`를 회신하도록 변경. 이 대기 시간 동안 Jetson 쪽 무응답 워치독은 꺼지도록 예외 처리함(`awaiting_decision` 플래그). 이에 따라 예전에 권장했던 "Mega의 5~10초 `VISION_RESULT` 타임아웃" 요구사항은 취소됨 — 관리자 대기가 수 분 이상 걸리는 게 정상이기 때문. 이후 IMX708 영상을 WebRTC로 관리자에게 실시간 스트리밍하는 기능(AWS StreamSession 시그널링 + Jetson aiortc publisher + 관리자 대시보드 라이브뷰)과 `mega_firmware.ino` 실제 구현이 모두 완료됨.
- **2026-07-16(6차): ERROR 복구 정책 v6 — EEPROM 기반 nextCell 재개 도입.** 기존(5차 이전)엔 ERROR 복구 시 항상 Cell1부터 다시 시작했으나, 셀 하나가 정상 완료될 때마다(`REPORT_RESULT` 전송 직후) EEPROM에 "다음에 시작할 셀 번호"만 저장해뒀다가, 물리 리셋 후 그 값부터 재개하도록 변경. 복구 대상이 "현재 물리 위치"가 아니라 "다음 셀 번호"인 이유는 엔코더/절대 위치/토크 센서가 전혀 없는 현재 하드웨어 제약 때문(위 "ERROR 복구 시 재개 지점" 절 참고). Jetson `state_machine.py`나 AWS 쪽은 변경 사항 없음(`START_CYCLE` 인터페이스가 그대로라서) — `mega_firmware.ino`에만 반영됨.
