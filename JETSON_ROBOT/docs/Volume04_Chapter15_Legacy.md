# Chapter 15. Legacy & Future Compatibility

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 저장소 상태를 기준으로, 지금까지의 설계 결정과 잔존 요소를 정리한다.
>
> **이 장의 성격**
> - Legacy는 "삭제되지 않은 쓰레기"가 아니라, **하위 호환성·예약 기능·역사적 설계 결정을 문서화**하는 장이다.
> - 협업자(GPT/사람)가 "이 파일 왜 있지?", "왜 이렇게 설계했지?"를 여기 한 곳에서 확인할 수 있게 한다.

---

## 15.1 Overview

시스템이 커지면 저장소에는 네 종류의 "지금 안 쓰지만 남아있는 것"이 생긴다. 이 장은 그것을 네 범주로 분류한다.

| 범주 | 정의 | 예 |
| --- | --- | --- |
| **Legacy** | 더 이상 런타임에서 사용되지 않는 코드/파일 | `uart.yaml`, `logging.conf`, `planner.py`, 복제 저장소 |
| **Reserved** | 아직 안 쓰지만 향후 사용할 예약 구조 | `image_path`(Phase D), Config Sync |
| **Design Decisions** | 최종적으로 내린 설계 선택과 그 이유 | NEXT_VIEW 제거, Cell 단위 Recovery, 항상 4 View |
| **Current but Secondary** | 지금 살아있지만 주 기능은 아닌 요소 | WebRTC 라이브뷰 |

핵심 구분: **Legacy(과거) ≠ Reserved(미래) ≠ Secondary(현재 보조)**. 이 셋을 섞으면 "지울 것"과 "남길 것"과 "확장할 것"이 뒤엉킨다. 이 장은 그 경계를 분명히 한다.

---

## 15.2 Legacy Components (실제 미사용)

런타임이 더 이상 읽지 않는, 그러나 저장소에 남아있는 요소들.

### `config/uart.yaml`

- **상태: Legacy (미사용)**
- 코드에서 `yaml.load` 등으로 **로드하지 않는다**(전수 확인).
- 내용이 **구 UART 프로토콜**(`MOVE/STOP/HOME/QR_SCAN`, `OK/BUSY/DONE/ERROR`)로, 현재 v1.0 프로토콜(`READY/RUN/RESUME/STATE/ACK/TASK/PING/PONG/COMPLETE`)과 다르다.
- 실제 UART 파라미터는 `settings.py`의 `arduino_port`·`arduino_baudrate`가 관리한다(Chapter 14).

### `config/logging.conf`

- **상태: Legacy (미사용)**
- `logging.config.fileConfig` 호출이 코드 어디에도 없다. `config/__init__.py`의 **주석 문자열**에만 이름이 등장한다.
- 현재 로깅은 대부분 `print()` 기반이다.

### `robot/planner.py`

- **상태: Legacy Module (런타임 경로 밖, 의도적 보존)**
- Chapter 9에서 이미 다뤘듯, 2026-07-15 아키텍처 변경으로 **결정권(REPLACE/OBSERVE/SKIP)이 Jetson → Mega로 이전**되면서 `state_machine.py`는 더 이상 `planner.py`를 import/호출하지 않는다.
- **지우지 않고 남긴 이유**(코드 주석 명시): ① `tests/test_decision.py`가 이 로직을 테스트 중이라 지우면 커버리지 손실, ② `ACTION_MAP`이 **Mega 펌웨어(C++)로 포팅할 "정답 스펙"** 역할. 현재 런타임 매핑은 `command.py`에 인라인돼 있고 "구 planner.py ACTION_MAP과 동일"이라 주석돼 있다.
- **삭제 조건**: Mega 펌웨어가 동일한 매핑을 안정적으로 사용하고, 테스트(`test_decision.py`)가 더 이상 `planner.py`에 의존하지 않게 되면 삭제 가능하다. (두 역할 — 테스트 커버리지 + ACTION_MAP 스펙 — 이 모두 해소되어야 함.)

---

## 15.3 Repository Legacy

저장소 구조 차원의 잔존물 — 협업자가 "어느 게 정본인가"를 헷갈리지 않도록 정리한다.

### 정본 vs 복사본 (monorepo 관계)

```
C:\STREW_VISION\JETSON_ROBOT           ← 정본 (canonical, Jetson 로봇 코드)
        │  (repo: STREW-VISION.git, branch master)
        │
STREW-VISION_AWS/jetson_robot/         ← 과거 monorepo 사본 (제거됨)
```

- **정본**은 `C:\STREW_VISION\JETSON_ROBOT`이다. Jetson 로봇 코드(UART/OTA/센서/YOLO/SQLite)의 변경은 여기서 한다.
- AWS 저장소(`STREW-VISION_AWS.git`)는 **AWS 측만** 담는다(`app/`, `infra/`, `jetson_greenhouse_system/`). CLAUDE.md에 따르면 과거 monorepo에 있던 `jetson_robot/` 사본은 제거되었고, 정본은 별도 저장소다.
- 두 저장소는 `app/` HTTP API + MQTT로만 통신한다. **같은 파일을 양쪽에서 편집하지 않는다.**

### `jetson_greenhouse_system/server01/`

- **상태: Legacy Copy (구조 복제 흔적)로 CLAUDE.md에 기록됨.**
- CLAUDE.md에는 `jetson_greenhouse_system/server01/`을 오래된 구조(legacy copy)로 취급하라는 주석이 남아 있다.
- **현재 저장소 상태와 관계없이**, 해당 디렉터리가 존재하는 경우에는 **정본 여부를 먼저 확인한 후 수정**해야 한다. 정본 그린하우스 서버는 `jetson_greenhouse_system/server/index.js`다.

---

## 15.4 Reserved Features (예약 — Legacy 아님)

지금은 비어있지만, 코드 구조상 **자리를 미리 잡아둔** 확장 지점. Legacy와 반대 방향(과거가 아닌 미래)이다.

### `image_path` — Phase D 예약 필드

- `inspection_images` 테이블에 `image_path TEXT` 컬럼이 있고, `add_image(...)`는 **현재 항상 `image_path=None`으로 저장**한다(state_machine.py에서 명시적으로 `image_path=None` 전달 — 확인됨).
- 즉 지금은 **판독 메타데이터(view/status/confidence)만** 저장하고, 실제 이미지 파일은 저장하지 않는다.
- **확장 경로(Phase D)**:

```
현재: image_path = None (메타데이터만)
   ↓
Phase D
   JPEG 저장 → S3 업로드 → AWS URL을 image_path에 기록
```

- 컬럼과 파라미터를 미리 둔 덕분에, Phase D는 스키마 변경 없이 값만 채우면 된다.

### Config Sync — Dashboard → Jetson (미구현)

- **As-Is**: 운영 정책값(`max_view`, `confidence_threshold`)의 기준은 Jetson SQLite `system_config`다(Chapter 10·11·14).
- **Reserved**: AWS Dashboard에서 바꾼 정책을 Jetson으로 내려보내는 경로는 **아직 없다**.

```
현재: SQLite(system_config) → 운영 (Jetson이 기준)
   ↓
확장: Dashboard 변경 → AWS → (MQTT/HTTP) → Jetson system_config 반영
```

- Chapter 11의 Implementation Note와 동일한 결정 — **지금 구현하지 않는다.** Cloud는 상태의 기준이 아니며(Source of Truth는 SQLite), Config Sync가 추가되어도 그 원칙은 유지된다.

---

## 15.5 Design Decisions (최종 설계 선택)

"왜 이렇게 설계했는가"를 기록한다. 시간이 지나 초기안을 잊었을 때, 이 절이 결정의 근거가 된다.

### NEXT_VIEW 제거 — Mega 자가 순회

```
초기안:  Jetson이 View마다 NEXT_VIEW 명령을 보냄
   ↓
최종:    Mega가 TOP → LEFT → RIGHT → FRONT 고정 순서로 스스로 순회
        Jetson은 4장 종합 후 최종 TASK만 전송
```

- `command.py` 주석에 명시: "**항상 4 View 고정 순서 정책**이므로 NEXT_VIEW는 두지 않는다."
- 이유: 순회 제어를 Mega(모션 담당)에 두면 Jetson↔Mega 왕복이 줄고, 역할 분담(Mega=모션, Jetson=AI/종합)이 깔끔해진다. 가변 순회가 필요해지면 그때 `CMD_NEXT_VIEW`를 확장으로 도입한다.

### Recovery — View 단위 → Cell 단위

```
초기 고려:  View 중간 위치까지 복원 (LEFT 찍다 꺼지면 LEFT부터)
   ↓
최종:       Cell 단위 복원 (그 Cell을 TOP부터 다시)
```

- `current_task`는 복원 기준으로 **cell_id까지만** 사용하고, View 중간 위치는 복원하지 않는다(Chapter 10). 4장은 짧은 시퀀스라 Cell 단위 재시작이 단순하고 안전하다.

### Multi-View — Early Stop → 항상 4 View

```
초기 고려:  확신이 서면 조기 종료(Early Stop)
   ↓
최종:       항상 4 View(TOP/LEFT/RIGHT/FRONT) 촬영 후 종합 판정
```

- 종합 판정(`aggregate_views`)은 가장 심각한 상태가 이긴다(어느 뷰든 disease면 disease). 항상 4장을 봐야 오판(한 각도에서 안 보이는 병징)을 줄일 수 있다. 촬영 수는 `system_config.max_view`로 조정 가능하되, 정책 기본은 4다.

---

## 15.6 Current but Secondary — WebRTC 라이브뷰

Legacy가 아니다. **현재 코드에 살아있고 유지하기로 결정**했으나, 주 판단 기능은 아니다.

```
WebRTC 라이브뷰   → 보조 (관리자가 실시간으로 눈으로 볼 수 있는 수단)
Inspection 4장    → 주 판단 근거 (관리자 승인·기록의 기준)
```

- `create_stream_session` / `POST /stream/session`은 Jetson·AWS 양쪽에 살아있다(Chapter 11 확인).
- Phase C 이후 **관리자 판단의 1차 근거는 Inspection 4-View 결과**다. WebRTC는 필요 시 실시간 확인을 돕는 **보조 채널**로 남는다.
- 따라서 WebRTC는 "제거 대상(Legacy)"이 아니라 "유지하되 보조(Secondary)"로 분류한다.

---

## 15.7 Future Roadmap

Phase D 이후 예약된 확장 기능. 현재 구현에는 포함되지 않는다.

| 기능 | 연결 지점 | 비고 |
| --- | --- | --- |
| Image Upload | `image_path`(15.4) | JPEG 저장 → 업로드 |
| S3 저장 | `image_path` | 이미지 원본 클라우드 보관 |
| Config Sync | `system_config`(15.4) | Dashboard → Jetson 정책 동기화 |
| Dataset Export | `inspection_images` | 판독 데이터셋 추출(재학습용) |
| AI Retraining | Dataset Export | 축적 데이터로 YOLO 재학습 |
| Statistics | `detection_log`/`task_history` | 셀별·기간별 통계 대시보드 |

이들은 모두 기존 SQLite 3-tier 구조(Chapter 10) 위에 얹히도록 설계되어, 스키마 대수술 없이 확장 가능하다.

---

## 15.8 Summary

Chapter 15는 STREW_VISION 저장소의 "지금 안 쓰지만 남아있는 것"을 네 범주로 정리한다.

- **Legacy** — 런타임이 더 이상 읽지 않는 것: `config/uart.yaml`(구 프로토콜), `config/logging.conf`(미로드), `robot/planner.py`(결정권 Mega 이전 후 테스트·스펙용 보존), 그리고 저장소 복제 흔적(`server01`, monorepo 사본).
- **Reserved** — 미래를 위해 자리를 잡아둔 것: `image_path`(Phase D 이미지/S3), Config Sync(Dashboard→Jetson).
- **Design Decisions** — 최종 설계 선택과 이유: NEXT_VIEW 제거(Mega 자가 순회), Cell 단위 Recovery, 항상 4 View.
- **Current but Secondary** — 살아있으나 보조인 것: WebRTC 라이브뷰(주 판단은 Inspection 4장).

이 장의 결론은 명확하다. **Legacy는 삭제되지 않은 쓰레기가 아니라, 프로젝트의 하위 호환성·예약 기능·역사적 설계 결정을 문서화하는 장이다.** 무엇을 지울 수 있고(Legacy), 무엇을 채울 것이며(Reserved), 왜 이렇게 정했고(Design Decisions), 무엇을 보조로 유지하는지(Secondary)를 한 곳에서 확인함으로써, 이후의 협업자와 미래의 자신이 시스템을 안전하게 이어받을 수 있다.

이로써 Volume 04는 런타임(RobotAgent)부터 통신(Cloud)·저장(Storage)·업데이트(OTA)·도구(Scripts)·설정(Config)·정리(Legacy)까지, **하나의 일관된 5계층 철학** 아래 완결된다.

| 계층 | 역할 |
| --- | --- |
| **Config** | 정적 부팅 설정 (환경·하드웨어 배선) |
| **Mega** | 실시간 Motion / Cycle |
| **SQLite** | 상태 기준 (Source of Truth) |
| **AWS** | 모니터링 및 승인 |
| **OTA** | 프로그램 교체 (상태는 불변) |

Config가 부팅을 정하고, Mega가 몸을 움직이고, SQLite가 상태를 기억하고, AWS가 지켜보며 승인하고, OTA가 코드를 갈아끼운다 — 각 계층의 책임이 겹치지 않는다. 이 분리가 STREW_VISION v2.0 설계의 뼈대다.
