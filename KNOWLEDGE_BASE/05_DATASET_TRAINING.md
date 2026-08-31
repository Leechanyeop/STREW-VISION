# 05. 데이터셋 · 학습 · 변환

## 큰 그림
```
[PC(GPU)] 학습 → best.pt → export → best.onnx (opset≤13, imgsz=640, --simplify)
   ↓ scp
[Jetson] trtexec --fp16 → best.engine → 추론
```
**학습은 PC에서만.** 젯슨 나노는 학습 못 함(4GB, 구버전 스택). 젯슨은 데이터 수집·엔진빌드·추론만.

## 모델 현황
- 현재 엔진: **YOLOv5-seg**, 3클래스(healthy_leaf/old_leaf/powdery_mildew), 출력 `1x25200x40`.
  - detection head만 사용(마스크 32열 무시). ~14 FPS, GPU ~65ms.
- 이전엔 YOLOv8(2클래스, `1x6x8400`)이었음 — decode 자동판별로 둘 다 지원(`02_JETSON_VISION.md`).
- **흰가루병 검출이 약함**: 학습 데이터가 인터넷 도메인이라 실제 온실 카메라와 안 맞음 → 도메인 재학습 필요.

## 데이터 수집 도구 (우리가 만든 것)
| 스크립트 | 위치 | 용도 |
|---|---|---|
| `capture_dataset.py` | JETSON_ROBOT/scripts | 젯슨 CSI로 N장 촬영 + `--send`로 PC 전송(scp/rsync). `--manual`(Enter촬영) |
| `extract_frames.py` | `C:\VISION_SOURCE` | 영상(.mp4)→프레임 추출. `--fps/--interval-sec/--target/--all`, 파일명=영상명 |
| `prepare_dataset.py` | `C:\VISION_SOURCE` | Roboflow 2개 데이터셋 리맵+병합 |

### prepare_dataset.py가 한 일 (재사용 시 참고)
2개 Roboflow 데이터셋을 우리 2클래스로 통합했던 로직:
- **클래스 리맵**: 각 셋이 자기 기준 0번부터라 충돌 → 통일 매핑
- **불필요 클래스 드롭**: 6클래스 중 안 쓰는 것 제거
- **폴리곤 → 바운딩박스 변환**: 세그멘테이션 라벨(class + 점들)을 min/max로 박스화
- **valid 없는 셋은 train에서 20% split**
- **주의**: 라벨 파일 trailing newline 없으면 `cat`으로 합칠 때 경계 줄이 붙어 카운트 왜곡 → 파일별로 셀 것

## 학습 스캐폴드 (`C:\VISION SOURCE`, 공백 주의)
YOLOv5n 학습 환경: `setup.bat/sh`(clone+venv+install), `train.bat/sh`, `export.bat/sh`, `data.yaml`(클래스),
`jetson_patch/`(v5 decode). `vision-weght/yolov5/`에 실제 yolov5 repo + export.py.

### 학습 → 변환 명령
```bash
# PC: 학습
python train.py --img 640 --batch 16 --epochs 100 --data data.yaml --weights yolov5n.pt
# PC: ONNX export (★ opset 12, TensorRT 8.2 호환)
python export.py --weights best.pt --include onnx --opset 12 --img 640 --simplify
# Jetson: engine
/usr/src/tensorrt/bin/trtexec --onnx=models/best.onnx --saveEngine=models/best.engine --fp16
```

## ★ 클래스 순서 = 절대 규칙
`data.yaml`의 names 순서 == 젯슨 `YOLO_CLASS_NAMES` == command.py 매핑. **하나라도 어긋나면 라벨 뒤바뀜.**
현재: `0:healthy_leaf, 1:old_leaf, 2:powdery_mildew`.

## 흰가루 검출 개선 로드맵 (남은 큰 작업)
1. 젯슨 카메라로 **실제 온실 흰가루 잎** 100~200장 수집(`capture_dataset.py`)
2. Roboflow 라벨링(같은 클래스 순서)
3. `prepare_dataset.py`로 기존 데이터에 병합
4. PC 재학습 → onnx(opset12) → 젯슨 engine 교체
5. `.env YOLO_CLASS_NAMES` 그대로면 코드 무수정
- **RAW 카메라 색/밝기를 학습 프레임과 매칭**해야 conf 유지(예쁜 게 아니라 도메인 일치가 목표).

## 자동 재학습 루프 (구상, 미구현)
젯슨이 raw 축적 → 서버 업로드 → GPU 재학습 → onnx → OTA로 젯슨 배포. 걸림돌: (a) 학습용 GPU 노드 필요,
(b) 라벨(무인 auto-label은 약한 클래스에 독). 반자동(사람 라벨 배치)이 정석. 관리자 승인 데이터를 약라벨로 재활용 가능.
