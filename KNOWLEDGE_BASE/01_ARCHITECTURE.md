# 01. 시스템 아키텍처

## 하드웨어 스택
| 구성 | 역할 | 비고 |
|---|---|---|
| **Jetson Nano** (Tegra X1, 4GB) | AI 추론(YOLO/TensorRT), 상태머신, 통신 허브, SQLite 상태 저장 | JetPack 4.x, Python 3.6, TensorRT 8.2, CUDA 10.2, OpenCV 3.2(GStreamer 없음) |
| **Arduino Mega 2560** | 물리 동작(모터/그리퍼), LCD 표시. 상태 저장 안 함 | UART로 Jetson과 통신, 16x2 I2C LCD(0x27) |
| **IMX708 CSI 카메라** | 딸기 잎 촬영. RG10(10-bit Bayer RAW) 출력 | ArduCam 드라이버(패치 커널). BGGR 패턴 |
| **ESP32** | 온습도 센서(sensor1~3) | MQTT `esp32/sensor`로 2초마다 발행 |
| **PC (로컬)** | AWS FastAPI 서버 + 대시보드 + MQTT 브로커(Mosquitto) | 프로젝트 정책상 클라우드 안 씀, 전부 로컬 |

## 소프트웨어 데이터 흐름
```
IMX708 ──RG10 RAW──▶ Jetson(RAW ISP → BGR)
                        │
                        ▼ YOLO(TensorRT best.engine) 추론
                     VisionResult(label/conf/box/status)
                        │
        ┌───────────────┼────────────────────────┐
        ▼               ▼                         ▼
   Mega(UART)      AWS(HTTP)               MJPEG 스트림(:8090)
   TASK 지시       진행/판독/상태 보고        대시보드 라이브 영상
        │               │
   물리동작·LCD      대시보드 표시 + 관리자 승인
                        ▲
   ESP32 ──MQTT──▶ AWS 직접 구독(온습도) ──▶ 대시보드 인디케이터
```

## Jetson 로봇 소프트웨어 구조 (`JETSON_ROBOT/`)
```
main.py                      진입점. RobotAgent 생성 → run_forever()
config/settings.py           모든 설정(.env + 기본값). frozen dataclass
robot/
  state_machine.py           ★ RobotAgent - 전체 오케스트레이션(하트비트/리스너/스케줄러 스레드)
  command.py                 UART 상수 + status_to_task + aggregate_views(4-View 종합)
  uart.py                    ArduinoLink - 시리얼 송수신(라인 버퍼링)
  vision_stream.py           ★ VisionStreamServer - MJPEG 스트림(main.py 내장)
  webrtc_publisher.py        (사용 안 함) aiortc 기반, 나노 빌드 불가 → MJPEG로 대체
ai/detector/
  camera.py                  ★ CsiCameraVisionSource - 엔진 로드/추론/decode 자동판별, get_stream_frame
  frame_hub.py               ★ SharedFrameCamera - 카메라 1개 공유(RAW 기본, nvargus 옵션)
  raw_camera.py              ★ RawCsiCamera - v4l2 RG10 → BGR ISP
  yolo_postprocess.py        decode_yolov8_output / decode_yolov5_output / nms / letterbox
  result.py                  VisionResult dataclass
storage/state_db.py          SQLite(Source of Truth) - current_task/system_config/detection_log 등
cloud/
  api_client.py              CloudClient - AWS HTTP 호출(post_progress/vision_event/decision 등)
  mqtt.py, sync.py, sensor_bridge.py
mega_firmware/mega_firmware.ino  ★ Mega 펌웨어(UART v1.0 + LCD)
scripts/                     test_vision.py, stream_mjpeg.py, raw_camera.py, capture_dataset.py 등
models/                      best.engine, best.onnx, best.pt, test_engine_cam.py
data/robot_state.db          SQLite 상태 DB(런타임 생성)
VERIFY.md                    브링업 검증 런북
```

## AWS 서버 구조 (`STREW-VISION_AWS/`)
```
app/
  main.py                    FastAPI - /robot/* /vision/* /stream/* /sensor/* /ai/* /api/ota/*
  settings.py                pydantic Settings(.env). mqtt_enabled 등
  repository.py              LocalJsonStore / DynamoStore(로컬 JSON 기본)
  schemas.py                 Pydantic 모델
  mqtt_ingest.py             ESP32 esp32/sensor 직접 구독 → 저장
  static/                    대시보드: index.html, admin.html, details.html, live.html, schedule.html, common.js
jetson_greenhouse_system/    (구 Node/Express 대시보드 - 참고용)
infra/terraform/             (미사용, 로컬 운영)
```

## RobotAgent 스레드 모델 (state_machine.py)
- **메인 스레드**: `run_forever()` - 그냥 살아있음(1초 sleep). 종료 시 close().
- **리스너 스레드**(`_uart_listener_loop`): UART 수신 단일 소유자. READY/STATE/COMPLETE/ERROR/PONG 처리.
  ★ **여기서 vision.read() 추론이 호출됨** → CUDA 컨텍스트 스레드 문제의 근원(해결됨: make_context+push/pop).
- **하트비트 스레드**(`_heartbeat_loop`): 1초 PING, 5초 무응답 시 Mega Offline. 5초마다 runtime status 보고.
- **스케줄러 스레드**(`_schedule_loop`): 주간 스케줄(요일×시각) 확인.
- **VisionStreamServer**: MJPEG HTTP 서버(별도 스레드) + 인코딩 스레드.

## 상태 관리 원칙
- **Jetson SQLite = Source of Truth**(Recovery 기준). Mega는 상태 저장 안 함(EEPROM 제거).
- 전원/네트워크 끊겨도 SQLite로 셀 단위 재개(RESUME).
- 대시보드 설정(cycle_count/max_view/confidence_threshold/total_cells) → 새 사이클 시작(RUN) 시 pull 적용.
