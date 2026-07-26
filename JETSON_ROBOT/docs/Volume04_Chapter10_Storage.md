# Chapter 10. Storage Module (`storage/`)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `storage/state_db.py` 구현(Phase A/B/C 반영 확정본)을 기준으로 작성되었다.
>
> **역할 (불변)**
> - Storage Module은 Jetson의 상태 관리 **Source of Truth**다. Mega는 상태를 저장하지 않는다(EEPROM 미사용).
> - AWS가 끊겨도 Jetson은 SQLite만으로 동작·복구할 수 있어야 한다.

---

## 10.1 Overview

`storage/` 디렉터리는 Jetson의 상태를 SQLite에 보관하는 계층이다. STREW_VISION v2.0에서 이 DB는 로봇 상태의 **Source of Truth**이며, Recovery(Phase B)의 기준이자 Inspection 결과(Phase C)의 저장소다.

핵심 설계 이유는 **오프라인 내성**이다. 전원·네트워크·AWS 연결이 끊겨도 Jetson은 로컬 SQLite에 현재 상태를 계속 기록하고, 복구 시 그 기록을 기준으로 작업을 이어간다. 따라서 모든 STATE 이벤트는 AWS 릴레이보다 **로컬 SQLite에 먼저** 저장된다(Chapter 7 참고).

Storage Module은 로그·장기 이력 서비스가 아니라 **현재 시스템 상태와 검사 결과를 관리하는 최소 저장소**다. 장기 로그·대시보드 집계는 AWS(DynamoDB)가 담당한다.

---

## 10.2 Storage Architecture

```
RobotAgent
    │  update_current_task() / add_image() / get_current_task() ...
    ▼
StateDB (storage/state_db.py)
    │  sqlite3 (표준 라이브러리)
    ▼
robot_state.db  (로컬 파일, config: state_db_path)
```

- 단일 커넥션(`check_same_thread=False`)으로 UART 리스너 스레드와 메인이 함께 접근한다. 쓰기는 짧고 커밋 단위라 기본 락으로 충분하다.
- 스키마는 `CREATE TABLE IF NOT EXISTS`로 최초 1회 생성되며, 기본 설정값을 시딩한다.

---

## 10.3 Tables

StateDB는 5개 테이블을 목적에 따라 3계층으로 나눈다.
- **운영 테이블** (`current_task`, `system_config`) — 현재 상태·설정을 읽고 쓴다.
- **Inspection 데이터** (`inspection_images`) — Phase C의 View별 원본 판독 결과.
- **이력 데이터** (`detection_log`, `task_history`) — 판정·작업 이력.

세 계층은 중복이 아니라 **데이터 계층이 다르다**: inspection_images는 View별 원본(4행/셀), detection_log는 그 셀의 최종 종합 판정(1행/셀), task_history는 작업 실행 이력이다.

### 운영 테이블

**`current_task`** — 현재 작업 상태. 항상 1행만 유지(`id=1` 고정). Recovery의 기준.

| 컬럼 | 의미 |
| --- | --- |
| cycle_id | 현재 Cycle (AWS task id) |
| cell_id | 현재 Cell — **Recovery의 실제 기준** |
| task | 현재 작업 (REPLACE 등) |
| state | 현재 State |
| step | Replace Step ID (진행률 계산 기준) |
| progress | 진행률 (0~100) |
| view | 현재까지 마지막으로 완료한 Inspection View (Recovery에는 사용하지 않음 — 아래 주의 참고) |
| status | RUNNING / COMPLETE |
| updated_at | 마지막 갱신 시각 |

> **Recovery 정책(Phase B 확정 — 셀 단위 재개).** 복구는 `cell_id`만을 기준으로 한다. 예를 들어 LEFT View 촬영 중 전원이 꺼져도, 복구 시에는 **그 셀을 TOP View부터 처음 다시** 검사한다(4 View 재수행). View 중간 위치는 복원하지 않는데, 현재 하드웨어에 위치/엔코더 센서가 없어 View 물리 위치를 신뢰성 있게 복원할 수 없기 때문이다. 따라서 `current_task.view`는 참고 정보이며, Recovery는 `cell_id`로만 수행한다.

**`system_config`** — 운영 설정값 (key/value).

| key | 의미 |
| --- | --- |
| confidence_threshold | [예약] Early Stop/가변 View 도입 시 사용 (현재 미사용) |
| max_view | 촬영 View 수 (기본 4: TOP/LEFT/RIGHT/FRONT). **런타임에 실제로 이 값을 읽어** View 수를 결정하며, Dashboard에서 조정할 수 있다. |

### Inspection 데이터 (Phase C)

**`inspection_images`** — View별 **원본** Inspection 판독 결과 (셀당 4행).

| 컬럼 | 의미 |
| --- | --- |
| cycle_id / cell_id | 소속 Cycle / Cell |
| view | TOP / LEFT / RIGHT / FRONT |
| status | 해당 View 판독 status |
| confidence | 해당 View confidence |
| image_path | **[Phase D 예약]** JPEG/S3 저장 시 사용. Phase C에서는 항상 None |
| created_at | 저장 시각 |

### 이력 데이터

**`detection_log`** — Cell 단위 **최종 종합 판정** 결과 (셀당 1행).

| 컬럼 | 의미 |
| --- | --- |
| cycle_id / cell_id | 소속 Cycle / Cell |
| detection_class | 4 View 종합 최종 status |
| confidence | 최종 대표 confidence |
| task | 결정된 TASK (OBSERVE/REPLACE/SKIP) |
| created_at | 저장 시각 |

**`task_history`** — Cycle 진행 중 작업 이력 (cycle/cell/task/result/start/end). 향후 이력·통계용.

> **주의(현행 기준).** 실제 읽기/쓰기가 발생하는 테이블은 `current_task`·`system_config`(운영), `inspection_images`·`detection_log`(Phase C)이며, `task_history`는 스키마만 준비되어 있고 작업 이력 기능 확장 시 활성화한다.

---

## 10.4 Access API

StateDB는 테이블별 접근 메서드를 제공한다.

### current_task (Recovery 기준)

```python
def update_current_task(self, cycle_id=None, cell_id=None, state=None, task=None,
                        step=None, progress=None, view=None, status="RUNNING") -> None:
    # INSERT OR REPLACE (id=1 고정). 모든 컬럼을 매번 넘기므로 안전.
    ...

def get_current_task(self) -> Optional[Dict]: ...
def clear_current_task(self) -> None: ...   # status=COMPLETE로 표시
```

STATE를 받을 때마다 `update_current_task`가 호출되어 상태가 갱신된다(Chapter 7.4). Recovery 시 `get_current_task`로 미완료 작업(status=RUNNING)을 조회한다(Chapter 7.3 / Phase B).

### inspection_images / detection_log (Phase C)

```python
def add_image(self, cycle_id, cell_id, view, status=None, confidence=None, image_path=None) -> int: ...
def get_images(self, cycle_id, cell_id) -> List[Dict]: ...   # 저장/조회 API
def add_detection(self, cycle_id, cell_id, detection_class, confidence, task=None) -> int: ...
```

Inspection의 각 View 판독 직후 `add_image`로 원본을 저장한다. **종합 판정 자체는 SQLite를 다시 읽어서 하지 않는다** — RobotAgent가 메모리(`_inspect_results`)에 View 결과를 누적했다가 4장이 모이면 그 메모리로 종합 판정한다. `get_images`는 저장·조회 API일 뿐이며, 최종 판정 경로에 있지 않다.

종합 판정이 끝나면 그 셀의 최종 결과(status/confidence/task)를 `add_detection`으로 `detection_log`에 1건 기록한다. 즉 흐름은 다음과 같다.

```
View별 판독 → add_image() (원본 저장) + 메모리 누적
4장 완료  → 메모리로 종합 판정 → add_detection() (최종 판정 기록) → TASK 전송
```

### system_config

```python
def get_config(self, key, default=None) -> Optional[str]: ...
def get_config_float(self, key, default=0.0) -> float: ...
def get_config_int(self, key, default=0) -> int: ...
def set_config(self, key, value) -> None: ...   # INSERT OR REPLACE
```

---

## 10.5 SQLite Compatibility (젯슨 나노 호환)

젯슨 나노(JetPack 4.x / Ubuntu 18.04)는 **SQLite 3.22**를 사용하며, Python은 **3.6**이다. 이에 맞춰 다음을 준수한다.

- **UPSERT 미사용** — `ON CONFLICT ... DO UPDATE`는 SQLite 3.24+ 전용이므로 쓰지 않는다. 대신 `INSERT OR REPLACE`(3.22 호환)로 갱신한다. `current_task`는 `id=1` 고정, `system_config`는 `key` PK라 모든 컬럼을 매번 넘기면 안전하다.
- **표준 라이브러리만 사용** — `sqlite3` 외 의존성 없음(Python 3.6 호환).

이 제약은 실기기 배포 전 반드시 지켜야 하며, 위반 시 젯슨에서 런타임 오류가 발생한다.

---

## 10.6 Design Principles

| 원칙 | 설명 |
| --- | --- |
| Source of Truth | 상태의 기준은 SQLite다. Mega는 상태를 저장하지 않는다(EEPROM 미사용). |
| Local-First | STATE는 AWS 릴레이보다 로컬 SQLite에 먼저 저장한다. |
| Offline Resilience | AWS/네트워크가 끊겨도 SQLite만으로 동작·복구 가능하다. |
| Minimal Storage | 현재 상태와 운영에 필요한 최소 데이터만 저장하며, 장기 분석 및 집계는 AWS가 담당한다. |
| Fault Tolerance | DB 초기화·저장 실패해도 로봇 동작을 막지 않는다(예외 흡수). |
| Legacy-Safe Schema | 3.22 호환 문법(INSERT OR REPLACE)만 사용한다. |

---

## 10.7 Summary

Storage Module(`storage/state_db.py`)은 Jetson 상태의 Source of Truth인 SQLite 계층이며, 데이터를 3계층으로 관리한다.

- **운영**: `current_task`(Recovery 기준), `system_config`(설정)
- **Inspection 원본**: `inspection_images` — TOP, LEFT, RIGHT, FRONT **4개 View의 판독 결과**를 View별로 저장
- **이력**: `detection_log`(Cell 단위 최종 종합 판정 1건), `task_history`(작업 이력)

`inspection_images`와 `detection_log`는 중복이 아니라 계층이 다른 데이터다 — 전자는 View별 원본(4행/셀), 후자는 종합 판정(1행/셀)이다. 이 구분 덕분에 향후 AWS 동기화·통계·재학습 데이터로 자연스럽게 확장된다.

이 DB는 오프라인 내성을 위해 설계되었다. 모든 STATE는 로컬에 먼저 저장되며, 전원·네트워크가 끊겨도 Jetson은 SQLite의 `cell_id`를 기준으로 그 셀을 처음(TOP View)부터 재개한다(Phase B, 셀 단위 재개). View 중간 위치는 복원하지 않는다. 또한 젯슨 나노의 SQLite 3.22 / Python 3.6 환경 호환을 위해 UPSERT를 쓰지 않고 `INSERT OR REPLACE`로 갱신한다.

---

## 부록. storage/ 테이블 맵 (GPT/협업자 참고용)

| 테이블 | 계층 | 단위 | 내용 |
| --- | --- | --- | --- |
| `current_task` | 운영 | 1행 고정 | 현재 상태 (Recovery=cell_id 기준) |
| `system_config` | 운영 | key/value | confidence_threshold(예약), max_view=4 |
| `inspection_images` | Inspection 원본 | 4행/셀 | View별 status/confidence (image_path=Phase D 예약) |
| `detection_log` | 이력 | 1행/셀 | 최종 종합 status/confidence/task |
| `task_history` | 이력 | — | 작업 실행 이력 (스키마만, 확장 예정) |

호환성: SQLite 3.22 / Python 3.6 (INSERT OR REPLACE, 표준 lib)
관련 설정: `config.state_db_path`(DB 파일 경로) · `system_config.max_view`(촬영 View 수)

---

## 부록 2. 운영 정책 관리 원칙 (As-Is / 향후)

> 이후 Chapter 11(Cloud), 12(Updater) 및 AWS 문서도 이 원칙을 공통 전제로 사용한다.

**As-Is (현재 구현).** 운영 정책값(`max_view`, `confidence_threshold`)의 기준은 **Jetson SQLite의 `system_config`**다. Jetson은 런타임에 이 값을 읽어 동작하며(예: `_target_view_count`가 `max_view`를 조회), 로컬에서 값을 바꾸면 즉시 반영된다.

**Implementation Note (향후 확장).** AWS Dashboard에서 변경한 운영 정책을 Jetson SQLite로 전달하는 **Config Sync 경로(Dashboard → Jetson `system_config`)는 현재 구현되어 있지 않으며 향후 확장 예정**이다. 현재 AWS의 설정 저장소와 Jetson SQLite는 분리되어 있어, Dashboard 변경이 Jetson에 자동 반영되지 않는다. Config Sync는 별도 Phase에서 (AWS `system_config` → MQTT/HTTP → Jetson `system_config`) 형태로 추가한다.
