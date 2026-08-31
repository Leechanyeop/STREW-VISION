# 06. 디버깅 함정 총정리 (★ 가장 자주 볼 파일)

이 프로젝트에서 실제로 하루씩 잡아먹은 함정들. **증상 → 진짜 원인 → 해결**. 새 AI는 증상이 보이면
추측 말고 여기서 찾아라.

## 카메라
| 증상 | 진짜 원인 | 해결 |
|---|---|---|
| 초록/보라 쓰레기 화면 | 젯슨 OpenCV는 GStreamer 없음 + CSI는 RG10(10bit Bayer) → `cv2.VideoCapture(0)`이 디베이어 못함 | nvargus(GStreamer appsink) 또는 v4l2-RAW+Python ISP. **CSI 센서에 cv2.VideoCapture(0) 절대 금지** |
| 뿌옇게/소프트 | nvargus ISP 제네릭 튜닝, 오토포커스(IMX708 VCM) 미제어, 저조도 고게인 | RAW 파이프라인(black/WB/demosaic/gamma), 초점 확인, **학습 도메인에 맞춰 튜닝(예쁘게 X)** |
| 강한 파란기 / 초록기 (색 편향) | Bayer 패턴 틀림 or WB 게인. 피부가 파랗다 = R↔B 스왑 = 패턴 오류 | 중립 WB로 RG/GB/GR/BG 다 시도. **이 IMX708은 BG(BGGR)** |
| 너무 어두움 | RAW scale 너무 낮음 + gamma 없음(linear는 어둡게 보임) | `RAW_SCALE`↑(흰색=255/흰RAW값≈0.8), `RAW_GAMMA=0.6`. 밝기는 exposure↑가 노이즈 면에서 1순위 |
| `스트림 종료/부족`, 카메라 busy, open 실패 | 이전 프로세스가 `/dev/video0` 아직 잡음(특히 kill -9) | `fuser /dev/video0`로 찾아 `pkill -9`. **카메라는 1프로세스만.** 안되면 reboot |
| `NvArgusCameraSrc: CANCELLED (7)` / `nvbuf_utils: Can not get HW buffer`(dmabuf) | 나노 4GB에서 nvargus + X데스크톱 + TensorRT가 NVMM/GPU 버퍼 경합 | **헤드리스로**(imshow 금지, 저장/스트림). 꼬이면 `sudo systemctl restart nvargus-daemon` → reboot. RAW 경로는 nvargus 안 써서 회피 |

## 추론 / 엔진
| 증상 | 진짜 원인 | 해결 |
|---|---|---|
| conf가 수백, 가짜 박스 폭발, 추론 수십초 | **클래스 수(nc) 불일치** 또는 모델종류 decode 불일치 → 출력 텐서 뒤엉킴 | `YOLO_CLASS_NAMES` 학습과 정확히 일치(현재 3개). decode를 출력 레이아웃에 맞춤 |
| `cannot reshape array of size N into shape (M,newaxis)` | seg 모델은 출력 2개(검출+마스크) → 마스크 출력을 잘못 집음. 또는 nc 틀려서 폭이 안 나눠짐 | 검출 바인딩을 shape로 자동판별(`shape[-1]==5+nc or 5+nc+32`), 실제 폭으로 reshape |
| 로그 `width=6 layout=v8` (나와야 할 건 `width=40 layout=v5`) | `YOLO_CLASS_NAMES`가 2개(nc=2) → 40폭 seg 못 알아봄 | `.env` 3클래스로. 이게 이번 프로젝트 막판 최대 블로커 |
| 박스 이상/검출 0인데 에러는 없음 | v5/v8/seg decode 불일치(objectness 유무, 전치, 마스크열) | 레이아웃 판별 후 맞는 decode(`02_JETSON_VISION.md` 표) |
| `Cuda Runtime (invalid resource handle)` | 추론이 컨텍스트 만든 스레드와 **다른 스레드**에서 호출됨(autoinit=메인, 추론=리스너 스레드) | `make_context()` + 버퍼 후 `pop()`, 추론 시 워커 스레드에서 `push()/pop()` |
| `[TRT][W] engine plan across different models of devices` | 엔진이 다른 장치에서 빌드됨 | 이 젯슨에서 `trtexec` 재빌드 |

## 상태머신 / 사이클
| 증상 | 진짜 원인 | 해결 |
|---|---|---|
| 셀 1에서 멈춤(VISION_READY 정지) | 추론 크래시(위 nc/reshape) → 4-View 누적 실패 → **TASK 못 보냄** → Mega가 TASK 기다리며 멈춤 | 추론 크래시부터 고쳐라(nc). ACK는 나가도 TASK가 안 나가면 마지막 View에서 데드락 |
| 사이클 1번 돌고 안 돎(무한인데) | **Jetson total_cells ≠ Mega TOTAL_CELLS**. Mega는 셀4 후 IDLE, Jetson은 total(20)을 기다려 재시작 안함 | 양쪽 일치(둘 다 4). SQLite: `python3 -c "..."`(sqlite3 CLI 없음). 재시작(부팅 시 AWS로 전파) |
| 셀 1→2,3,4 순식간 통과 | 펌웨어 이동함수 TODO 스텁 → 물리 지연 없음(ACTION_TOTAL_MS만). 정상. | 실제 검사면 각 셀 4-View는 함. 모터 배선되면 자연 dwell |
| 관리자 승인(WAIT)에서 멈춤, post_status만 반복 | powdery 판정 → `_await_admin_decision`이 리스너 스레드 블로킹, 관리자 응답 대기 | 대시보드 admin에서 승인/거부. 오검 잦으면 confidence_threshold↑ |
| Mega Offline 오판 | 리스너가 판단대기로 PONG 못읽음 | `awaiting_decision` 중 오프라인 판정 유예(구현됨). PONG 프레이밍(라인버퍼) |

## 설정 / 네트워크 / 배포
| 증상 | 진짜 원인 | 해결 |
|---|---|---|
| `.env` 바꿨는데 무시됨 / 클래스 2개 / 401 | **OS 환경변수가 .env를 덮음**(pydantic/os.getenv 우선순위) | `echo $VAR` 확인, unset 또는 명시적 세팅 |
| `Connection refused` 서버로 | 상대(서버) IP가 아니라 **자기 IP**를 가리킴(192.168.0.3=젯슨 자신) | 서버=PC IP로. 서버 `--host 0.0.0.0`, 방화벽 |
| MQTT `timed out` | 브로커 host 틀림/미기동, LAN 리스너·방화벽 | `mosquitto_sub -t '#'`로 확인, MQTT_BROKER_HOST=PC IP |
| 대시보드 값 안뜸 | `MQTT_ENABLED=false`거나 서버가 다른 브로커/토픽 | AWS `.env` MQTT_ENABLED=true, 토픽 esp32/sensor |
| total_cells가 자꾸 20으로 | 부팅 시 SQLite→AWS 보고→get_robot_config로 다시 받음(순환) | SQLite=4로 바꾸고 **재시작**(그래야 AWS에도 4 전파). 안되면 AWS config 직접 4 |
| git pull하면 젯슨 작업 날아갈까 걱정 | best.engine/.env는 untracked/gitignore라 pull이 안 건드림. 수정한 추적파일 있으면 pull이 거부(에러)함 | `git status` 먼저. 걱정되면 바뀐 파일만 scp |
| aiortc/av 설치 안됨(WebRTC) | 나노 Python3.6/aarch64 CPython 휠 없음, PyAV/ffmpeg 빌드 지옥 | **WebRTC 포기 → MJPEG**(표준 http.server, 의존성 0, 브라우저·대시보드 임베드) |

## 잘 잊는 상식 8가지
1. 나노 OpenCV로 CSI 센서 못 연다 → nvargus 또는 v4l2-RAW.
2. 카메라 = 1프로세스. 한 프로세스 안에서 공유(SharedFrameCamera).
3. decode는 모델종류·nc와 정확히 일치.
4. CUDA 컨텍스트는 스레드에 묶임 → 워커 추론이면 make_context+push/pop.
5. 배포 이미지를 학습 도메인에 맞춰라(사람 눈 X).
6. 헤드리스가 안정 모드. imshow는 dmabuf/X 경합.
7. 설정값은 모든 컴포넌트에서 일치(Jetson total_cells == Mega TOTAL_CELLS).
8. 네트워크 클라이언트는 상대 IP를, 서버는 0.0.0.0을.
