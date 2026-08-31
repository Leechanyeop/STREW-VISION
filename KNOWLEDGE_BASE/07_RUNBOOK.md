# 07. 실행 · 검증 런북 (처음부터, 레이어별)

**한 번에 한 레이어씩 통과.** 각 단계 [명령] → [PASS] → [FAIL 시]. PASS 전엔 다음으로 안 감.
(원본 상세본: `JETSON_ROBOT/VERIFY.md`)

## 0. 최신 파일 반영 (PC → 젯슨 scp)
젯슨 실 경로 `blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT`. 이번 세션 변경 파일:
```
ai/detector/{raw_camera,frame_hub,camera,yolo_postprocess}.py
config/settings.py  robot/{command,state_machine,vision_stream}.py  scripts/*.py
```
Mega 펌웨어는 **Arduino IDE로 업로드**(LCD 반영).

### 젯슨 `.env` 필수값
```
CAMERA_BACKEND=raw
RAW_BAYER=BG
RAW_WB=1.0,0.476,0.87
RAW_SCALE=0.8
RAW_GAMMA=0.6
YOLO_CLASS_NAMES=healthy_leaf,old_leaf,powdery_mildew   ← ★ 3개
AWS_ENABLED=true
AWS_API_BASE=http://<PC_IP>:8000    ← 젯슨 자기IP(192.168.0.3) 아님!
MQTT_BROKER_HOST=<PC_IP>
```

## 1. 카메라 RAW
```bash
python3 scripts/raw_camera.py --save out --frames 30
```
PASS: `첫 프레임 OK`, `out/`에 정색(BG) 이미지, FPS. FAIL: `06_GOTCHAS.md` 카메라 섹션.

## 2. 엔진 + decode (★ 핵심)
```bash
python3 models/test_engine_cam.py --save out --frames 30   # models/ 에 있음
```
PASS 로그: `검출 출력 binding=?, width=40` + `out/`에 박스 + conf 0~1.
FAIL: `width=6`/`reshape (6,newaxis)` → YOLO_CLASS_NAMES 2개 → .env 3개로.

## 3. total_cells = Mega(4)
```bash
python3 -c "import sqlite3;c=sqlite3.connect('data/robot_state.db');c.execute(\"UPDATE system_config SET value='4' WHERE key='total_cells'\");c.commit();print(dict(c.execute('SELECT key,value FROM system_config')))"
```
(젯슨엔 sqlite3 CLI 없어서 Python. 바꾼 뒤 main.py 재시작해야 AWS에도 전파돼 유지)

## 4. AWS 서버 (PC)
```bash
# PC
cd C:\AWS_SYSTEM\STREW-VISION_AWS
uvicorn app.main:app --host 0.0.0.0 --port 8000
# Mosquitto LAN 리스너 + 방화벽 8000/1883
```
PASS: 젯슨 로그 `Report 'post_progress' successfully.` (Connection refused 없음).

## 5. 전체 main.py
```bash
cd /home/STREW-VISION/JETSON_ROBOT
python3 main.py
```
PASS 로그 순서:
```
[frame_hub] 카메라 백엔드=RAW
[raw_camera] 첫 프레임 OK
[camera] 출력 2개, 검출 pos=? width=40 layout=v5     ← ★ width=40
[stream] MJPEG 라이브 스트림 시작: http://0.0.0.0:8090/
[READY] Mega 부팅 완료 → [RUN] cycle_id=...
[VIEW] cell=1 view=TOP status=... conf=0.xx
[INSPECT] cell=1 종합판정 → [TASK] cell=1 ... → [COMPLETE]
```
Mega LCD: `Cell 1/4 MOVE → VIEW:TOP → TASK:REPLACE → DONE`.

## 6. 대시보드
- **live.html**: 스트림 URL `http://<젯슨IP>:8090/stream` → 영상 + 검사 박스
- **실시간 추론(오른쪽)**: 흰가루병/conf/Cell 갱신
- **현재 Cycle**: Cell 1→4 진행, 목표=무한, 셀4 후 재시작

## 증상별 FIX 요약
| 증상 | 조치 |
|---|---|
| `reshape (6,newaxis)` | .env YOLO_CLASS_NAMES 3개 |
| 셀1 멈춤 | 추론 크래시(위) 또는 total_cells≠4 |
| 사이클 1번 후 정지 | total_cells=4 |
| 스트림 박스 안뜸 | 추론 크래시(위) |
| 인디케이터 갱신X | AWS 연결(4단계) |
| Connection refused | AWS IP=PC IP |
| 초록/파란 화면 | RAW_BAYER=BG, 카메라 섹션 |
| dmabuf CANCELLED | 헤드리스, nvargus 재시작/reboot |

## 자주 쓰는 단독 테스트
- 카메라만 스트림: `python3 scripts/stream_mjpeg.py --no-boxes`
- 엔진+카메라 박스: `python3 models/test_engine_cam.py --save out --frames 30`
- 비전 단독: `VISION_MODE=csi python3 scripts/test_vision.py --mode csi --count 5`
- Mega 진단: `python3 scripts/diag_mega.py`
