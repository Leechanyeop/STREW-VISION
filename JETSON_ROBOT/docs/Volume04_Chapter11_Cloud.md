# Chapter 11. Cloud Module (`cloud/`)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `cloud/` 디렉터리 구현을 기준으로 작성되었다.
>
> **운영 정책 관리 원칙 (공통 전제 — Chapter 10 부록 2)**
> - **As-Is**: 운영 정책값(max_view 등)의 기준은 Jetson SQLite(`system_config`)다.
> - **Implementation Note**: Dashboard → Jetson Config Sync는 향후 확장 예정(미구현).
>
> **역할 (불변)**
> - Cloud Module은 Jetson의 상태·판독 결과를 AWS로 **보고(업로드)**하고, 관리자 판단을 **조회**한다.
> - Cloud가 끊겨도 로봇 제어(Mega)와 로컬 상태(SQLite)는 계속 동작한다(오프라인 내성).

---

## 11.1 Overview

`cloud/` 디렉터리는 Jetson과 AWS 사이의 통신 계층이다. Jetson에서 생성된 작업 상태, 비전 판독, 센서 데이터를 AWS로 올리고, 병해충 판단 요청에 대한 관리자 응답을 조회한다.

Cloud Module의 핵심 설계는 **오프라인 내성**이다. AWS·네트워크가 끊겨도 로봇의 실시간 제어(Mega)와 상태 관리(SQLite)는 멈추지 않는다. Cloud 전송 실패는 로봇 동작을 막지 않고, 재시도 큐에 쌓였다가 나중에 다시 보낸다.

데이터 흐름은 기본적으로 **Jetson → AWS(업로드)** 방향이다. 반대 방향(AWS → Jetson)은 현재 관리자 판단 조회(polling)와 OTA 명령(MQTT 구독)뿐이며, 운영 정책을 내려보내는 Config Sync는 향후 확장이다.

---

## 11.2 Cloud Architecture

```
RobotAgent
    │
    ├── api_client.py (REST)  ──HTTP──▶ AWS FastAPI  ──▶ Dashboard
    ├── sync.py (재시도 큐)   ──▶ api_client 감싸 실패 보관
    ├── mqtt.py (MQTT)        ──▶ 긴급정지 구독 / OTA update 구독
    └── sensor_bridge.py      ──▶ ESP32 센서 → /sensor/log (기본 비활성)
```

각 파일의 책임:
- **`api_client.py`** : AWS REST API 호출 (`CloudClient`)
- **`sync.py`** : 전송 실패 시 큐에 보관 후 재시도 (`CloudSync`)
- **`mqtt.py`** : MQTT 구독 (긴급정지 / OTA)
- **`sensor_bridge.py`** : ESP32 센서 데이터 브리지 (선택)

---

## 11.3 REST Client (`api_client.py`)

`CloudClient`는 AWS FastAPI와 통신하는 REST 클라이언트다. 생성 시 `X-API-Key` 헤더를 세팅하고, 각 메서드가 정해진 엔드포인트를 호출한다.

주요 메서드(실제 구현):

| 메서드 | 엔드포인트 | 방향 |
| --- | --- | --- |
| `next_task(robot_id)` | `GET /robot/next` | AWS→Jetson (작업 수신) |
| `post_response(...)` | `POST /robot/response` | Jetson→AWS (완료/에러 보고) |
| `post_progress(...)` | `POST /robot/progress` | Jetson→AWS (진행 보고) |
| `post_vision_event(...)` | `POST /vision/event` | Jetson→AWS (판독 기록) |
| `create_decision_request(..., inspection_views)` | `POST /vision/decision-request` | Jetson→AWS (병해충 판단 요청 + 4 View) |
| `get_decision_request(id)` | `GET /vision/decision-request/{id}` | AWS→Jetson (관리자 응답 조회) |
| `post_sensor_log(...)` | `POST /sensor/log` | Jetson→AWS (센서) |
| `post_ota_status(...)` | `POST /robot/ota-status` | Jetson→AWS (OTA 상태) |
| `create_stream_session(...)` | `POST /stream/session` | WebRTC 시그널링 |

`create_decision_request`는 Phase C에서 4 View 판독 결과(`inspection_views`)를 함께 전송한다(Chapter 7.5 / AWS 대시보드 표시용).

```python
def create_decision_request(self, robot_id, vision_event_id, detected_status, inspection_views=None):
    body = {"robot_id": robot_id, "vision_event_id": vision_event_id,
            "detected_status": detected_status, "inspection_views": inspection_views or []}
    r = self.session.post(f"{self.base_url}/vision/decision-request", json=body, timeout=self.timeout)
    r.raise_for_status()
    return r.json()
```

---

## 11.4 Retry Queue (`sync.py`)

`CloudSync`는 AWS 전송의 **오프라인 내성**을 담당한다. `try_send`로 보고를 시도하되, 실패하면 예외를 흡수하고 재시도 큐(`fail_queue`)에 보관한다. 즉 **AWS 전송 실패가 로봇 동작을 막지 않는다.**

```python
class CloudSync:
    def __init__(self, cloud_client):
        self.cloud_client = cloud_client
        self.fail_queue = []

    def try_send(self, report_func, *args, **kwargs):
        try:
            report_func(*args, **kwargs)
        except Exception as e:
            print(f"Failed to send report: {e}. Queuing for retry.")
            self.fail_queue.append((report_func, args, kwargs))

    def flush_queue(self):
        # 큐에 쌓인 실패 보고를 다시 시도한다. 또 실패하면 다시 큐에 넣는다.
        ...
```

RobotAgent는 진행 보고(`post_progress`)·완료(`post_response`)처럼 "실패해도 되는" 보고를 `cloud_sync.try_send(...)`로 감싼다. 반면 관리자 판단 요청(`create_decision_request`)·응답 조회(`get_decision_request`)는 반환값(id/status)이 즉시 필요하므로 `try_send`로 감싸지 않고 직접 호출한다.

---

## 11.5 MQTT (`mqtt.py`)

`MqttClient`는 MQTT 브로커를 구독한다. 두 가지 용도가 있다.
- **긴급정지** : 지정 토픽에서 `stop` 수신 시 `emergency_stop_flag`를 세운다.
- **OTA 업데이트** : `on_update` 콜백으로 원격 업데이트 명령을 받는다(Chapter 12).

paho-mqtt 1.x/2.x 호환을 위해 클라이언트 생성 시 `CallbackAPIVersion.VERSION1`을 명시하고, 1.x에서는 예외로 폴백한다. 수신 콜백에서 어떤 예외가 나도 수신 루프(긴급정지 포함)는 죽지 않도록 예외를 흡수한다.

MQTT는 RobotAgent 초기화 과정에서 브로커 연결(`connect`) 및 구독(`subscribe`)을 수행하며, 이후 백그라운드 네트워크 스레드(`loop_start`)에서 메시지를 수신한다.

> **참고.** ESP32 센서 데이터는 현재 AWS 서버가 직접 MQTT를 구독해서 처리하는 것이 기본이다. Jetson 경유 브리지(`sensor_bridge.py`)는 기본 비활성이며, **AWS 설정(`aws_enabled`)과 센서 토픽(`mqtt_sensor_topic`)이 함께 활성화된 경우에만 생성**된다.

---

## 11.6 Cloud Data Flow

```
[업로드: Jetson → AWS]
STATE/COMPLETE → (cloud_sync.try_send) → api_client → AWS → Dashboard
4 View 판독   → create_decision_request(inspection_views) → AWS → Admin 승인 화면

[조회: AWS → Jetson]
병해충 판단   → get_decision_request(polling) → 관리자 treat/ignore 수신
OTA 명령      → mqtt on_update → UpdateManager (Chapter 12)
```

Cloud Module은 **상태·판독을 올리고, 관리자 판단과 OTA 명령을 받는다.** 운영 정책값(max_view 등)을 AWS에서 받아오는 경로는 아직 없다(아래 Implementation Note).

---

## 11.7 Design Principles

| 원칙 | 설명 |
| --- | --- |
| Offline Resilience | AWS 전송 실패가 로봇 동작을 막지 않는다. 실패는 큐에 보관 후 재시도. |
| Upload-Oriented | 기본 방향은 Jetson→AWS(업로드). AWS→Jetson은 판단 조회·OTA뿐. |
| Fire-and-Forget vs Direct | 실패 허용 보고는 `try_send`, 반환값이 필요한 호출은 직접. |
| API-Key Auth | 모든 REST 호출은 `X-API-Key` 헤더로 인증한다. |
| Loose Coupling | Cloud Module은 로봇 제어 로직을 모른다. 보고·조회만 담당. |
| Not the Source of Truth | Cloud는 상태를 저장하거나 복구 기준을 결정하지 않는다. 상태의 기준은 SQLite(Chapter 10)다. |

---

## 11.8 Summary

Cloud Module(`cloud/`)은 Jetson과 AWS 사이의 통신 계층이다. `api_client.py`가 REST 호출을, `sync.py`가 실패 재시도 큐를, `mqtt.py`가 긴급정지·OTA 구독을 담당한다. Phase C에서는 `create_decision_request`가 4 View 판독 결과를 함께 올려 관리자가 대시보드에서 검토할 수 있게 한다.

Cloud Module은 오프라인 내성을 전제로 설계되어, AWS·네트워크가 끊겨도 로봇의 실시간 제어와 로컬 상태 관리는 계속된다.

**Cloud Module은 상태를 저장하거나 복구 기준을 결정하지 않는다.** 상태의 기준(Source of Truth)은 Chapter 10의 SQLite이며, Cloud는 이를 외부 시스템(AWS)에 동기화하는 역할만 담당한다. 이 원칙은 Volume 04 전체의 계층 철학 — 실시간 제어=Mega, 상태 기준=Jetson SQLite, 모니터링·승인=AWS — 과 일치한다.

---

## Implementation Note (Config Sync — 향후 확장)

현재 운영 정책값(`max_view`, `confidence_threshold`)의 기준은 Jetson SQLite(`system_config`)다(As-Is). AWS Dashboard에서 변경한 정책을 Jetson SQLite로 내려보내는 **Config Sync 경로(Dashboard → AWS `system_config` → MQTT/HTTP → Jetson `system_config`)는 현재 구현되어 있지 않으며 향후 확장 예정**이다. 이 경로가 추가되면 "Dashboard에서 max_view 변경 → Jetson 즉시 반영"이 가능해진다. 본 내용은 향후 계획이며 현재 구현에는 포함되지 않는다.

---

## 부록. cloud/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 역할 | 방향 |
| --- | --- | --- |
| `api_client.py` | AWS REST 호출 (`CloudClient`) | 양방향 |
| `sync.py` | 전송 실패 재시도 큐 (`CloudSync`) | Jetson→AWS |
| `mqtt.py` | MQTT 구독 (긴급정지 / OTA) | AWS→Jetson |
| `sensor_bridge.py` | ESP32 센서 브리지 (기본 비활성) | ESP→AWS |
