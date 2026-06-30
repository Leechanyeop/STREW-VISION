# Jetson Nano 실행 방법

이 프로젝트는 Node.js + Express + SQLite 기반의 Jetson Greenhouse 서버입니다.
Jetson Nano에서 웹 대시보드, 관리자 페이지, 상세 로그 페이지, API 서버를 한 번에 실행합니다.

## 1. 프로젝트 복사

PC에서 Jetson Nano로 폴더를 복사합니다.

```bash
scp -r jetson_greenhouse_system jetson@JETSON_IP:~/
```

Jetson Nano에서 프로젝트 폴더로 이동합니다.

```bash
cd ~/jetson_greenhouse_system
```

## 2. Node.js 및 빌드 도구 설치

```bash
sudo apt update
sudo apt install -y nodejs npm build-essential python3 make g++ python3-dev libsqlite3-dev
```

버전 확인:

```bash
node -v
npm -v
```

## 3. 의존성 설치

```bash
npm install
```

`better-sqlite3`는 Jetson Nano에서 네이티브 빌드가 필요할 수 있습니다. 설치가 실패하면 위의 빌드 도구가 모두 설치됐는지 확인한 뒤 다시 실행합니다.

```bash
npm install
```

## 4. 데이터베이스 초기화

```bash
npm run init-db
```

생성되는 DB 위치:

```text
data/greenhouse.db
```

DB 스키마 파일:

```text
database/schema.sql
```

## 5. 서버 실행

기본 포트는 `4100`입니다.

```bash
npm start
```

다른 포트로 실행하려면:

```bash
PORT=8000 npm start
```

## 6. 접속 주소

Jetson Nano 내부:

```text
http://localhost:4100
```

같은 네트워크의 다른 PC:

```text
http://JETSON_IP:4100
```

화면 구성:

```text
/          메인 대시보드: 중요한 상태만 표시
/details   상세 로그/상태 페이지: 센서, AI, 로봇, 이벤트 전체 확인
/admin     관리자 페이지: 승인 대기 작업과 알람 이벤트 검토
```

## 7. 주요 API

전체 메인 대시보드 데이터:

```bash
curl http://localhost:4100/api/dashboard
```

상세 로그/상태 데이터:

```bash
curl http://localhost:4100/api/details
```

AI 모드 상태 조회:

```bash
curl http://localhost:4100/api/ai-mode
```

AI 모드 활성화:

```bash
curl -X POST http://localhost:4100/api/ai-mode \
  -H 'Content-Type: application/json' \
  -d '{"enabled":true,"modeName":"AUTO_MONITOR"}'
```

AI 모드 비활성화:

```bash
curl -X POST http://localhost:4100/api/ai-mode \
  -H 'Content-Type: application/json' \
  -d '{"enabled":false,"modeName":"AUTO_MONITOR"}'
```

센서 데이터 입력:

```bash
curl -X POST http://localhost:4100/api/sensor \
  -H 'Content-Type: application/json' \
  -d '{"cell_id":1,"temperature":26.5,"humidity":70,"sap_amount_ml":320,"growth_rate":64}'
```

AI 판독 입력:

```bash
curl -X POST http://localhost:4100/api/ai \
  -H 'Content-Type: application/json' \
  -d '{"cell_id":1,"ai_mode":"OBSERVE","disease_area":"LEAF","disease_name":"leaf_spot","disease_probability":85}'
```

승인 대기 작업 승인:

```bash
curl -X POST http://localhost:4100/api/approval/1/approve
```

승인 대기 작업 거절:

```bash
curl -X POST http://localhost:4100/api/approval/1/reject
```

로봇 다음 작업 조회:

```bash
curl http://localhost:4100/api/robot/next-task
```

로봇 상태 업데이트:

```bash
curl -X POST http://localhost:4100/api/robot/status \
  -H 'Content-Type: application/json' \
  -d '{"task_id":1,"progress_rate":60,"temperature":26,"humidity":72,"sap_amount_ml":300,"robot_status":"RUNNING"}'
```

## 8. 백그라운드 실행

```bash
nohup npm start > greenhouse.log 2>&1 &
```

로그 확인:

```bash
tail -f greenhouse.log
```

프로세스 확인:

```bash
ps aux | grep 'server/index.js'
```

## 9. 자동 실행 설정

서비스 파일 생성:

```bash
sudo nano /etc/systemd/system/greenhouse-server.service
```

내용:

```ini
[Unit]
Description=Jetson Greenhouse Node Server
After=network.target

[Service]
WorkingDirectory=/home/jetson/jetson_greenhouse_system
ExecStart=/usr/bin/npm start
Restart=always
RestartSec=5
Environment=PORT=4100
User=jetson

[Install]
WantedBy=multi-user.target
```

서비스 등록 및 실행:

```bash
sudo systemctl daemon-reload
sudo systemctl enable greenhouse-server
sudo systemctl start greenhouse-server
```

상태 확인:

```bash
sudo systemctl status greenhouse-server
```

## 10. 구현된 기능 요약

- `/` 메인 페이지는 1920x1080 화면에서 중요한 값만 보이도록 구성했습니다.
- `/details` 페이지는 센서 로그, AI 판독, 로봇 작업, 피드백, 이벤트, 임계값을 테이블로 보여줍니다.
- `/admin` 페이지는 승인 대기 작업과 알람 이벤트 검토에 집중합니다.
- 메인 페이지에 AI 모드 ON/OFF 버튼이 있습니다.
- AI 모드 상태는 `system_settings` 테이블에 저장됩니다.
- 문제가 있는 셀이나 승인 대기 항목은 알림 영역에 표시됩니다.

## 11. 주의사항

- Jetson Nano와 접속 PC가 같은 네트워크에 있어야 합니다.
- 방화벽을 사용하는 경우 `4100` 포트를 열어야 합니다.
- 기존 Python `app.py` 서버와 같은 포트를 동시에 쓰지 마세요.
- 실제 로봇/AI 프로그램은 위 API로 센서값, AI 판독값, 로봇 진행률을 전송하면 됩니다.

## 12. Python GUI 클라이언트

서버는 그대로 Node.js로 실행하고, Python GUI는 API를 호출하는 별도 클라이언트로 실행할 수 있습니다.

Jetson Nano 데스크톱 환경에서 실행:

```bash
python3 greenhouse_gui.py
```

다른 PC에서 Jetson Nano 서버에 접속하는 GUI로 실행하려면 서버 주소를 지정합니다.

```bash
GREENHOUSE_SERVER_URL=http://JETSON_IP:4100 python3 greenhouse_gui.py
```

GUI 기능:

- 메인 상태 요약 확인
- AI Mode ON/OFF 전환
- 승인 대기 작업 승인/거절
- 센서, AI, 로봇 작업, 피드백, 이벤트 상세 로그 확인

주의:

- GUI 실행 전에 서버가 먼저 켜져 있어야 합니다.
- GUI는 DB를 직접 수정하지 않고 HTTP API만 사용합니다.
- Jetson Nano Lite 환경처럼 데스크톱이 없는 경우 GUI 대신 웹 화면을 사용하세요.
