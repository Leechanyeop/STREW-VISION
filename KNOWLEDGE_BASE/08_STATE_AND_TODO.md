# 08. 현재 상태 · 남은 작업 · 알려진 이슈

## ✅ 완료 (작동 확인됨)
- **카메라 RAW ISP**: v4l2 RG10 → BGR, BGGR(BG) 패턴, 색 정상. nvargus 대체(뿌옇게 이슈 해결).
- **TensorRT 추론**: best.engine(YOLOv5-seg 3클래스) 로드·추론 ~14FPS. decode 자동판별(v5/v8/seg).
- **CUDA 스레드 버그 해결**: make_context+push/pop (리스너 스레드 추론 OK).
- **MJPEG 라이브 스트림**: main.py 내장(:8090), 검사 박스 얹음. 대시보드 live.html 임베드.
- **Mega UART 통신**: READY/RUN/STATE/ACK/TASK/COMPLETE 흐름 정상. LCD 표시 코드 추가.
- **AWS 연결**: post_progress/config/status 보고 성공(PC IP 맞춘 뒤).
- **데이터 도구**: 영상→프레임, 젯슨 촬영+전송, 2셋 병합(폴리곤→박스).
- **3클래스 코드**: settings/command/camera 매핑(healthy_leaf→OBSERVE, old_leaf/powdery→REPLACE).
- **종료 정리**: frame_hub close(카메라 해제), main.py SIGTERM.

## 🔴 막판 블로커 (이것만 하면 전체 작동)
1. **젯슨 `.env` YOLO_CLASS_NAMES=3개** (healthy_leaf,old_leaf,powdery_mildew).
   - 현재 2개로 남아 → 추론 `reshape (6,newaxis)` 크래시 → 셀1 멈춤 + 스트림 박스 없음.
   - 로그 `width=40 layout=v5` 뜨면 해결(현재 `width=6 layout=v8`).
2. **total_cells=4** (Mega와 일치). 현재 20 → 무한순회 안 됨.
3. 위 2개 적용 후 main.py 재시작 → 박스·LCD·셀진행·인디케이터 연쇄로 살아남.
4. **Mega 펌웨어(LCD본) 업로드** (Arduino IDE) — LCD 값 표시.

## ⚠️ 알려진 이슈 / 개선 필요
- **흰가루병 검출 약함**: 학습 데이터가 실제 온실 도메인과 안 맞음 → 젯슨 카메라로 수집·재학습 필요(`05_DATASET_TRAINING.md`).
- **RAW 색을 학습 프레임과 매칭 필요**: 지금 색은 사람 눈 기준. conf 유지하려면 학습 프레임과 비슷하게 WB/gamma 재조정.
- **물리 동작 미구현**: Mega `moveToCell/moveToView/executePhysicalTask` 전부 TODO 스텁(모터 배선 전).
- **세그멘테이션 미사용**: seg 모델이지만 detection head만 씀. 병반 면적% 필요하면 마스크 재구성 추가 가능(FPS↓).
- **total_cells 순환**: SQLite↔AWS 보고 순환. 값 바꾸면 재시작 필요.
- **API_KEY**: 현재 로컬 테스트라 change-me/OS env 이슈. 실사용 시 랜덤키를 젯슨·AWS·GitHub Secret 동일하게.

## 🔒 보안 규칙 (지킬 것)
- `.env`·API키·AWS 자격증명·실데이터 DB·하드웨어 로그 = **커밋 금지**(.env는 gitignore).
- 실사용 API_KEY는 `openssl rand -hex 24`, 젯슨/AWS 동일. "change-me" 금지.
- 예시는 `.env.example`.

## 📁 저장소 규칙 (CLAUDE.md 요약)
- Jetson 코드 = `C:\STREW_VISION\JETSON_ROBOT`(STREW-VISION.git), AWS = `C:\AWS_SYSTEM\STREW-VISION_AWS`(별도 repo).
- 동시 편집 주의 파일: `app/main.py`, `repository.py`, `schemas.py`, `state_machine.py`, `mega_firmware.ino` 등.
- API 계약(`/robot/* /vision/* /stream/* /sensor/* /ai/*`) 변경·스키마 재작성·데이터 삭제 전 확인.
- 한국어 도메인 용어 유지.

## 다음 세션 새 AI에게: 바로 할 일
1. `07_RUNBOOK.md` 0~5단계로 `.env`(3클래스) + total_cells=4 적용, main.py 재시작, `width=40 layout=v5` 확인.
2. 되면 대시보드에서 스트림 박스 + 인디케이터 확인.
3. 그다음 큰 목표 = **흰가루 도메인 재학습**(`05_DATASET_TRAINING.md`) + Mega 물리동작 구현.
