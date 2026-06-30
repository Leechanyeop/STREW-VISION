# Jetson Nano AI 영농 DB + 웹서버

이 프로젝트는 엑셀의 데이터 형식(ID, 날짜/시간, 온도, 습도, 작업유무, 작업률, EXECUTE_TASK, 발병율, 공급 수액량, AI MODE, 보식 날짜, 평균 성장률, 로봇 작업 상태)을 기준으로 Jetson Nano에서 바로 실행할 수 있는 SQLite DB와 FastAPI 웹 서버입니다.

## 실행

```bash
cd jetson_greenhouse_system
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app:app --host 0.0.0.0 --port 8000
```

브라우저에서 `http://JetsonNano_IP:8000` 접속.

## 주요 웹페이지

| 페이지 | URL | 역할 |
|---|---|---|
| 대시보드 | `/` | 셀별 센서, AI 판독, 로봇 상태 표시 |
| 승인 검토창 | `/approvals` | 위험 판독 승인/반려 |
| 로봇 작업 API | `/api/robot/next-task` | 로봇이 수행할 다음 작업 조회 |

## API 테스트 예시

### 1. 센서 입력

```bash
curl -X POST http://localhost:8000/api/sensor \
  -H 'Content-Type: application/json' \
  -d '{"cell_id":4,"temperature":26.5,"humidity":88,"sap_amount_ml":420,"growth_rate":62}'
```

### 2. AI 판독 입력

```bash
curl -X POST http://localhost:8000/api/ai \
  -H 'Content-Type: application/json' \
  -d '{"cell_id":4,"ai_mode":"감시","disease_area":"잎","disease_name":"흰곰팡이병","disease_probability":85}'
```

발병확률이 80% 이상이면 `approvals`에 PENDING 검토건이 생성되고, `robot_tasks`는 `WAIT_APPROVAL` 상태가 됩니다.

### 3. 관리자 승인

```bash
curl -X POST 'http://localhost:8000/api/approval/1/approve?approved_by=admin'
```

승인 후 `robot_tasks.state_machine`이 `EXECUTE_TASK`로 전환됩니다.

### 4. 로봇 피드백

```bash
curl -X POST http://localhost:8000/api/robot/status \
  -H 'Content-Type: application/json' \
  -d '{"task_id":1,"progress_rate":60,"temperature":26,"humidity":82,"sap_amount_ml":390,"robot_status":"보식 진행중"}'
```

작업률이 100이면 `COMPLETE`로 바뀌고 `growth_records`에 보식 날짜와 평균 성장률이 기록됩니다.

## 상태 머신

| 상태 | 의미 |
|---|---|
| AI_DETECT | AI가 발병 여부와 확률 판독 |
| WAIT_APPROVAL | 임계값 초과로 관리자 승인 대기 |
| EXECUTE_TASK | 승인 후 로봇 작업 실행 |
| REPORT_STATUS | 로봇이 작업률과 상태 보고 |
| COMPLETE | 작업 완료 및 DB 업데이트 |

## DB 설계 핵심

- `sensor_logs`: 온도, 습도, 수액량, 성장률 기록
- `ai_readings`: AI MODE, 병명, 발병확률, 위험도 기록
- `approvals`: 웹 검토창 승인/반려 이력
- `robot_tasks`: 로봇 명령과 상태머신
- `robot_feedback`: 로봇 작업률과 실시간 피드백
- `growth_records`: 작업 완료 후 보식 날짜와 평균 성장률

상세 플로우차트와 ERD는 `diagrams.md`에 있습니다.
