# 백엔드 변경점 정리

## 변경 목적

기존 `jetson_greenhouse_system`의 UI는 그대로 두고, DB와 판단/명령 백엔드만 새 구조에 맞게 바꿨다. 핵심은 웹 UI, Jetson Nano, ESP/Arduino 제어 코드가 같은 작업 큐를 바라보도록 만든 것이다.

## 수정한 파일

| 파일 | 변경 내용 |
|---|---|
| `server/index.js` | 판단 로직, 로봇 작업 큐 API, 로봇 응답 API, 비전 이벤트 API 추가 |
| `server/init-db.js` | 기존 SQLite DB에 새 컬럼/테이블을 자동 추가하는 마이그레이션 추가 |
| `database/schema.sql` | 새 DB 구조 반영 |
| `AWS_DATABASE_IMPLEMENTATION.md` | AWS에서 DB를 어떻게 구성하는지 설명 추가 |
| `BACKEND_CHANGELOG.md` | 이번 변경점 문서화 |

UI 파일인 `index.html`, `admin.html`, `details.html`은 수정하지 않았다.

## 새로 추가된 DB 구조

### `robot_tasks` 추가 컬럼

| 컬럼 | 의미 |
|---|---|
| `robot_id` | 작업을 가져갈 로봇 ID. 기본값은 `robot-01` |
| `execute_task` | ESP/Arduino가 이해할 실제 실행 명령 |
| `move_sign` | `LEFT`, `RIGHT`, `FORWARD`, `BACKWARD`, `STOP` 같은 이동 지시 |
| `target_label` | Jetson CSI 웹캠/YOLO가 찾을 목표 라벨 |
| `queue_status` | `queued`, `sent`, `running`, `done`, `failed`, `cancelled` 상태 |
| `sent_at` | 로봇이 작업을 가져간 시간 |
| `last_response_payload` | 로봇이 마지막으로 보낸 응답 JSON |

### `robot_feedback` 추가 컬럼

| 컬럼 | 의미 |
|---|---|
| `completion_sign` | `DONE`, `FAILED`, `RUNNING` |
| `response_payload` | ESP/Arduino 응답 원본 JSON |

### 새 테이블 `vision_events`

Jetson CSI 웹캠 또는 YOLO가 감지한 결과를 저장한다.

주요 컬럼:

- `robot_id`
- `cell_id`
- `source`
- `label`
- `confidence`
- `x_center`, `y_center`, `width`, `height`
- `payload`
- `created_at`

## 판단 로직 변경

### 기존

AI 판독 확률이 80 이상이면 관리자 승인 대기를 만들고, 승인되면 `robot_tasks.state_machine`을 `EXECUTE_TASK`로 바꿨다.

### 변경 후

AI 판독 결과에 따라 작업 큐까지 같이 준비한다.

- `disease_probability >= 80`: 관리자 승인 필요, `WAIT_APPROVAL` 작업 생성
- 관리자 승인 후: 작업이 `EXECUTE_TASK`, `queue_status=queued`가 되어 Jetson/ESP가 가져갈 수 있음
- `50 <= disease_probability < 80`이고 AI Mode ON: 관찰 작업 `OBSERVE` 자동 생성 가능
- 작업을 로봇이 가져가면 `queue_status=sent`
- 로봇 응답이 오면 `done`, `failed`, `running`으로 상태 변경

## ESP/Arduino 연동 API

### 1. 작업 생성

```http
POST /api/robot/request
```

예시:

```json
{
  "robot_id": "robot-01",
  "cell_id": 1,
  "task_name": "OBSERVE",
  "move_sign": "FORWARD",
  "target_label": "plant"
}
```

### 2. Jetson/ESP가 다음 작업 가져오기

```http
GET /api/robot/next?robot_id=robot-01
```

기존 UI 호환 API도 유지된다.

```http
GET /api/robot/next-task
```

응답 예시:

```json
{
  "id": 12,
  "task_id": 12,
  "robot_id": "robot-01",
  "cell_id": 1,
  "execute_task": "OBSERVE_BY_VISION",
  "task_name": "OBSERVE",
  "move_sign": "FORWARD",
  "target_label": "plant",
  "status": "sent"
}
```

### 3. 로봇 작업 결과 보고

```http
POST /api/robot/response
```

예시:

```json
{
  "task_id": 12,
  "robot_id": "robot-01",
  "execute_task": "OBSERVE_BY_VISION",
  "completion_sign": "DONE",
  "message": "task accepted",
  "payload": {
    "detected_label": "plant",
    "x_center": 640,
    "y_center": 360
  }
}
```

### 4. CSI 웹캠/YOLO 비전 결과 저장

```http
POST /api/vision/event
```

예시:

```json
{
  "robot_id": "robot-01",
  "cell_id": 1,
  "source": "jetson-csi-camera",
  "label": "plant",
  "confidence": 0.91,
  "x_center": 640,
  "y_center": 360,
  "width": 160,
  "height": 120
}
```

## 전체 흐름

```text
AI 판독 또는 수동 작업 생성
        ↓
robot_tasks에 작업 저장
        ↓
Jetson/ESP가 /api/robot/next 호출
        ↓
서버가 작업 상태를 sent로 변경
        ↓
Jetson이 CSI 웹캠으로 판단 후 ESP/Arduino에 명령 전송
        ↓
ESP/Arduino가 실행 결과 반환
        ↓
Jetson/ESP가 /api/robot/response로 결과 보고
        ↓
DB의 robot_tasks, robot_feedback, system_events 업데이트
```

## 검증 결과

- `server/index.js` 문법 검사 통과
- `server/init-db.js` 문법 검사 통과
- `npm run init-db` 실행 성공
- 기존 `data/greenhouse.db`에 새 컬럼과 `vision_events` 테이블 적용 확인
