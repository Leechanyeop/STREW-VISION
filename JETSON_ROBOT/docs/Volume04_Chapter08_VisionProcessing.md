# Chapter 8. Vision Processing

> STREW_VISION v2.0 · Volume 04 · Jetson Nano Software Design
> 본 장은 실제 `ai/detector/` 구현을 기준으로 작성되었다.
>
> **Chapter 7과의 역할 분리 (중복 방지)**
> - Chapter 7 (Event Processing) : **언제** AI를 호출하는가 — `STATE(VISION_READY)` 이벤트 수신 시
> - Chapter 8 (Vision Processing) : **어떻게** AI가 동작하는가 — Vision 내부 구현
>
> **역할 분담 (불변)**
> - Arduino Mega : Vision을 수행하지 않는다. `STATE(VISION_READY)`로 촬영 준비 완료만 통보한다.
> - Jetson (Vision Module) : 카메라 획득 → AI 추론 → Detection Result 생성. Motion은 다루지 않는다.

---

## 8.1 Overview

RobotAgent는 `STATE(VISION_READY)` 이벤트를 수신했을 때만 AI 추론을 수행한다(Chapter 7). 이때 실제 영상 획득과 객체 검출을 담당하는 것이 Vision Module(`ai/detector/`)이다.

Vision Module은 RobotAgent로부터 독립적으로 동작한다. RobotAgent는 `vision.read()`를 호출하여 결과(`VisionResult`)만 받을 뿐, 카메라 종류나 추론 방식(Mock/YOLO)의 내부 구현은 알지 못한다. 이러한 추상화를 통해 카메라나 모델이 바뀌어도 RobotAgent와 이벤트 처리 로직은 수정할 필요가 없다.

Vision Module의 출력은 Motion 명령이 아니라 **판독 결과(status/confidence/label)**이며, 이를 Task로 변환하는 것은 RobotAgent의 몫이다.

---

## 8.2 Vision Architecture

```
RobotAgent
    │  vision.read()  (STATE(VISION_READY) 시에만 호출)
    ▼
Vision Source  (VisionSource 추상 인터페이스)
    │
    ├─ MockVisionSource       (개발/시뮬용 - 무작위 status)
    └─ CsiCameraVisionSource  (실기기 - 카메라 + YOLO/TensorRT)
           │
           ▼
      Image Frame  (SharedFrameCamera에서 최신 프레임)
           │
           ▼
      AI Detector (YOLOv8 TensorRT + 후처리)
           │
           ▼
      VisionResult  (label / confidence / status / bbox)
           │
           ▼
RobotAgent  (status_to_task 로 TASK 변환)
```

Vision Module은 `create_vision_source()` 팩토리로 생성되며, 설정(`vision_mode`)에 따라 Mock 또는 실제 카메라 소스를 반환한다.

---

## 8.3 Vision Source

Vision Source는 "영상을 읽어 판독 결과를 돌려주는" 단일 인터페이스로 추상화되어 있다. 핵심은 `read()` 메서드 하나다.

```python
class VisionSource:
    def read(self) -> VisionResult:
        raise NotImplementedError
```

### 8.3.1 팩토리 (`create_vision_source`)

RobotAgent 초기화 시 이 팩토리로 Vision Source를 생성한다. `mode`가 `"mock"`이면 개발용 소스를, 아니면 실제 카메라 소스를 반환한다.

```python
def create_vision_source(mode, camera_index, frame_width, frame_height, yolo_model_path) -> VisionSource:
    if mode.lower() == "mock":
        return MockVisionSource()
    return CsiCameraVisionSource(camera_index, frame_width, frame_height, yolo_model_path)
```

### 8.3.2 MockVisionSource (개발/시뮬)

하드웨어 없이 시스템을 검증하기 위한 소스. 무작위 `status`를 반환하여 정상/병해충 흐름을 모두 시험할 수 있다.

```python
class MockVisionSource(VisionSource):
    def read(self) -> VisionResult:
        return VisionResult(
            label="mock-object", confidence=0.80, x_center=640, y_center=360,
            width=160, height=120,
            status=random.choice(["healthy", "powdery_mildew", "missing_plant", "empty_cell"]),
        )
```

### 8.3.3 CsiCameraVisionSource (실기기)

실제 카메라(공유 프레임 버퍼)와 YOLOv8 TensorRT 엔진을 사용한다. 카메라 캡처는 `SharedFrameCamera`(백그라운드 스레드)가 전담하고, `read()`는 최신 프레임을 가져와 추론만 수행한다. 모델(`.engine`)이 없으면 단순 윤곽선 검출로 폴백한다.

---

## 8.4 AI Detection Pipeline

실기기 검출은 두 경로로 구성된다. 모델(`.engine`)이 있으면 **YOLOv8 TensorRT** 경로를, 없으면 **Contour(윤곽선) Fallback** 경로를 사용한다. 어느 경로든 최종 출력은 동일한 `VisionResult`이므로 상위 계층은 차이를 알 필요가 없다.

```
                 Latest Frame (SharedFrameCamera)
                          │
              ┌───────────┴───────────┐
              ▼                        ▼
      [모델 있음] YOLO 경로     [모델 없음] Fallback 경로
              │                        │
        Letterbox 전처리          Grayscale / Threshold
              │                        │
        TensorRT Engine            Contour 검출
              │                        │
        Decode → NMS               최대 영역 선택
              │                        │
              └───────────┬───────────┘
                          ▼
                    VisionResult
```

### 8.4.1 YOLOv8 TensorRT 경로

`_read_with_yolo()`에서 3단계로 수행된다.

1. **전처리** — letterbox(비율 유지 + 회색 패딩) → RGB → CHW → 0~1 정규화
2. **엔진 실행** — host 버퍼 → GPU → `execute_async_v2` → 출력 회수
3. **후처리** — YOLOv8 출력 디코드 → NMS → 최고 confidence 1개 → 원본 좌표 변환

```python
# 3) 후처리: (4+nc, 8400) 디코드 -> NMS -> 최고 confidence 1개 -> 원본 좌표
num_classes = len(self.yolo_class_names)
raw = np.asarray(self.host_outputs[0]).reshape(4 + num_classes, -1)
detections = decode_yolov8_output(raw, num_classes, self.yolo_conf_threshold)
kept = nms(detections, self.yolo_iou_threshold)
```

후처리 로직(`decode_yolov8_output`, `nms`, `letterbox_params`)은 `ai/detector/yolo_postprocess.py`에 순수 numpy로 분리되어 있어, TensorRT/카메라 없이도 단위 테스트가 가능하다.

### 8.4.2 Contour Fallback 경로

`.engine` 파일이 없는 환경(모델 미배포 등)에서는 OpenCV 윤곽선 검출로 폴백한다. 가장 큰 윤곽 영역을 바운딩 박스로 반환하며, 시스템 흐름 자체가 멈추지 않도록 하는 안전장치다.

> **참고.** confidence threshold(`yolo_conf_threshold`)와 클래스 목록(`yolo_class_names`)은 설정(config)에서 주입되며, 학습 클래스가 곧 `status` 값이 된다(healthy/powdery_mildew/missing_plant/empty_cell).

---

## 8.5 Detection Result (`VisionResult`)

Vision Module의 출력은 `VisionResult` 데이터클래스다. RobotAgent는 이 중 **`status`**를 사용해 TASK를 결정한다.

```python
@dataclass
class VisionResult:
    label: Optional[str]
    confidence: Optional[float] = None
    x_center: Optional[int] = None
    y_center: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    status: Optional[str] = None

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)
```

| 필드 | 의미 |
| --- | --- |
| `status` | 판독 상태 (healthy / powdery_mildew / missing_plant / empty_cell) — **TASK 결정 기준** |
| `confidence` | 검출 신뢰도 |
| `label` | 검출 클래스 라벨 |
| `x_center~height` | 바운딩 박스 |

`to_payload()`는 결과를 dict로 변환하여 AWS(vision event)와 TASK 변환에 사용된다.

> **경계 명시.** `status`는 Vision Module이 생성하는 **판독 결과**이며, Motion이나 작업(Task)의 의미를 포함하지 않는다. `status`를 TASK(OBSERVE/REPLACE/SKIP)로 변환하는 것은 RobotAgent가 담당하고, 그 TASK로 Motion을 수행하는 것은 Arduino Mega가 담당한다. 즉 Vision Module은 "무엇으로 보이는가"까지만 책임지고, "무엇을 할 것인가"는 상위 계층이 결정한다.

---

## 8.6 Integration with RobotAgent

Vision Module과 RobotAgent의 연결 지점은 `_handle_vision_ready()` 한 곳이다(Chapter 7.5).

```
STATE(VISION_READY)          # Mega가 촬영 준비 완료 통보
   → vision.read()           # Vision Module: 프레임 획득 + AI 추론
   → to_payload()            # VisionResult → dict (status 포함)
   → status_to_task(status)  # RobotAgent: status → OBSERVE/REPLACE/SKIP
   → TASK                    # Jetson → Mega
```

역할 경계가 여기서 분명하다.
- **Vision Module** : `status`를 만든다 (인식).
- **RobotAgent** : `status`를 `TASK`로 바꾼다 (변환). Replace 여부를 스스로 결정하지 않는다.
- **Arduino Mega** : `TASK`를 받아 Motion을 수행한다 (제어).

Vision Module은 `TASK`나 Motion을 전혀 알지 못하며, RobotAgent도 카메라/YOLO 내부를 알지 못한다. 두 계층은 `VisionResult`라는 인터페이스로만 연결된다.

---

## 8.7 Vision Design Principles

| 원칙 | 설명 |
| --- | --- |
| On-Demand Detection | AI 추론은 `STATE(VISION_READY)` 시에만 수행한다(상시 추론 아님). |
| Event-Driven | 카메라 프레임 순회가 아니라 이벤트에 의해 추론이 트리거된다. |
| Camera Independence | Mock/실카메라를 팩토리로 교체 가능. RobotAgent는 영향 없음. |
| Detector Independence | 모델(.engine) 유무·종류가 바뀌어도 `read()` 인터페이스는 불변. |
| Loose Coupling | Vision과 RobotAgent는 `VisionResult`로만 연결된다. |

---

## 8.8 Summary

Vision Module(`ai/detector/`)은 RobotAgent가 `STATE(VISION_READY)` 시점에 호출하는 AI 추론 계층이다. `create_vision_source()` 팩토리가 설정에 따라 Mock 또는 실카메라 소스를 생성하며, 실기기에서는 YOLOv8 TensorRT 경로(모델이 없으면 Contour Fallback 경로)로 객체를 검출한다.

Vision Module의 출력인 `VisionResult`는 Motion 명령이 아니라 판독 결과(`status`)이며, 이를 TASK로 변환하는 것은 RobotAgent의 역할이다. 이러한 분리를 통해 Jetson은 인식(Vision)·변환(RobotAgent)을, Arduino Mega는 제어(Motion)를 담당하는 명확한 계층 구조를 유지한다.

---

## Implementation Note (Future Extension)

향후 Phase C에서는 단일 시점 추론이 **다중 시점(Multi-View, TOP/LEFT/RIGHT/LOW/FRONT) 반복 추론**으로 확장되며, confidence threshold 기반 반복 검사와 **Inspection 이미지 저장** 기능이 추가된다. 본 확장은 Vision Module 내부에서 이루어지며, RobotAgent와의 인터페이스(`vision.read()` → `VisionResult`)는 그대로 유지된다.

본 내용은 향후 확장 계획이며 현재 구현에는 포함되지 않는다.

---

## 부록. ai/detector/ 파일 맵 (GPT/협업자 참고용)

| 파일 | 역할 |
| --- | --- |
| `camera.py` | VisionSource 추상 + Mock/CSI 구현 + YOLO 추론 + `create_vision_source` 팩토리 |
| `result.py` | `VisionResult` 데이터클래스 + `to_payload()` |
| `yolo_postprocess.py` | YOLOv8 출력 디코드 / NMS / letterbox (순수 numpy, 테스트 가능) |
| `frame_hub.py` | `SharedFrameCamera` — 백그라운드 프레임 캡처 (다중 소비자 공유) |
| `validator.py` | 검출 결과 검증 보조 |
