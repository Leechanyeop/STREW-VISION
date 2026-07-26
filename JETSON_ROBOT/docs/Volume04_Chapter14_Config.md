# Chapter 14. Config — 환경·부팅 설정 (`config/`)

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `config/` 디렉터리와 그 사용처를 기준으로 작성되었다.
>
> **역할 (불변)**
> - `config/`는 로봇이 **부팅될 때 읽는 정적 설정** — 환경(AWS on/off), 하드웨어 배선(포트·해상도), 경로 등 — 을 담는다.
> - 런타임 기준은 오직 `settings.py`의 `Config` 하나다. 값은 `.env`에서 읽고, 없으면 코드 기본값을 쓴다.
> - **운영 정책값(max_view 등 동적으로 바뀌는 값)은 Config가 아니라 SQLite(`system_config`)가 관리한다** (Chapter 10·11).

---

## 14.1 Overview

`config/` 디렉터리는 로봇의 **부팅 시점 설정**을 담당한다. Volume 04의 다른 모듈이 "실행 중 동작"이라면, Config는 그 실행이 시작되기 전에 **환경과 하드웨어를 어떻게 잡을지** 결정하는 정적 계층이다.

핵심은 명확한 구분이다.

| 성격 | 어디서 관리 | 예 |
| --- | --- | --- |
| **정적 부팅 설정** | `config/settings.py` (`.env`) | AWS on/off, 시리얼 포트, 카메라 해상도, MQTT 브로커, OTA 경로 |
| **동적 운영 정책** | **SQLite `system_config`** (Chapter 10) | `max_view`, `confidence_threshold` |

이 경계가 Config 챕터의 뼈대다. "장비를 어떻게 켤 것인가"는 Config, "운영 중 어떤 정책으로 판단할 것인가"는 SQLite다. 이 둘을 섞지 않는 것이 v2.0 설계의 핵심 결정이었다(Chapter 11 Config Sync 논의 참조).

---

## 14.2 config/ 디렉터리 구성

```
config/
├── settings.py      [사용]   런타임 설정의 유일한 기준 (Config dataclass)
├── __init__.py      [사용]   패키지 초기화 (docstring)
├── logging.conf     [미사용] 로깅 설정 파일 — 코드에서 로드되지 않음
└── uart.yaml        [미사용] UART 설정 YAML — 코드에서 로드되지 않음
```

**As-Is 정직 기록.** `config/`에는 네 개의 파일이 있지만, **실제 런타임이 읽는 것은 `settings.py` 하나뿐**이다. `logging.conf`와 `uart.yaml`은 디렉터리에 존재하지만 **어떤 파이썬 코드도 이 두 파일을 로드하지 않는다**(`yaml.load`, `logging.config.fileConfig` 호출 없음 — 코드 전수 확인). 자세한 내용은 14.6에서 다룬다.

| 파일 | 코드에서 로드? | 실제 역할 |
| --- | --- | --- |
| `settings.py` | ✅ 여러 모듈이 import | 런타임 설정 기준 |
| `__init__.py` | ✅ 패키지 | 초기화(문서 주석) |
| `logging.conf` | ❌ | 미사용(참고용 잔존) |
| `uart.yaml` | ❌ | 미사용(과거 프로토콜 잔존) |

---

## 14.3 `settings.py` — 설정의 유일한 기준

`settings.py`는 `Config`라는 **frozen dataclass** 하나로 모든 설정을 담는다. 각 필드는 `os.getenv("KEY", 기본값)` 형태로, `.env`에 값이 있으면 그것을, 없으면 코드에 박힌 기본값을 쓴다.

```python
from dataclasses import dataclass
from dotenv import load_dotenv
import os

load_dotenv()                      # .env 파일을 환경변수로 로드

@dataclass(frozen=True)            # 생성 후 변경 불가(불변 설정)
class Config:
    robot_id: str = os.getenv("ROBOT_ID", "robot-01")
    aws_enabled: bool = os.getenv("AWS_ENABLED", "false").lower() in ("1", "true", "yes")
    # ... (이하 모든 설정 필드)

settings = Config()                # 모듈 로드 시 단일 인스턴스 생성
```

세 가지 설계 특징:

- **`load_dotenv()`** — 프로젝트 루트의 `.env`를 읽어 환경변수로 등록한다. 그 뒤 각 필드가 `os.getenv`로 값을 가져온다.
- **`frozen=True`** — 인스턴스 생성 후 속성 변경을 막는다. 설정은 부팅 시 한 번 정해지고 런타임 중 바뀌지 않는다(동적 정책은 SQLite 몫).
- **기본값 내장** — `.env`가 없어도 코드 기본값으로 동작한다. 예를 들어 `aws_enabled` 기본값이 `false`라 AWS 없이 로컬 mock으로도 뜬다.

실제로 `settings.py`(또는 `settings` 인스턴스)를 import하는 곳: `main.py`, `robot/state_machine.py`, `ai/detector/camera.py`, `scripts/ota_preflight.py`, `scripts/sim_mega_v1.py`.

---

## 14.4 설정 카테고리

`Config`의 필드는 성격별로 다음과 같이 묶인다(값은 `config/settings.py` 기준 기본값).

### 정체성 / AWS 연동
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `robot_id` | `robot-01` | 로봇 식별자 |
| `aws_enabled` | `false` | AWS 연동 스위치. false면 로컬 mock 동작 |
| `aws_api_base` | `http://localhost:8000` | AWS FastAPI 주소 |
| `api_key` | (하드코딩 기본, 14.7 보안 참조) | `X-API-Key` 인증값 |
| `aws_timeout` | `5.0` | REST 요청 제한(초) |

### MQTT
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `aws_mqtt_broker` | `localhost` | MQTT 브로커 호스트 |
| `aws_mqtt_port` | `1883` | 브로커 포트 |
| `aws_mqtt_topic` | `robot/emergency_stop` | 긴급정지 구독 토픽 |
| `mqtt_sensor_topic` | `""`(비활성) | ESP32 센서 브리지 토픽(Chapter 11) |
| `sensor_forward_interval_sec` | `10` | 센서 전달 주기 |

### OTA (Chapter 12)
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `ota_enabled` | `true` | OTA 서비스 기동 여부 |
| `ota_update_topic` | `robot/system/update` | UPDATE 명령 수신 토픽 |
| `ota_status_topic` | `robot/system/status` | 상태 보고 토픽 |
| `ota_repo_dir` | 저장소 루트 자동감지 | git이 도는 경로 |
| `ota_arduino_fqbn` | `arduino:avr:mega` | 펌웨어 대상 보드 |
| `ota_arduino_port` | `/dev/ttyACM0` | 펌웨어 업로드 포트 |
| `ota_firmware_sketch` | `<로봇폴더>/mega_firmware` | 스케치 경로(폴더명 자동감지) |

### 상태 저장 (Chapter 10)
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `state_db_path` | `data/robot_state.db` | Jetson 상태 SQLite(Source of Truth) 경로 |

### 하드웨어 / UART
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `arduino_port` | `/dev/ttyACM0` | Mega 시리얼 포트 |
| `arduino_baudrate` | `115200` | UART 속도(Mega와 동일해야 함) |
| `poll_interval_sec` | `1.0` | 폴링 주기 |

### 비전 / YOLO
| 키 | 기본값 | 의미 |
| --- | --- | --- |
| `vision_mode` | `mock` | `mock` / `csi` 등 비전 모드 |
| `csi_camera_index` | `0` | CSI 카메라 인덱스 |
| `frame_width` / `frame_height` | `1280` / `720` | 프레임 해상도 |
| `yolo_model_path` | `models/best.engine` | TensorRT `.engine` 경로 |
| `yolo_conf_threshold` | `0.4` | YOLO confidence 임계 |
| `yolo_iou_threshold` | `0.45` | YOLO IoU 임계 |
| `yolo_input_size` | `640` | 입력 크기 |
| `yolo_class_names` | `healthy,powdery_mildew,missing_plant,empty_cell` | 클래스(학습 순서와 일치 필수) |

> `yolo_model_path` 기본값은 `.pt`가 아니라 `.engine`이다 — 카메라 로더가 `deserialize_cuda_engine()`으로 TensorRT 엔진을 읽기 때문(주석 참조).

---

## 14.5 `.env` 우선순위와 `.env.example`

값의 우선순위는 **`.env`(환경변수) > 코드 기본값** 이다. 공유 가능한 예시로 `.env.example`이 저장소에 포함된다(실제 `.env`는 비밀값이라 커밋 금지 — Chapter의 보안 규약).

**As-Is 정직 기록 — `.env.example`과 `settings.py` 기본값이 일부 다르다.** `.env.example`은 배포 시 채워 넣을 예시이므로 `settings.py`의 코드 기본값과 목적이 다르지만, 현재 두 값이 어긋나는 항목이 있으니 사용 시 유의한다.

| 키 | `.env.example` | `settings.py` 기본값 | 비고 |
| --- | --- | --- | --- |
| `VISION_MODE` | `csi` | `mock` | example은 실기(csi), 코드 기본은 안전한 mock |
| `YOLO_MODEL_PATH` | `models/best.pt` | `models/best.engine` | 코드는 TensorRT `.engine` 기준(example이 구식) |
| `API_KEY` | `change-me` | (하드코딩 hex) | **반드시 실제 랜덤값으로 교체**(14.7) |

또한 `.env.example`에는 MQTT·OTA·`STATE_DB_PATH`·YOLO 임계값 등 다수 키가 빠져 있다. 이들은 `.env`에 없으면 `settings.py` 기본값으로 동작한다.

> **Implementation Note.** `.env.example`을 `settings.py`의 실제 키 집합·기본값과 맞추면 배포 혼선을 줄일 수 있다(특히 `VISION_MODE`, `YOLO_MODEL_PATH`). 현재는 미정리 상태로, 문서로만 차이를 명시한다.

---

## 14.6 미사용 설정 파일 — `uart.yaml` / `logging.conf`

`config/` 안의 두 파일은 **코드에서 로드되지 않는다**. As-Is로 정직하게 기록한다.

### `uart.yaml` — 로드 안 됨, 게다가 과거 프로토콜

`uart.yaml`은 UART 포트/속도/명령어를 담은 YAML이지만 **어떤 코드도 `yaml.load`로 읽지 않는다.** 실제 UART 파라미터는 `settings.py`의 `arduino_port`·`arduino_baudrate`에서 온다.

더 중요한 것은 **내용이 현재 프로토콜과 다르다**는 점이다. `uart.yaml`의 명령어는 `MOVE/STOP/HOME/QR_SCAN/DETECT`, 응답은 `OK/BUSY/DONE/ERROR`로 되어 있는데, 이는 v1.0 UART 프로토콜(`READY/RUN/RESUME/STATE/ACK/TASK/PING/PONG/COMPLETE`, Chapter 5·7)과 **일치하지 않는 구버전**이다. 즉 `uart.yaml`은 **과거 설계의 잔존물**이며 현재 시스템 동작에 영향을 주지 않는다.

### `logging.conf` — 로드 안 됨

`logging.conf`는 표준 `logging.config.fileConfig` 형식의 로깅 설정이지만, **코드에서 `fileConfig`로 로드하지 않는다.** 현재 로깅은 대부분 `print()` 기반이다. `logging.conf`는 참고용으로만 남아 있다.

> **Implementation Note.** 두 파일을 실제로 쓰려면: `uart.yaml`은 현재 프로토콜에 맞게 갱신 후 로더를 붙이거나(권장하지 않음 — 이미 `settings.py`가 UART를 관리), Chapter 15(Legacy)로 이관한다. `logging.conf`는 `main.py` 초기화에서 `logging.config.fileConfig("config/logging.conf")`로 로드하면 활성화된다. 둘 다 향후 정리 대상이며 현재는 미사용임을 명시한다.

---

## 14.7 보안 — `API_KEY`

`api_key`는 AWS REST 인증(`X-API-Key`)의 핵심 값이다. 다음 규약을 지킨다.

- **하드코딩 기본값에 의존하지 않는다.** `settings.py`에는 fallback 기본값이 박혀 있으나, **운영에서는 반드시 `.env`의 실제 값으로 덮어써야 한다.**
- **`change-me`를 그대로 쓰지 않는다.** `.env.example`의 `API_KEY=change-me`는 자리표시자다. 운영 값은 랜덤(예: `openssl rand -hex 24`)으로 생성한다.
- **양쪽이 같아야 한다.** AWS `.env`, Jetson `.env`, (OTA를 쓰면) GitHub Secret의 API_KEY가 **동일한 랜덤값**이어야 인증이 통과한다.
- **커밋 금지.** 실제 `.env`, AWS 자격증명, 키는 절대 커밋하지 않는다. 공유는 `.env.example`(자리표시자)로만.

> **주의.** `settings.py`에 실제처럼 보이는 hex 기본값이 박혀 있는 것은 개발 편의를 위한 fallback이다. 운영 배포 전 이 값이 `.env`로 확실히 덮여 있는지 점검할 것.

---

## 14.8 Design Principles

| 원칙 | 설명 |
| --- | --- |
| Single Source (Static) | 런타임 정적 설정의 기준은 `settings.py` 하나. 여러 곳에 흩지 않는다. |
| Static vs Dynamic | 부팅 설정=Config, 운영 정책(max_view 등)=SQLite. 섞지 않는다. |
| Env Over Default | `.env` 값이 코드 기본값보다 우선. 배포 환경별 오버라이드. |
| Frozen | `Config`는 불변. 런타임 중 설정이 바뀌지 않는다. |
| Safe Defaults | 기본값은 안전한 쪽(`aws_enabled=false`, `vision_mode=mock`)으로. |
| Secrets Externalized | 비밀값은 `.env`(커밋 금지), 공유는 `.env.example`(자리표시자). |
| Honest About Dead Files | 미사용(`uart.yaml`/`logging.conf`)은 사용처럼 위장하지 않고 명시한다. |

---

## 14.9 Summary

`config/` 디렉터리는 STREW_VISION의 **부팅 설정 계층**이다. 런타임이 실제로 읽는 것은 `settings.py`의 `Config`(frozen dataclass) 하나이며, 값은 `.env`에서 로드하고 없으면 코드 기본값을 쓴다. 정체성·AWS·MQTT·OTA·UART·비전/YOLO·상태 DB 경로 등 부팅에 필요한 정적 값을 여기서 관리한다.

이 챕터의 핵심 경계는 **정적 설정 vs 동적 정책**이다. "장비를 어떻게 켜는가"(포트·해상도·AWS on/off)는 Config가, "운영 중 어떤 기준으로 판단하는가"(`max_view`, `confidence_threshold`)는 **SQLite `system_config`**(Chapter 10)가 관리한다. Config는 부팅 시 한 번 정해져 불변이고, 운영 정책은 SQLite에서 동적으로 조정된다 — 이 분리가 v2.0의 의도된 설계다.

As-Is로 정직하게 남기는 사실 두 가지: `uart.yaml`·`logging.conf`는 디렉터리에 있으나 **코드에서 로드되지 않으며**(특히 `uart.yaml`은 구버전 프로토콜 잔존물), `.env.example`은 `settings.py` 기본값과 일부 어긋난다(`VISION_MODE`, `YOLO_MODEL_PATH`, `API_KEY`). 보안상 `API_KEY`는 반드시 실제 랜덤값으로 교체하고 커밋하지 않는다.

---

## 부록. config/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 사용 | 역할 |
| --- | --- | --- |
| `settings.py` | ✅ | 런타임 설정 기준(`Config` frozen dataclass, `.env` 로드) |
| `__init__.py` | ✅ | 패키지 초기화(문서 주석) |
| `logging.conf` | ❌ 미사용 | 로깅 설정(참고용, `fileConfig` 미호출) |
| `uart.yaml` | ❌ 미사용 | UART 설정(구버전 프로토콜 잔존, 미로드) |
| `.env` | (런타임) | 실제 비밀·환경값. **커밋 금지** |
| `.env.example` | (공유) | 자리표시자 예시(일부 키 누락·불일치, 14.5) |
