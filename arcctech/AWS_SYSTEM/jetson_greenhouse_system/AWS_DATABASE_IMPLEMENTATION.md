# AWS 데이터베이스 구현 방식

## 현재 로컬/개발 DB

현재 `jetson_greenhouse_system`은 로컬 개발과 Jetson 단독 실행을 위해 SQLite를 사용한다.

- DB 파일: `data/greenhouse.db`
- 스키마 파일: `database/schema.sql`
- 초기화/마이그레이션: `server/init-db.js`
- 서버 진입점: `server/index.js`

서버가 시작될 때 `server/index.js`가 `server/init-db.js`를 import한다. 그래서 DB 파일이 없으면 새로 만들고, 기존 DB가 있으면 필요한 컬럼과 테이블을 자동으로 추가한다.

## 이번 구조에서 추가된 DB 역할

기존 DB는 센서값, AI 판독, 관리자 승인, 로봇 작업 상태를 저장했다. 이번 변경으로 아래 역할이 추가됐다.

| 구분 | 저장 위치 | 설명 |
|---|---|---|
| 로봇 작업 큐 | `robot_tasks` | Jetson/ESP/Arduino가 가져갈 작업 명령을 저장한다. |
| 로봇 응답 | `robot_feedback` | 로봇이 작업을 수행한 결과를 저장한다. |
| 비전 이벤트 | `vision_events` | Jetson CSI 웹캠/YOLO가 인식한 객체 정보를 저장한다. |
| 최근 응답 원본 | `robot_tasks.last_response_payload` | ESP/Arduino가 보낸 원본 JSON을 보관한다. |

## AWS에서는 어떻게 구현하는가

AWS에 올릴 때는 두 가지 방식이 가능하다.

## 1. 권장 방식: Amazon RDS PostgreSQL

이 온실 시스템은 `cells`, `sensor_logs`, `ai_readings`, `approvals`, `robot_tasks`처럼 서로 관계가 있는 테이블이 많다. 그래서 운영용 AWS DB는 DynamoDB보다 RDS PostgreSQL이 더 자연스럽다.

구성은 다음과 같다.

1. Node 백엔드는 ECS Fargate 또는 EC2에서 실행한다.
2. DB는 Amazon RDS PostgreSQL에 둔다.
3. `database/schema.sql`의 SQLite 문법을 PostgreSQL 문법으로 변환한다.
4. `better-sqlite3` 대신 `pg` 또는 Prisma 같은 PostgreSQL 클라이언트를 사용한다.
5. 서버는 환경변수 `DATABASE_URL`로 RDS에 접속한다.

운영 구조:

```text
Web UI / Jetson / ESP
        ↓ HTTP API
ECS Fargate or EC2 Node Server
        ↓ SQL
Amazon RDS PostgreSQL
```

이 방식의 장점은 승인, 작업, 피드백, 센서 로그를 SQL JOIN으로 안정적으로 조회할 수 있다는 점이다.

## 2. 빠른 시연 방식: EC2 + SQLite

짧은 시연이나 학교 프로젝트 데모라면 EC2 한 대에 현재 Node 서버를 그대로 올리고, `data/greenhouse.db`를 EBS 디스크에 저장해도 된다.

구성:

```text
Web UI / Jetson / ESP
        ↓ HTTP API
EC2 Node Server
        ↓ file I/O
EBS volume: data/greenhouse.db
```

이 방식은 가장 빨리 동작하지만, 서버를 여러 대로 늘리기 어렵고 DB 백업/복구를 직접 관리해야 한다.

## 3. DynamoDB를 쓰는 경우

앞서 새로 만든 `AWS_SYSTEM` 기본 API는 DynamoDB 저장소도 지원한다. 단, 이 기존 온실 시스템처럼 관계형 조회가 많은 구조에서는 모든 테이블을 그대로 DynamoDB로 옮기기보다 이벤트 저장용으로 쓰는 것이 좋다.

DynamoDB에 적합한 데이터:

- 로봇 작업 이벤트
- 로봇 응답 이벤트
- 비전 인식 이벤트
- 시스템 로그 이벤트

DynamoDB 키 예시:

| pk | sk | 데이터 |
|---|---|---|
| `TASK#robot-01` | `2026-06-17T...#taskId` | 로봇 작업 |
| `RESPONSE#robot-01` | `2026-06-17T...#responseId` | 로봇 응답 |
| `VISION#robot-01` | `2026-06-17T...#eventId` | 비전 결과 |

## 최종 추천

- 개발/Jetson 단독 테스트: 현재 SQLite 유지
- AWS 데모: EC2 + SQLite 가능
- AWS 운영/확장: RDS PostgreSQL 권장
- 이벤트 로그 대량 저장: DynamoDB 보조 사용 가능
