# STREW_VISION 브링업 검증 체크리스트 (처음부터)

아래를 **순서대로** 하나씩 통과시켜라. 각 단계는 [명령] → [정상(PASS)] → [실패 시(FIX)] 구조다.
한 단계가 PASS되기 전엔 다음으로 넘어가지 말 것. 대부분의 "안 됨"은 앞 단계가 안 잡혀서다.

---

## 0. 최신 파일 반영 (PC → 젯슨 scp)
이번 세션에서 바뀐 파일들. PC(`C:\STREW_VISION\JETSON_ROBOT`)에서:
```powershell
scp ai/detector/raw_camera.py       blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/ai/detector/
scp ai/detector/frame_hub.py        blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/ai/detector/
scp ai/detector/camera.py           blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/ai/detector/
scp ai/detector/yolo_postprocess.py blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/ai/detector/
scp config/settings.py              blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/config/
scp robot/command.py                blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/robot/
scp robot/state_machine.py          blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/robot/
scp robot/vision_stream.py          blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/robot/
scp scripts/*.py                    blackhood@HAXASYS:/home/STREW-VISION/JETSON_ROBOT/scripts/
```
**Mega 펌웨어**는 Arduino IDE로 `mega_firmware/mega_firmware.ino` 열어 업로드(LCD 표시 추가됨).

### `.env` 필수 값 (젯슨)
```
CAMERA_BACKEND=raw
RAW_BAYER=BG
RAW_WB=1.0,0.476,0.87
RAW_SCALE=0.8
RAW_GAMMA=0.6
YOLO_CLASS_NAMES=healthy_leaf,old_leaf,powdery_mildew   ← ★ 3개! (2개면 추론 깨짐)
AWS_ENABLED=true
AWS_API_BASE=http://<PC_IP>:8000        ← 젯슨 자기(192.168.0.3) 아님! PC IP
MQTT_BROKER_HOST=<PC_IP>
```

---

## 1. 카메라 RAW 단독 (색/밝기)
```bash
cd /home/STREW-VISION/JETSON_ROBOT
python3 scripts/raw_camera.py --save out --frames 30
```
**PASS:** `[raw_camera] 첫 프레임 OK`, `out/`에 **정색(BG)** 이미지, FPS 출력.
**FIX:**
- `스트림 종료/부족` → 카메라 점유: `pkill -9 -f v4l2-ctl; pkill -9 -f python`; 안되면 `sudo reboot`
- 색 이상 → `RAW_BAYER`(BG 기본) / `RAW_WB` / `RAW_SCALE` 조정

---

## 2. 엔진 + 디코드 (★ nc=3 핵심)
```bash
python3 models/test_engine_cam.py --save out --frames 30   # 이 파일은 models/ 에 있음
```
**PASS 로그:** `[camera]`가 아니라 여기선 바인딩 로그 →
```
검출 출력 binding=2, width=40      ← width=40 이어야 정상 (3클래스 seg)
```
그리고 `out/`에 **박스**(healthy_leaf/old_leaf/powdery) + conf 0~1.
**FIX:**
- `width=6` 또는 `reshape ... (6,newaxis)` → `YOLO_CLASS_NAMES`가 2개다 → `.env` 3개로 → 재시작

---

## 3. Mega UART + LCD
`main.py` 실행 후(4단계) 확인. 
**PASS 로그:** `[READY] Mega 부팅 완료` → `[RUN] cycle_id=...` → STATE 이벤트.
**PASS LCD:** 부팅 시 `STREW ROBOT / READY` → 사이클 돌면 `Cell 1/4 / MOVE` → `VIEW:TOP` → `TASK:REPLACE` → `DONE` 로 바뀜.
**FIX:**
- LCD가 READY에서 안 바뀜 → 펌웨어(LCD 추가본) 업로드 확인
- LCD 아예 안 뜸 → I2C 주소(0x27) / SDA·SCL 배선 확인
- `[READY]` 안 뜸 → USB(ARDUINO_PORT=/dev/ttyACM0) / 보드레이트(115200) 확인

---

## 4. total_cells 일치 (무한순회 조건)
Mega는 `TOTAL_CELLS=4`. 젯슨 `total_cells`도 **4**여야 함.
- SQLite로 직접 4 설정 (젯슨엔 sqlite3 CLI가 없으니 Python으로):
```bash
python3 -c "import sqlite3;c=sqlite3.connect('data/robot_state.db');c.execute(\"UPDATE system_config SET value='4' WHERE key='total_cells'\");c.commit();print(dict(c.execute('SELECT key,value FROM system_config')))"
```
**주의:** total_cells는 부팅 시 AWS로 보고되고 Config Sync로 다시 받아온다(순환). 그래서
**SQLite를 4로 바꾼 뒤 main.py를 재시작**해야 4가 AWS에도 전파돼 유지된다. (실행 중 바꾸면 다음 사이클에 20으로 덮일 수 있음.)
**PASS:** 셀 4 COMPLETE 후 3초 뒤 다음 사이클 자동 시작(cycle_count=0=무한).
**FIX:** total_cells가 20 등 → Mega(4)와 안 맞으면 셀4에서 멈춤 → 4로 통일.

---

## 5. AWS 연결 (인디케이터/대시보드용)
**PC에서:** `uvicorn app.main:app --host 0.0.0.0 --port 8000` + Mosquitto LAN + 방화벽 8000/1883.
**젯슨 `.env`:** `AWS_API_BASE=http://<PC_IP>:8000`, `MQTT_BROKER_HOST=<PC_IP>`.
**PASS 로그:** `Report 'post_progress' successfully.` (Connection refused / timed out 없음).
**FIX:**
- `Connection refused` → PC 서버 안 켜졌거나 IP가 젯슨 자기 IP(192.168.0.3)로 되어있음 → PC IP로
- `MQTT timed out` → Mosquitto LAN 리스너/방화벽

---

## 6. 전체 main.py + 대시보드
```bash
python3 main.py
```
**PASS 로그 순서:**
```
[frame_hub] 카메라 백엔드=RAW
[raw_camera] 첫 프레임 OK
검출 output ... width=40 layout=v5        (또는 [camera] ... width=40 layout=v5)
[stream] MJPEG 라이브 스트림 시작: http://0.0.0.0:8090/
[READY] Mega 부팅 완료
[RUN] cycle_id=...
[VIEW] cell=1 view=TOP status=... conf=0.xx  ← 추론 성공!
[INSPECT] cell=1 종합판정: ...
[TASK] cell=1 ... 전송
[COMPLETE] ... → 다음 셀
```
**대시보드:**
- **Live Stream**: 스트림 주소 `http://<젯슨IP>:8090/stream` 입력 → 영상 + **검사 박스**
- **실시간 추론(오른쪽)**: 흰가루병/conf/Cell 갱신
- **현재 Cycle**: Cell 1→2→3→4 진행, 목표=무한, 셀4 후 재시작

**FIX 요약표:**
| 증상 | 원인 | 조치 |
|---|---|---|
| `reshape (6,newaxis)` | YOLO_CLASS_NAMES 2개 | .env 3개 |
| 셀1에서 멈춤 | 추론 크래시(위) 또는 total_cells≠4 | 2단계+4단계 |
| 사이클 1번 후 정지 | total_cells≠Mega | total_cells=4 |
| 스트림 박스 안뜸 | 추론 크래시 | 2단계 |
| 인디케이터 갱신X | AWS 연결 안됨 | 5단계 |
| Connection refused | AWS IP=젯슨 자기IP | PC IP |
| LCD 안바뀜 | 펌웨어 구본 | LCD본 업로드 |

---

## 핵심 원칙 (자주 까먹는 것)
1. **YOLO_CLASS_NAMES는 3개** (healthy_leaf, old_leaf, powdery_mildew) — 2개면 다 깨짐.
2. **Jetson total_cells == Mega TOTAL_CELLS** (지금 둘 다 4).
3. **AWS_API_BASE/MQTT는 PC IP** (젯슨 자기 IP 아님).
4. **카메라는 1프로세스만** — main.py 돌 땐 stream_mjpeg.py 따로 돌리지 말 것(8090·카메라 충돌).
5. **BG Bayer** — 이 IMX708 센서는 BGGR.
