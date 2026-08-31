# 04. AWS 서버 + 대시보드

`C:\AWS_SYSTEM\STREW-VISION_AWS`. FastAPI + 정적 HTML 대시보드. **로컬 PC에서 실행**(클라우드 안 씀).

## 실행
```bash
cd C:\AWS_SYSTEM\STREW-VISION_AWS
uvicorn app.main:app --host 0.0.0.0 --port 8000   # ★ 0.0.0.0 필수(젯슨이 붙어야 함)
```
- 저장소: `LocalJsonStore`(기본, `./data/strew_store.json`) 또는 DynamoStore.
- 대시보드: `http://localhost:8000/` (index/admin/details/live/schedule).

## 설정 (`app/settings.py` + `.env`)
```
API_KEY=change-me          ← "change-me"면 인증 OFF(대시보드 통과). 실제 키면 인증 ON
MQTT_ENABLED=true          ← ESP32 센서 수집 켜기
MQTT_BROKER_HOST=localhost
MQTT_SENSOR_TOPIC=esp32/sensor
```
**★ 인증 로직**(main.py `require_api_key`): `api_key != "change-me"`면 헤더 `X-API-Key` 일치 요구.
대시보드(common.js)는 localStorage의 키를 헤더로 보냄(사이드바 "API Key" 입력칸). **OS 환경변수 API_KEY가
.env를 덮으니**, 로컬 테스트에서 401 나면 `echo $Env:API_KEY` 확인 후 `change-me`로.

## 주요 API 엔드포인트 (Jetson이 호출)
| 엔드포인트 | 용도 |
|---|---|
| `GET /robot/next` `POST /robot/request` | 작업 큐 |
| `POST /robot/progress` | 진행상황(target/state/progress/action) 실시간 |
| `POST /robot/response` | 셀 완료/에러 |
| `GET/POST /robot/config` | 로봇 설정(cycle_count/max_view/confidence_threshold/total_cells) 동기화 |
| `GET/POST /robot/status` `/robot/schedule` `/robot/errors` | 런타임 상태/스케줄/에러 |
| `POST /vision/event` | 종합 판독 결과 |
| `POST /vision/decision-request` `GET /vision/decision-request/{id}` | 관리자 승인 요청/폴링 |
| `/stream/session/*` | (WebRTC용, 현재 MJPEG로 대체) |
| `GET /ai/readings` | 대시보드 실시간 추론 인디케이터 데이터 |
| `/api/ota/*` `/robot/ota-status` | OTA 업데이트 |

## MQTT 센서 수집 (`app/mqtt_ingest.py`)
ESP32가 `esp32/sensor`로 `{"sensor1":{"temp","humi"},...}` 발행 → **AWS가 직접 구독**(Jetson 경유 X).
`sensorN → cell N` 매핑. 쓰로틀 `sensor_ingest_interval_sec=10`(셀당 10초에 1회 저장).
`MQTT_ENABLED=true`일 때만 기동. 기동 로그: `mqtt ingest: connected ... subscribed 'esp32/sensor'`.

## 대시보드 페이지 (`app/static/`)
| 페이지 | 내용 |
|---|---|
| `index.html` | 메인 - 로봇 진행도 링/셀맵, 농장 상태 |
| `admin.html` | 관리자 - 승인 대기(decision request) 처리, 로봇 타일 |
| `details.html` | 상세 - Cycle Progress/Runtime/Timeline, 로봇 설정 편집 |
| `live.html` | ★ 라이브 스트림 - MJPEG `<img>` 임베드(젯슨:8090) + 실시간 추론 인디케이터 |
| `schedule.html` | 주간 작업 스케줄(요일×시각 그리드) |
| `common.js` | 공통(사이드바, API 호출, getApiKey/localStorage) |

**live.html 스트림**: 상단 입력칸에 `http://<젯슨IP>:8090/stream` → "스트림 시작"(기본 192.168.0.3 자동시도).
연결되면 배지 OFFLINE→LIVE. localStorage에 URL 저장. 오른쪽 인디케이터는 `/ai/readings`에서 별도로 옴.

## 로봇 설정 동기화 흐름
1. 대시보드 로봇설정 저장 → AWS `POST /robot/config`.
2. **즉시 적용 아님** — 젯슨이 **다음 사이클 시작(RUN) 때** `get_robot_config` pull → SQLite에 반영.
3. 부팅 시 젯슨이 `post_robot_config(get_all_config())`로 자기 설정을 AWS에 보고(순환 주의: total_cells).

## 네트워크 주의 (자주 틀림)
- 젯슨 `.env` `AWS_API_BASE`/`MQTT_BROKER_HOST` = **PC IP** (젯슨 자기 IP 아님!).
- 증상 `Connection refused to 192.168.0.3:8000` = 그게 젯슨 자기 IP였음 → PC IP로.
- PC: uvicorn `--host 0.0.0.0`, Mosquitto LAN 리스너, Windows 방화벽 8000/1883 허용.
