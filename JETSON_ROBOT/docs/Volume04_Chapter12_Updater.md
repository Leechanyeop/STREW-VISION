# Chapter 12. Updater Module — 원격 자동 업데이트 (OTA)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `updater/` 디렉터리와 OTA 배선 코드를 기준으로 작성되었다.
>
> **역할 (불변)**
> - OTA는 코드를 GitHub에 push하면 현장의 Jetson이 **스스로 최신 코드를 내려받아 반영**하는 원격 업데이트 계층이다.
> - MQTT 브로커를 외부에 직접 공개하지 않고, **AWS FastAPI가 GitHub↔MQTT 중계**를 담당한다.
> - 업데이트 실패 시 **이전 커밋으로 롤백**하여 깨진 상태를 남기지 않는다.

---

## 12.1 Overview

`updater/` 디렉터리는 Jetson의 **무인 원격 업데이트(OTA, Over-The-Air)**를 담당한다. 온실 현장에 배치된 로봇에 사람이 직접 접속해 `git pull` 하지 않아도, 코드를 GitHub에 push하면 로봇이 스스로 최신 코드와 펌웨어를 반영한다.

핵심 설계 원칙은 세 가지다.

- **중계 구조** — MQTT 브로커를 인터넷에 노출하지 않는다. GitHub Actions는 HTTPS로 AWS를 호출하고, AWS가 내부 MQTT로 UPDATE 명령을 발행한다.
- **원자성(롤백)** — pip / 컴파일 / 펌웨어 업로드 중 어느 단계라도 실패하면 `git reset --hard`로 이전 커밋으로 되돌린다. 반쯤 적용된 상태를 남기지 않는다.
- **Jetson Nano 호환** — JetPack 기본 Python 3.6 환경을 전제로 한다. 모든 subprocess 호출은 `capture_output`/`text`(3.7+) 대신 `PIPE` + `universal_newlines`를 쓴다.

버전은 **날짜 기반 문자열**(예: `20260723164200`)이다. Jetson은 마지막으로 적용한 버전을 로컬 상태 파일(`.ota_state`)에 보관하고, 같은 버전이 다시 오면 `git fetch`도 없이 즉시 종료한다(`ALREADY_LATEST`).

---

## 12.2 End-to-End Flow

```
[개발자] git push
    │
    ▼
[GitHub Actions] ota-update.yml
    · version = date +%Y%m%d%H%M%S   (날짜 기반)
    · POST https://<AWS>/api/ota/update  {command:UPDATE, version}  + X-API-Key
    │
    ▼
[AWS FastAPI] /api/ota/update
    · publish_once(MQTT robot/system/update, {command:UPDATE, version})
    │   └─ 브로커를 외부에 공개하지 않기 위한 중계 지점
    ▼
[Jetson MQTT] robot/system/update 구독
    · MqttClient.on_update → OtaService.on_update_message
    ▼
[Jetson] UpdateManager.handle_update_command
    · 락 확인 → 버전 비교 → git fetch/pull → pip → 펌웨어 → 헬스체크 → 재시작
    │
    ├── MQTT robot/system/status ──▶ (상태 보고)
    └── HTTP POST /robot/ota-status ──▶ AWS ──▶ Dashboard
```

이 흐름의 핵심은 **AWS가 GitHub와 MQTT 사이의 중계자**라는 점이다. GitHub Actions는 브로커 주소나 자격증명을 모른 채 HTTPS 한 번만 호출하고, 실제 MQTT 발행은 AWS 내부에서 일어난다.

---

## 12.3 Trigger Side — GitHub Actions & AWS 중계

### GitHub Actions (`.github/workflows/ota-update.yml`)

push가 일어나면 워크플로가 날짜 기반 버전을 만들고 AWS를 호출한다.

```yaml
- name: Generate date-based version
  run: echo "version=$(date +%Y%m%d%H%M%S)" >> "$GITHUB_OUTPUT"
# ...
  run: |
    curl -sS -X POST "$BASE/api/ota/update" \
      -H "X-API-Key: ..." \
      -d "{\"command\":\"UPDATE\",\"version\":\"$VERSION\"}"
```

### AWS 중계 (`app/main.py` — `POST /api/ota/update`)

AWS는 이 HTTPS 호출을 받아 내부 MQTT로 UPDATE를 발행한다. 브로커를 외부에 직접 열지 않기 위한 **유일한 진입점**이다.

```python
@app.post("/api/ota/update", dependencies=[Depends(require_api_key)])
def trigger_ota_update(payload: OtaUpdateCommand) -> dict:
    body = {"command": "UPDATE", "version": payload.version}
    publish_once(settings.mqtt_broker_host, settings.mqtt_broker_port,
                 settings.ota_update_topic, json.dumps(body))
    return {"published": True, "topic": settings.ota_update_topic, "version": payload.version}
```

---

## 12.4 Receive Side — MQTT 구독과 OtaService (`ota_service.py`)

`OtaService`는 `MqttClient`와 `UpdateManager`를 잇는 **배선(wiring)** 계층이다. RobotAgent 초기화 시 기동되며(`cfg.ota_enabled`가 참일 때), MQTT `robot/system/update`를 구독하다가 UPDATE 명령이 오면 UpdateManager를 돌리고, 결과를 **MQTT status 토픽 + AWS HTTP 양쪽**으로 보고한다.

> **주의 — RobotAgent가 OTA를 실행하는 것이 아니다.** RobotAgent는 초기화 시점에 OtaService를 "구독 등록"만 할 뿐, 업데이트를 직접 호출하지 않는다. OTA는 **MQTT 이벤트가 OtaService를 깨우는** 구조다. 즉 실행 흐름은 `RobotAgent → OtaService`가 아니라 `MQTT robot/system/update → MqttClient.on_update() → OtaService → UpdateManager`이며, RobotAgent는 이 경로 바깥에서 로봇 제어를 계속 수행한다.

```python
class OtaService:
    def __init__(self, cfg, mqtt_client, cloud_client=None, arduino_link=None):
        self.manager = UpdateManager(
            repo_dir=cfg.ota_repo_dir,
            publish_status=self._report_status,
            release_uart_fn=self._release_uart,   # 펌웨어 업로드 전 UART 해제
            health_check_fn=self._health_check,
            arduino_fqbn=cfg.ota_arduino_fqbn,
            arduino_port=cfg.ota_arduino_port,
            firmware_sketch_dir=cfg.ota_firmware_sketch,
        )
        mqtt_client.on_update = self.on_update_message   # 콜백 등록
```

세 가지 콜백이 UpdateManager에 주입된다는 점이 중요하다. 덕분에 UpdateManager 자체는 하드웨어·네트워크를 몰라도 되고, 테스트가 가능해진다.

- **`_release_uart`** — `arduino_link.close()`. arduino-cli가 시리얼 포트를 쓰려면 `main.py`가 포트를 놓아줘야 하므로, 펌웨어 업로드 직전에 UART를 닫는다.
- **`_health_check`** — 업데이트 후 최소 점검. 현재는 가볍게 `True`를 반환하고, 상세 점검(Mega ping/UART)은 재시작 후 하트비트로 이뤄진다.
- **`_report_status`** — 상태를 ① MQTT status 토픽 `publish`와 ② AWS `post_ota_status` 양쪽으로 보낸다. 둘 다 실패해도 예외를 흡수한다(보고 실패가 업데이트를 막지 않는다).

RobotAgent에서의 실제 구독 배선(`state_machine.py`):

```python
self.ota_service = None
if getattr(cfg, "ota_enabled", False):
    self.ota_service = OtaService(cfg, self.mqtt_client, self.cloud, arduino_link=self.arduino)

self.mqtt_client.connect(
    cfg.aws_mqtt_broker, cfg.aws_mqtt_topic, cfg.aws_mqtt_port,
    update_topic=cfg.ota_update_topic if self.ota_service is not None else None,
)
```

> OTA 서비스 초기화가 실패해도 `try/except`로 흡수하고 로봇 동작은 계속한다. OTA는 부가 기능이지 제어의 전제 조건이 아니다.

---

## 12.5 UpdateManager — 업데이트 실행 엔진 (`update_manager.py`)

`UpdateManager`가 실제 업데이트 절차를 수행한다. 모든 쉘 명령은 `CommandRunner`를 통해 실행되고, 재시작·UART 해제·헬스체크는 콜백으로 주입되므로 **하드웨어 없이 테스트 가능**하다.

### 12.5.1 명령 진입 — `handle_update_command`

```python
def handle_update_command(self, payload):
    if payload.get("command") != "UPDATE":
        return {"status": "IGNORED", ...}
    if self.is_updating:                      # ① 업데이트 락
        return {"status": "ALREADY_UPDATING"}
    if target_version == self.current_version():   # ② 버전 비교
        return {"status": "ALREADY_LATEST", ...}
    self.is_updating = True
    try:
        return self._do_update(target_version)
    finally:
        self.is_updating = False
```

두 개의 조기 종료 관문이 있다.

- **업데이트 락(`is_updating`)** — 진행 중에 새 UPDATE가 오면 `ALREADY_UPDATING`으로 무시한다. 중복 실행 방지.
- **버전 비교** — 수신 버전이 `.ota_state`의 마지막 적용 버전과 같으면 `git fetch`조차 하지 않고 `ALREADY_LATEST`로 종료한다.

### 12.5.2 업데이트 절차 — `_do_update`

| 순서 | 단계 | 실패 시 |
| --- | --- | --- |
| 1 | `git fetch origin` | `UPDATE_FAILED (Git Fetch Error)` |
| 2 | 현재 브랜치 자동 감지 (`rev-parse --abbrev-ref HEAD`) | detached면 `main` 폴백 |
| 3 | HEAD vs `origin/<branch>` 비교 | 같으면 `ALREADY_LATEST` (버전만 갱신) |
| 4 | `git pull origin <branch>` | `UPDATE_FAILED (Git Pull Error)` |
| 5 | 변경 파일 목록 산출 (`git diff --name-only`) | — |
| 6 | `requirements.txt` 변경 시에만 `pip install` | **롤백** + `Pip Install Error` |
| 7 | `*.ino`(mega_firmware) 변경 시: UART 해제 → `arduino-cli compile` → `upload` | **롤백** + Compile/Upload Error |
| 8 | 헬스체크(`health_check_fn`) | **롤백** + `Health Check Failed` |
| 9 | `.ota_state`에 버전 기록 → `UPDATE_COMPLETE` 보고 | — |
| 10 | 자기 재시작 (`os.execv`) | 실기기에서는 이 아래로 내려오지 않음 |

**브랜치 하드코딩 안 함** — 이 저장소(`STREW-VISION.git`)는 `master`, 다른 환경은 `main`일 수 있으므로 현재 체크아웃된 브랜치를 따라간다.

**조건부 실행** — pip은 `requirements.txt`가 바뀐 경우에만, 펌웨어 업로드는 `mega_firmware`의 `.ino`가 바뀐 경우에만 돈다. 코드만 바뀌면 무거운 단계를 건너뛴다.

### 12.5.3 롤백 — `_rollback`

pip / 컴파일 / 업로드 / 헬스체크 중 어느 하나라도 실패하면 이전 커밋으로 하드 리셋한다.

```python
def _rollback(self, old_commit):
    self.runner.run(["git", "reset", "--hard", old_commit])
```

이것이 OTA의 안전판이다. 절반만 적용된 상태로 로봇이 재시작되는 일을 막는다.

### 12.5.4 버전 상태 파일 — `.ota_state`

마지막으로 적용한 버전을 저장하는 로컬 파일이다(`gitignore` 대상). `current_version()`이 이 파일을 읽어 버전 비교에 쓴다. 파일 저장 실패는 무시한다(업데이트 자체를 막지 않는다).

---

## 12.6 Status Reporting

`_report_status`는 업데이트의 각 결과를 두 경로로 보고한다.

```
UpdateManager.publish_status(status)
    │
    ├── MQTT  robot/system/status   (mqtt.publish)
    └── HTTP  POST /robot/ota-status  (cloud.post_ota_status)  ──▶ AWS ──▶ Dashboard
```

보고되는 `status` 값: `UPDATING` / `UPDATE_COMPLETE` / `UPDATE_FAILED` / `ALREADY_LATEST` / `ALREADY_UPDATING`. 완료 보고에는 `version`, `commit`(단축 해시), `firmware_updated`, `changed_files`, `update_time`이 함께 담긴다.

AWS 쪽 수신 엔드포인트(`app/main.py`): `POST /robot/ota-status`가 상태를 저장하고, `GET /robot/ota-status`로 대시보드가 목록을 조회한다.

---

## 12.7 Preflight 점검 (`scripts/ota_preflight.py`)

실제 업데이트를 하지 않고 **OTA가 성공하기 위한 전제 조건만 검사**하는 스크립트다. Jetson에 처음 배포할 때 한 번 돌려 환경을 확인한다.

```bash
python3 scripts/ota_preflight.py
```

점검 항목: `git`/`arduino-cli` 설치 여부, 저장소 경로(`ota_repo_dir`), 펌웨어 스케치 경로, 시리얼 포트, 관련 설정값. 각 항목을 `[OK]/[WARN]/[FAIL]`로 출력한다. 실제 업데이트 전에 "환경이 준비됐는지"를 미리 확인하는 안전 절차다.

---

## 12.8 Jetson Nano 호환성 노트

OTA 코드 전반은 JetPack 기본 **Python 3.6** 환경을 전제로 한다.

- **subprocess** — `capture_output`/`text`(3.7+) 대신 `stdout=PIPE, stderr=PIPE, universal_newlines=True`를 쓴다. `CommandRunner.run`, preflight 모두 동일.
- 이 규약은 SQLite(Chapter 10)의 `INSERT OR REPLACE`, `ON CONFLICT` 회피와 같은 맥락 — **Jetson Nano 실환경 호환을 코드 전반의 제약으로 둔다.**

---

## 12.9 Design Principles

| 원칙 | 설명 |
| --- | --- |
| Relay, Not Exposure | MQTT 브로커를 외부에 열지 않는다. GitHub→AWS(HTTPS)→MQTT 중계. |
| Atomic / Rollback | 어느 단계든 실패하면 이전 커밋으로 `git reset --hard`. 반쯤 적용된 상태 금지. |
| Conditional Steps | pip은 requirements 변경 시, 펌웨어 업로드는 `.ino` 변경 시에만. |
| Idempotent by Version | 같은 버전이면 `git fetch`도 없이 `ALREADY_LATEST`. |
| Lock | 진행 중 중복 UPDATE는 `ALREADY_UPDATING`으로 무시. |
| Injectable I/O | 쉘=CommandRunner, 재시작/UART해제/헬스체크=콜백 주입 → 테스트 가능. |
| Non-Blocking | OTA 초기화·상태 보고 실패가 로봇 제어를 막지 않는다. |
| Jetson-Compatible | Python 3.6 기준 subprocess 규약을 지킨다. |

---

## 12.10 Summary

Updater Module(`updater/`)은 STREW_VISION의 무인 원격 업데이트(OTA)를 담당한다. 개발자가 코드를 push하면 GitHub Actions가 날짜 기반 버전을 만들어 AWS를 HTTPS로 호출하고, AWS가 이를 내부 MQTT로 중계한다. Jetson의 `OtaService`가 이 명령을 받아 `UpdateManager`를 돌리며, git pull → (조건부) pip/펌웨어 업로드 → 헬스체크 → 재시작 순으로 진행한다. 어느 단계든 실패하면 이전 커밋으로 롤백하고, 결과는 MQTT status 토픽과 AWS `/robot/ota-status` 양쪽으로 보고되어 대시보드에서 확인된다.

OTA는 **제어의 전제 조건이 아니라 부가 계층**이다. 초기화나 보고가 실패해도 로봇의 실시간 제어(Mega)와 상태 관리(SQLite, Chapter 10)는 영향을 받지 않는다. 브로커를 외부에 노출하지 않는 중계 구조와, 실패 시 롤백하는 원자성이 이 모듈의 두 축이다.

**OTA는 Source of Truth를 변경하지 않는다.** OTA가 교체하는 것은 프로그램(코드·펌웨어)뿐이며, 상태는 여전히 SQLite(Chapter 10)가 유지한다. 업데이트되어도 `current_task`·`inspection_images`·`detection_log`는 그대로 남는다. 즉 "코드는 새것, 상태는 이어짐"이 보장된다.

이 덕분에 재시작이 Recovery와 자연스럽게 이어진다. OTA의 마지막 단계인 `os.execv` 재시작 이후에는 RobotAgent가 다시 시작되며 SQLite를 읽고 복구를 수행한다 — **재시작 이후의 Recovery는 Chapter 10(Storage)과 Chapter 7(Event Processing)의 Recovery 절차를 그대로 따른다.** OTA는 그 흐름의 앞단(프로그램 교체)만 담당하고, 상태 복원의 책임은 넘기지 않는다.

---

## 부록. updater/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 역할 |
| --- | --- |
| `updater/update_manager.py` | 업데이트 실행 엔진 (`UpdateManager`, `CommandRunner`). git/pip/arduino/롤백/버전. |
| `updater/ota_service.py` | MQTT↔UpdateManager 배선 (`OtaService`). 콜백 주입 + 상태 2경로 보고. |
| `scripts/ota_preflight.py` | 배포 전 환경 점검(비파괴). git/arduino-cli/포트/설정 확인. |
| `.github/workflows/ota-update.yml` | push → 날짜 버전 생성 → AWS `/api/ota/update` 호출. |
| `app/main.py` (AWS) | `/api/ota/update`(MQTT 중계 발행), `/robot/ota-status`(상태 수신/조회). |
| `.ota_state` | 마지막 적용 버전 로컬 저장(gitignore). 버전 비교 기준. |

---

### 관련 설정값 (`config/settings.py`)

| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `ota_enabled` | `true` | OTA 서비스 기동 여부. |
| `ota_update_topic` | `robot/system/update` | UPDATE 명령 수신 토픽. |
| `ota_status_topic` | `robot/system/status` | 상태 보고 발행 토픽. |
| `ota_repo_dir` | repo 루트 자동 감지 | git이 도는 저장소 경로. |
| `ota_arduino_fqbn` | `arduino:avr:mega` | 펌웨어 컴파일/업로드 대상 보드. |
| `ota_arduino_port` | `/dev/ttyACM0` | 펌웨어 업로드 시리얼 포트. |
| `ota_firmware_sketch` | `<로봇폴더>/mega_firmware` | 펌웨어 스케치 경로(폴더명 자동 감지). |
