# 02. Jetson 비전 파이프라인 (카메라 + TensorRT + 스트림)

전체 경로: `IMX708 RG10 RAW → RawCsiCamera(ISP) → BGR → CsiCameraVisionSource(YOLO/TensorRT) → VisionResult`

## A. 카메라 캡처 — 두 백엔드

`frame_hub.SharedFrameCamera(cv2, idx, w, h)`가 카메라 1개를 잡고 `get_latest_frame()`(BGR numpy)로
여러 소비자(추론 + 스트림)에게 나눠준다. `CAMERA_BACKEND` 환경변수로 백엔드 선택:

### 1) RAW (기본, `CAMERA_BACKEND=raw`) — `raw_camera.RawCsiCamera`
nvargus가 이 IMX708에서 뿌옇게(소프트/저대비) 나와서 **RG10 RAW를 v4l2로 직접 받아 Python에서 ISP**:
```
v4l2-ctl --stream-mmap RG10 → stdout 파이프
 → uint16 & 0x03FF (10bit)
 → Black level 제거 (-64)
 → White Balance (mosaic 게인맵)
 → cv2.cvtColor(BayerBG2BGR)  ← ★ 이 센서는 BGGR = "BG"
 → scale(0.8) → gamma(0.6)
 → BGR
```
**튜닝값(`.env` `RAW_*`로 조절, 코드 수정 불필요):**
```
RAW_BAYER=BG      ← ★ 필수(RG로 하면 R↔B 바뀌어 파랗게 나옴)
RAW_WB=1.0,0.476,0.87
RAW_SCALE=0.8     ← 밝기(흰색=255/흰RAW값)
RAW_GAMMA=0.6     ← 학습 도메인 매칭용(YOLO 입력에도 적용)
RAW_EXPOSURE=45000  RAW_GAIN=64
```
- Black level=64는 렌즈 완전히 막고 측정(min61/max68/mean64).
- 카메라 단독 테스트: `python3 scripts/raw_camera.py --save out --frames 30`

### 2) nvargus (`CAMERA_BACKEND=nvargus`) — frame_hub 내장
`nvarguscamerasrc ! ...NVMM... ! nvvidconv ! BGRx ! videoconvert ! BGR ! appsink`.
GStreamer Python 바인딩(`gi.repository.Gst` + `GstApp`)으로 직접 파이프라인. OpenCV는 GStreamer가
없어서 못 씀. **단점: 이 카메라에선 뿌옇고, X 디스플레이+TensorRT와 dmabuf 경합.** 그래서 RAW가 기본.

## B. TensorRT 추론 — `camera.CsiCameraVisionSource`

`__init__`에서 `best.engine`을 deserialize → 컨텍스트/스트림/버퍼 할당 → **출력 레이아웃 자동 판별**.
`_read_with_yolo(frame)`에서 letterbox → CHW/255 → execute → decode → NMS → best → VisionResult.

### ★ CUDA 컨텍스트 스레드 문제 (매우 중요)
추론은 **리스너 스레드**에서 호출되는데 엔진은 메인 스레드(`__init__`)에서 만들어짐. CUDA 컨텍스트는
스레드에 묶여서, 그냥 두면 `Cuda Runtime (invalid resource handle)`. 해결:
```python
cuda.init(); self.cuda_ctx = cuda.Device(0).make_context()  # __init__에서
# 버퍼 할당 후 self.cuda_ctx.pop()  ← 현재 스레드에서 떼어둠
# 추론 시(리스너 스레드): self.cuda_ctx.push() ... finally: self.cuda_ctx.pop()
```
`pycuda.autoinit` 쓰지 말 것(현재 스레드 고정). 테스트 스크립트(단일 스레드)는 autoinit도 OK.

### ★ 출력 레이아웃 자동 판별 (v5/v8/seg)
현재 엔진은 **YOLOv5-seg**: 출력 2개 — `output0 (1,25200,40)` 검출 + `output1 (1,32,160,160)` 마스크.
`_out_shapes`로 검출 바인딩을 shape로 찾음:
```python
for pos, shp in enumerate(out_shapes):
    if shp[-1] in (5+nc, 5+nc+32):   # v5 det(8) 또는 v5-seg(40)
        det_pos, det_w, layout = pos, shp[-1], "v5"; break
    if shp[1] == 4+nc:               # v8 (1,4+nc,8400)
        det_pos, det_w, layout = pos, 4+nc, "v8"; break
```
디코드 분기(`_read_with_yolo`):
```python
if layout=="v5": raw = det.reshape(-1, det_w); decode_yolov5_output(...)
else:            raw = det.reshape(4+nc, -1); decode_yolov8_output(...)
```

### 출력 형식 정리 (decode 핵심)
| 모델 | 출력 shape | 열 구성 | conf | reshape |
|---|---|---|---|---|
| YOLOv8 det | (1, 4+nc, 8400) | box,class (obj 없음) | class | (4+nc, -1) |
| YOLOv5 det | (1, 25200, 5+nc) | box,obj,class | obj×class | (-1, 5+nc) |
| YOLOv5-seg | (1, 25200, 5+nc+32) + mask | box,obj,class,mask32 | obj×class | (-1, 40); 마스크 무시 |

`decode_yolov5_output`(yolo_postprocess.py)은 `[:,:4]`box, `[:,4]`obj, `[:,5:5+nc]`class로 슬라이스 →
seg의 마스크 32열 자동 무시. **마스크(segmentation)는 구현 안 함 — detection head만 사용.**

### 클래스 (3개, 순서 고정)
```
0: healthy_leaf   1: old_leaf   2: powdery_mildew
```
`.env` `YOLO_CLASS_NAMES=healthy_leaf,old_leaf,powdery_mildew` (또는 settings.py 기본값).
**★ 2개로 남아있으면 nc 불일치 → 40폭 seg 출력을 못 알아보고 마스크 출력을 집어 `reshape(6,-1)` 크래시.**
로그 `[camera] ... width=40 layout=v5`면 정상, `width=6 layout=v8`면 nc=2 잘못됨.

### 작업 매핑 (command.py)
```
healthy_leaf → OBSERVE(관찰)
old_leaf     → REPLACE(교체)
powdery_mildew → REPLACE(교체) + 관리자 승인(DISEASE_STATUSES)
```
`aggregate_views`: 4-View 중 가장 심각한 status 채택(powdery > old_leaf > healthy_leaf).

## C. 라이브 스트림 (MJPEG, WebRTC 대체)

aiortc/av가 나노 Python3.6/aarch64에서 빌드 불가 → **MJPEG(표준 http.server, 의존성 0)**.
- **main.py 내장**: `robot/vision_stream.VisionStreamServer`가 `vision.get_stream_frame`을 읽어 `:8090`으로 송출.
  - `get_stream_frame()`: 최근 검사(박스 그린) 프레임이 2초 이내면 그걸, 아니면 raw 라이브.
  - camera.py `_read_with_yolo`가 검사 시 모든 NMS 박스를 그려 `_last_annotated`에 저장(엔진 1개 재사용).
- **카메라 1개 = 1프로세스** 제약: main.py 돌 땐 `stream_mjpeg.py` 따로 돌리지 말 것(카메라·8090 충돌).
- 단독 테스트: `python3 scripts/stream_mjpeg.py --no-boxes`(카메라만) / `python3 scripts/stream_mjpeg.py`(박스).
- 대시보드 `live.html`에 `<img src="http://<젯슨IP>:8090/stream">`로 임베드(구현됨).

## D. 엔진 변환 (PC → 젯슨)
학습·export는 PC(RTX GPU), 최종 `.onnx → .engine`만 젯슨:
```bash
# 젯슨
/usr/src/tensorrt/bin/trtexec --onnx=models/best.onnx --saveEngine=models/best.engine --fp16
```
- ONNX **opset ≤ 13**, `imgsz=640` 고정(TensorRT 8.2 호환).
- `[TRT][W] engine plan across different models of devices` 경고 = 다른 장치에서 빌드됨 → 이 젯슨에서 재빌드 권장.
