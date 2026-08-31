# STREW_VISION 지식 창고 (Knowledge Base) — 다른 AI를 위한 인수인계

> 이 문서 묶음은 **STREW_VISION 딸기 스마트팜 로봇 프로젝트**의 모든 지식을 정리한 것이다.
> 새 세션/새 AI가 이 프로젝트를 이어받아 작업할 수 있도록, 아키텍처·코드 위치·설정·디버깅 함정·
> 실행법·현재 상태를 담았다. **먼저 이 파일을 읽고, 필요한 챕터로 이동하라.**

## 이 프로젝트가 뭔가 (한 문단)
딸기 온실을 순회하며 각 셀(재배 위치)의 딸기 잎을 **IMX708 CSI 카메라 + YOLO(TensorRT)**로 검사해
`healthy_leaf / old_leaf / powdery_mildew(흰가루병)`을 판별하고, 병해 의심 시 관리자 승인을 받아
교체/관찰/스킵 작업을 수행하는 로봇이다. **Jetson Nano**가 두뇌(AI·상태관리·통신), **Arduino Mega**가
물리 동작(모터·LCD), **AWS(로컬 PC의 FastAPI)**가 대시보드·저장·관리자 승인, **ESP32**가 온습도 센서다.

## 시스템 3-파트 구조
```
[Arduino Mega]  ──UART v1.0──  [Jetson Nano]  ──HTTP/MQTT──  [AWS FastAPI + 대시보드]
 물리동작·LCD                    AI추론·상태머신·통신             저장·관리자승인·모니터링
                                     │
                                  IMX708 CSI 카메라 (RAW/YOLO)
[ESP32] ──MQTT(esp32/sensor)──▶ [AWS 직접 구독] (온습도)
```

## 저장소 위치 (중요 — 2개로 분리됨)
- **Jetson 로봇 코드**: `C:\STREW_VISION\JETSON_ROBOT` (git repo `STREW-VISION.git`)
  - 실제 젯슨 경로: `/home/STREW-VISION/JETSON_ROBOT` (SSH: `blackhood@HAXASYS`)
- **AWS 서버·대시보드**: `C:\AWS_SYSTEM\STREW-VISION_AWS` (git repo `STREW-VISION_AWS.git`)
  - 로컬 PC에서 실행(FastAPI). AWS 클라우드엔 안 올림(프로젝트 정책).
- 이 둘은 `app/` HTTP API + MQTT로 통신. Jetson 코드를 AWS repo에 복제하지 말 것.

## 챕터 목차
| 파일 | 내용 |
|---|---|
| `01_ARCHITECTURE.md` | 전체 시스템·데이터 흐름·컴포넌트별 역할·주요 파일 지도 |
| `02_JETSON_VISION.md` | 카메라(RAW/nvargus), TensorRT 엔진, decode(v5/v8/seg), CUDA, 스트리밍 |
| `03_MEGA_UART.md` | UART v1.0 프로토콜, Mega 상태머신, LCD, 4-View 검사 |
| `04_AWS_DASHBOARD.md` | FastAPI 엔드포인트, MQTT 센서 수집, 대시보드 페이지, 설정 동기화 |
| `05_DATASET_TRAINING.md` | 데이터 수집·병합·라벨링, YOLOv5/v8 학습, ONNX→engine 변환 |
| `06_GOTCHAS.md` | **★ 디버깅 함정 총정리 (증상→원인→해결)** — 가장 자주 볼 파일 |
| `07_RUNBOOK.md` | 처음부터 실행·검증하는 순서(레이어별) |
| `08_STATE_AND_TODO.md` | 현재 완료 상태 + 남은 작업 + 알려진 이슈 |

## 새 AI가 지켜야 할 핵심 원칙 (먼저 읽어라)
1. **한 번에 한 레이어씩 검증.** 카메라 → 엔진/decode → 추론 스레드 → 통합 → 네트워크. 대부분의
   "안 됨"은 아래 레이어가 실제로 검증 안 된 것.
2. **젯슨 OpenCV는 CSI RAW를 못 연다.** nvargus(GStreamer) 또는 v4l2-RAW+Python ISP를 써야 함.
3. **카메라는 1프로세스만** 소유 가능(`/dev/video0`). main.py 돌 땐 별도 스트림 프로세스 금지.
4. **decode는 모델 종류·클래스 수와 정확히 일치**해야 함. 안 맞으면 conf 폭발/reshape 에러.
5. **CUDA 컨텍스트는 스레드에 묶임** — 워커 스레드 추론이면 make_context+push/pop.
6. **설정값은 모든 컴포넌트에서 일치**해야 함 (Jetson total_cells == Mega TOTAL_CELLS 등).
7. **네트워크는 상대 IP를 가리켜야 함** (자기 IP 아님), 서버는 0.0.0.0 바인딩.
8. **비밀키/env**: OS 환경변수가 `.env`를 덮어씀. `.env`/`.git` 비밀 커밋 금지.

## 현재 상태 한 줄
비전·카메라(RAW/BG)·MJPEG 스트림·대시보드·Mega 통신·LCD 다 연결됨. **막판 블로커: 젯슨 `.env`의
`YOLO_CLASS_NAMES`가 3개(healthy_leaf,old_leaf,powdery_mildew)여야 하는데 2개로 남아 추론 크래시 →
`total_cells=4`와 함께 적용 후 재시작하면 전체 작동.** 자세한 건 `08_STATE_AND_TODO.md`.
