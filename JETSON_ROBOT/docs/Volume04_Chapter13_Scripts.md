# Chapter 13. Scripts — 운영·유지보수 도구 (`scripts/`)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `scripts/` 디렉터리의 스크립트를 기준으로 작성되었다.
>
> **역할 (불변)**
> - `scripts/`는 **실행 중인 시스템이 아니라, 운영자가 손으로 돌리는 보조 도구**다.
> - 진단·점검·기동·시뮬레이션 — 배포와 유지보수를 돕는 Production Support Tools 계층이다.
> - 런타임(RobotAgent)과 분리되어 있어, 어떤 스크립트도 로봇의 상태(SQLite)를 바꾸지 않는다.

---

## 13.1 Overview

`scripts/` 디렉터리는 STREW_VISION의 **운영·유지보수 도구** 모음이다. Volume 04의 다른 모듈들이 "실행 중인 시스템"의 일부라면, `scripts/`는 그 시스템을 **배포하고, 점검하고, 문제를 격리하는 데 운영자가 직접 사용하는 도구**다.

Volume 04 전체 계층 안에서의 위치는 다음과 같다.

| 계층 | 모듈 | 성격 |
| --- | --- | --- |
| 런타임 | RobotAgent (`robot/`) | 실행 중인 제어 루프 |
| AWS 통신 | Cloud (`cloud/`) | 실행 중 보고·조회 |
| 상태 저장 | Storage (`storage/`) | 실행 중 상태 관리(Source of Truth) |
| 원격 업데이트 | Updater (`updater/`) | 이벤트 구동 자동 업데이트 |
| **운영/유지보수** | **Scripts (`scripts/`)** | **운영자가 손으로 돌리는 보조 도구** |

핵심 구분은 **"시스템이 돌리는 코드"가 아니라 "사람이 돌리는 도구"**라는 점이다. 스크립트는 대부분 `main.py`(런타임)와 **동시에 실행하지 않는다**. 특히 시리얼 포트를 쓰는 진단 도구는 런타임과 포트를 동시에 점유할 수 없으므로, 먼저 `main.py`를 종료하고 실행한다.

---

## 13.2 스크립트 구성

현재 `scripts/`에는 네 개의 도구가 있으며, 용도별로 두 축으로 나뉜다.

```
scripts/
├── run_agent.sh        [기동]   venv 구성 + 의존성 설치 + 로봇 실행
├── ota_preflight.py    [점검]   OTA 배포 전 환경 점검 (비파괴)
├── diag_mega.py        [진단]   Mega UART 통신만 순수 확인 (런타임 없이)
└── sim_mega_v1.py      [검증]   하드웨어 없이 프로토콜 전 흐름 시뮬레이션
```

| 스크립트 | 분류 | 하드웨어 필요 | 런타임과 동시 실행 |
| --- | --- | --- | --- |
| `run_agent.sh` | 기동(Launch) | Jetson 실기 | — (이것이 런타임을 띄움) |
| `ota_preflight.py` | 점검(Preflight) | 불필요(권장 실기) | 가능(비파괴 읽기) |
| `diag_mega.py` | 진단(Diagnose) | Mega 연결 | **불가**(포트 독점) |
| `sim_mega_v1.py` | 검증(Simulate) | **불필요** | — (가짜 Mega로 대체) |

---

## 13.3 `run_agent.sh` — 로봇 기동 런처

로봇 소프트웨어를 실행하는 진입 스크립트다. 가상환경을 만들고 의존성을 설치한 뒤 `main.py`를 실행한다.

```bash
#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m main
```

- **`set -euo pipefail`** — 오류·미정의 변수·파이프 실패 시 즉시 중단(안전한 기동).
- **`cd "$(dirname "$0")/.."`** — 스크립트 위치와 무관하게 항상 프로젝트 루트에서 실행.
- **격리 실행** — `.venv`를 만들어 의존성을 시스템과 분리한다.

**언제 사용하나** — Jetson에서 로봇 소프트웨어를 처음 띄우거나 재기동할 때. 이 스크립트가 `python -m main`으로 런타임(RobotAgent)을 시작한다.

---

## 13.4 `ota_preflight.py` — OTA 배포 전 점검 (비파괴)

실제 업데이트를 **하지 않고**, OTA가 성공하기 위한 전제 조건만 검사한다(Chapter 12 참조). Jetson에 처음 배포할 때 환경이 갖춰졌는지 한 번에 확인하는 도구다.

```bash
python3 scripts/ota_preflight.py
```

검사 항목(각각 `[OK]/[WARN]/[FAIL]` 출력):

| # | 점검 | FAIL 조건 |
| --- | --- | --- |
| 1 | git 저장소 인식 + `origin` + `fetch --dry-run` | git 저장소 아님 / origin 없음 |
| 2 | `arduino-cli` 설치 + `arduino:avr` 코어 | (없으면 WARN — 펌웨어 자동 업로드만 불가) |
| 3 | 시리얼 포트 존재(`ota_arduino_port`) | (없으면 WARN — Mega 미연결 가능) |
| 4 | `paho-mqtt` 사용 가능 | 미설치 |
| 5 | 펌웨어 스케치 경로(`mega_firmware.ino`) | (없으면 WARN) |

친절한 진단이 특징이다. 예를 들어 git `dubious ownership` 오류가 나면 해결 명령(`git config --global --add safe.directory ...`)까지 출력한다. `FAIL`이 하나도 없으면 종료코드 0, 있으면 1을 반환한다.

**언제 사용하나** — OTA를 켜기 전, 새 Jetson에 배포한 직후. "UPDATE 명령이 오면 정상 동작할 조건을 갖췄는가"를 미리 확인한다. Python 3.6 호환(subprocess `PIPE`+`universal_newlines`)을 지킨다.

---

## 13.5 `diag_mega.py` — Mega UART 통신 진단

`main.py` 없이 **순수하게 "Mega가 시리얼로 말을 하는가?"만** 확인하는 도구다. 포트를 열고 → 먼저 3초간 그냥 들어오는 바이트(부팅 메시지 등)를 관찰하고 → `{"type":"START_CYCLE"}` JSON 한 줄을 보낸 뒤 → 10초간 들어오는 모든 바이트를 **날것 그대로** 출력한다.

```bash
python3 scripts/diag_mega.py                    # 기본 /dev/ttyACM0, 115200
python3 scripts/diag_mega.py /dev/ttyUSB0 115200
```

동작:

1. 연결된 시리얼 포트 목록 출력(없으면 케이블/전원/데이터 케이블 여부 안내).
2. **[1/2]** 전송 전 3초 관찰 — 부팅 메시지 등 자발적으로 들어오는 바이트 확인.
3. **[2/2]** `{"type":"START_CYCLE"}\n` 전송 후 10초간 수신 바이트를 원시(raw)로 표시.

> 보내는 것은 문자열 "START_CYCLE"이 아니라 **JSON 한 줄 `{"type":"START_CYCLE"}`** 이다(개행 종료).

**언제 사용하나** — `main.py`의 워치독(무응답)이 반복될 때, **원인을 "펌웨어/배선"과 "Jetson 로직"으로 격리**하기 위해. 여기서 바이트가 보이면 하드웨어는 정상 → 문제는 상위 로직. 아무것도 안 오면 케이블·전원·펌웨어 문제로 좁혀진다.

> **주의.** `main.py`와 **동시에 실행할 수 없다.** 시리얼 포트를 둘이 동시에 못 쓰므로, 진단 전 반드시 `main.py`를 종료한다.

---

## 13.6 `sim_mega_v1.py` — 하드웨어 없는 프로토콜 시뮬레이션

실제 Arduino 없이, `mega_firmware.ino`와 동일한 프로토콜로 응답하는 **가짜 Mega(`FakeMega`)**를 파이썬으로 구현한다. `ArduinoLink`를 monkeypatch로 이 가짜에 물려서 RobotAgent의 전체 흐름을 콘솔에서 눈으로 확인한다.

```bash
python3 scripts/sim_mega_v1.py          # AWS 없이(mock) 1 Cycle 시뮬레이션
```

검증하는 흐름(현재 코드는 **Phase C 멀티뷰**까지 반영):

```
READY → RUN
  └─ 셀마다:  MOVE_CELL/ACK
              → [ VISION_READY(view)/ACK ] × 4  (TOP→LEFT→RIGHT→FRONT)
              → TASK 수신(4장 종합)
              → TASK_DONE/ACK → COMPLETE
  └─ 4셀 순회 후 IDLE                                  (+ PING/PONG 상시)
```

구현 방식:

- **`FakeMega`** — `.ino`의 STATE→ACK 핸드셰이크, 셀 순회, COMPLETE 이벤트를 그대로 흉내낸다. `VIEWS = ("TOP","LEFT","RIGHT","FRONT")`를 **Mega가 스스로 순회**하며(Phase C 방식 ②), 각 View마다 `VISION_READY(view)`를 STATE로 올리고 ACK를 받으면 다음 View로 넘어간다. **마지막(4번째) View 이후에야 Jetson이 TASK를 보내면** 물리 동작(가상)을 수행한다 — 즉 `NEXT_VIEW` 명령 없이 Mega 자가 순회 구조를 시뮬레이션한다.
- **monkeypatch** — `sm.ArduinoLink`를 `FakeArduinoLink`로, `sm.MqttClient`를 스텁(`FakeMqtt`)으로 교체한다. 따라서 시리얼·MQTT·비전 하드웨어 없이 RobotAgent 로직만 순수 검증한다.
- **mock 모드** — `Config` 기본값(`aws_enabled=False`, `vision_mode=mock`)을 그대로 써서 AWS 없이 독립 실행된다.

**언제 사용하나** — 하드웨어가 없는 개발 PC나 CI에서 RobotAgent의 이벤트 흐름(READY/RUN/STATE/ACK, 4 View 순회, TASK/TASK_DONE/COMPLETE, 하트비트)이 깨지지 않았는지 빠르게 확인할 때. 실기 없이 회귀 검증이 가능하다.

> 이름의 `v1`은 **Mega 펌웨어 v1.0 프로토콜**을 흉내낸다는 뜻이다. 프로토콜이 바뀌면(예: Phase C View 순회) 이 시뮬레이터도 함께 갱신해야 실기와 일치가 유지된다. 실제로 현재 파일은 4 View 순회를 반영하도록 갱신돼 있다.

---

## 13.7 운영 환경에서의 사용 시점

시간 순서로 보면 스크립트들은 로봇 생애주기의 각 지점에 대응한다.

```
[개발/CI]        sim_mega_v1.py     — 하드웨어 없이 로직 회귀 검증
     │
[Jetson 최초 배포] ota_preflight.py   — 환경(git/arduino/포트/mqtt) 점검
     │
[기동]           run_agent.sh        — venv 구성 + 로봇 실행
     │
[문제 발생 시]    diag_mega.py        — main.py 종료 후 UART 통신 격리 진단
```

즉 `sim`은 배포 **전**, `preflight`는 배포 **직후**, `run_agent`는 **기동**, `diag`는 **장애 진단** 시점의 도구다.

---

## 13.8 Design Principles

| 원칙 | 설명 |
| --- | --- |
| Tools, Not Runtime | 스크립트는 실행 중인 시스템이 아니라 운영자가 손으로 돌리는 도구다. |
| Non-Destructive by Default | 점검·진단·시뮬레이션은 상태(SQLite)를 바꾸지 않는다. |
| Isolate the Fault | `diag_mega`는 하드웨어 문제와 로직 문제를 분리해준다(포트 독점 → main.py와 배타 실행). |
| Hardware-Optional Verification | `sim_mega_v1`은 실기 없이 프로토콜 전 흐름을 검증한다. |
| Fail Fast Launch | `run_agent.sh`는 `set -euo pipefail`로 문제 발생 시 즉시 중단. |
| Jetson-Compatible | preflight/진단은 Python 3.6 호환 subprocess 규약을 지킨다. |
| Actionable Diagnostics | 실패 시 원인뿐 아니라 **해결 명령**까지 안내한다(예: safe.directory). |

---

## 13.9 Summary

`scripts/` 디렉터리는 STREW_VISION의 **운영·유지보수 도구(Production Support Tools)** 계층이다. 네 개의 도구가 로봇 생애주기의 각 지점을 담당한다 — `sim_mega_v1.py`(하드웨어 없는 프로토콜 검증), `ota_preflight.py`(배포 전 비파괴 환경 점검), `run_agent.sh`(venv 구성 + 기동), `diag_mega.py`(UART 통신 격리 진단).

이 스크립트들의 공통 성격은 **"실행 중인 시스템"이 아니라 "운영자가 사용하는 보조 도구"**라는 것이다. 어떤 스크립트도 로봇의 상태를 대신 관리하지 않는다 — 상태의 기준은 여전히 SQLite(Chapter 10)이며, 스크립트는 그 시스템을 배포하고 점검하고 문제를 격리하는 것을 돕는다. 진단·점검 도구가 대부분 비파괴이고, 시리얼을 쓰는 도구는 런타임과 배타적으로 실행된다는 점이 이 계층의 안전 규약이다.

---

## 부록. scripts/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 분류 | 역할 | 실행 |
| --- | --- | --- | --- |
| `run_agent.sh` | 기동 | venv 생성 + requirements 설치 + `python -m main` | `bash scripts/run_agent.sh` |
| `ota_preflight.py` | 점검 | OTA 전제조건 5종 비파괴 검사 | `python3 scripts/ota_preflight.py` |
| `diag_mega.py` | 진단 | Mega UART 원시 통신 확인(main.py 종료 후) | `python3 scripts/diag_mega.py [port] [baud]` |
| `sim_mega_v1.py` | 검증 | FakeMega로 프로토콜 전 흐름(4 View 순회 포함) 시뮬레이션(하드웨어 불필요) | `python3 scripts/sim_mega_v1.py` |
