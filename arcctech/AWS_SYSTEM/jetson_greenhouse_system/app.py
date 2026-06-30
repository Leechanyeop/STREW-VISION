import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field


BASE_DIR = Path(__file__).resolve().parent # 현재 파일이 위치한 디렉토리
DB_PATH = BASE_DIR / "greenhouse.db" # 데이터베이스 파일 경로
SCHEMA_PATH = BASE_DIR / "schema.sql" # 데이터베이스 스키마 SQL 파일 경로
 
app = FastAPI(title="Jetson Nano Greenhouse Control Server") # FastAPI 애플리케이션 인스턴스 생성

app.mount( # /static 경로에 정적 파일 제공 설정
    "/static",
    StaticFiles(directory=BASE_DIR / "static"),
    name="static"
)

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))# Jinja2 템플릿 설정, templates 디렉토리에서 템플릿 파일을 찾도록 지정


def db() -> sqlite3.Connection:# 데이터베이스 연결 함수
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    with db() as conn:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))


@app.on_event("startup")
def startup() -> None:
    init_db()


def get_thresholds(conn: sqlite3.Connection) -> Dict[str, sqlite3.Row]:
    rows = conn.execute(
        "SELECT * FROM thresholds WHERE enabled = 1"
    ).fetchall()

    result = {}
    for row in rows:
        result[row["metric"]] = row

    return result


def env_warning( # 환경 경고 판단 함수
    thresholds: Dict[str, sqlite3.Row],# 임계값 정보가 담긴 딕셔너리 sqlite3.Row 객체를 값으로 가지는 딕셔너리
    temperature: float,
    humidity: int,
    sap_amount_ml: float
) -> str:
    warnings = []  # type: List[str]

    checks = {
        "temperature": temperature,
        "humidity": humidity,
        "sap_amount_ml": sap_amount_ml,
    }

    for metric, value in checks.items():
        t = thresholds.get(metric)

        if not t:
            continue

        min_value = t["min_value"]
        max_value = t["max_value"]

        if min_value is not None and value < min_value:
            warnings.append(metric)

        if max_value is not None and value > max_value:
            warnings.append(metric)

    if not warnings:
        return "NORMAL"

    return "WARNING:" + ",".join(warnings)


def risk_from_probability(probability: int) -> Tuple[str, str]:
    if probability >= 80:
        return "위험", "보식"

    if probability >= 50:
        return "주의", "감시"

    return "정상", "유지"


class SensorInput(BaseModel):
    cell_id: int = Field(ge=1, le=4)
    temperature: float
    humidity: int = Field(ge=0, le=100)
    sap_amount_ml: float = Field(ge=0)
    growth_rate: Optional[int] = Field(default=None, ge=0, le=100)


class AiInput(BaseModel):
    cell_id: int = Field(ge=1, le=4)
    sensor_log_id: Optional[int] = None
    ai_mode: str = Field(regex="^(감시|보식|정상)$")
    disease_area: Optional[str] = Field(default=None, regex="^(잎|뿌리|꽃|열매)$")
    disease_name: str = "정상"
    disease_probability: int = Field(ge=0, le=100)


class RobotFeedbackInput(BaseModel):
    task_id: int
    progress_rate: int = Field(ge=0, le=100)
    temperature: Optional[float] = None
    humidity: Optional[int] = Field(default=None, ge=0, le=100)
    sap_amount_ml: Optional[float] = None
    robot_status: str


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request):
    with db() as conn:
        latest = conn.execute("""
            SELECT
                c.id AS cell_id,
                c.cell_name,

                s.measured_at,
                s.temperature,
                s.humidity,
                s.sap_amount_ml,
                s.growth_rate,
                s.env_warning,

                a.ai_mode,
                a.disease_name,
                a.disease_probability,
                a.risk_level,
                a.recommended_task,

                rt.state_machine,
                rt.progress_rate,
                rt.robot_status

            FROM cells c

            LEFT JOIN sensor_logs s
                ON s.id = (
                    SELECT id
                    FROM sensor_logs
                    WHERE cell_id = c.id
                    ORDER BY measured_at DESC
                    LIMIT 1
                )

            LEFT JOIN ai_readings a
                ON a.id = (
                    SELECT id
                    FROM ai_readings
                    WHERE cell_id = c.id
                    ORDER BY detected_at DESC
                    LIMIT 1
                )

            LEFT JOIN robot_tasks rt
                ON rt.id = (
                    SELECT id
                    FROM robot_tasks
                    WHERE cell_id = c.id
                    ORDER BY created_at DESC
                    LIMIT 1
                )

            ORDER BY c.id
        """).fetchall()

        pending = conn.execute("""
            SELECT *
            FROM approvals
            WHERE approval_status = 'PENDING'
            ORDER BY requested_at DESC
        """).fetchall()

        events = conn.execute("""
            SELECT *
            FROM system_events
            ORDER BY event_time DESC
            LIMIT 10
        """).fetchall()

    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "latest": latest,
            "pending": pending,
            "events": events
        }
    )


@app.get("/approvals", response_class=HTMLResponse)
def approvals_page(request: Request):
    with db() as conn:
        rows = conn.execute("""
            SELECT
                ap.*,
                ar.disease_name,
                ar.disease_probability,
                ar.ai_mode
            FROM approvals ap
            JOIN ai_readings ar
                ON ar.id = ap.ai_reading_id
            ORDER BY ap.requested_at DESC
        """).fetchall()

    return templates.TemplateResponse(
        "approvals.html",
        {
            "request": request,
            "approvals": rows
        }
    )


@app.post("/api/sensor")
def ingest_sensor(payload: SensorInput):
    with db() as conn:
        thresholds = get_thresholds(conn)

        warning = env_warning(
            thresholds,
            payload.temperature,
            payload.humidity,
            payload.sap_amount_ml
        )

        cur = conn.execute("""
            INSERT INTO sensor_logs(
                cell_id,
                temperature,
                humidity,
                sap_amount_ml,
                growth_rate,
                env_warning
            )
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            payload.cell_id,
            payload.temperature,
            payload.humidity,
            payload.sap_amount_ml,
            payload.growth_rate,
            warning
        ))

        conn.execute("""
            INSERT INTO system_events(event_type, cell_id, message)
            VALUES (?, ?, ?)
        """, (
            "SENSOR",
            payload.cell_id,
            "센서 입력 저장: " + warning
        ))

        return {
            "sensor_log_id": cur.lastrowid,
            "env_warning": warning
        }


@app.post("/api/ai")
def ingest_ai(payload: AiInput):
    risk_level, recommended_task = risk_from_probability(
        payload.disease_probability
    )

    disease_area = payload.disease_area or "잎"

    with db() as conn:
        cur = conn.execute("""
            INSERT INTO ai_readings(
                cell_id,
                sensor_log_id,
                ai_mode,
                disease_area,
                disease_name,
                disease_probability,
                risk_level,
                recommended_task,
                ai_message
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.cell_id,
            payload.sensor_log_id,
            payload.ai_mode,
            disease_area,
            payload.disease_name,
            payload.disease_probability,
            risk_level,
            recommended_task,
            "%s번 셀 %s %s%%" % (
                payload.cell_id,
                payload.disease_name,
                payload.disease_probability
            )
        ))

        ai_reading_id = cur.lastrowid
        approval_id = None

        if payload.disease_probability >= 80:
            msg = "%s번 셀 %s %s%% - 관리자 승인 필요" % (
                payload.cell_id,
                payload.disease_name,
                payload.disease_probability
            )

            ap = conn.execute("""
                INSERT INTO approvals(
                    ai_reading_id,
                    cell_id,
                    review_message
                )
                VALUES (?, ?, ?)
            """, (
                ai_reading_id,
                payload.cell_id,
                msg
            ))

            approval_id = ap.lastrowid

            command_payload = {
                "cell_id": payload.cell_id,
                "task": "보식"
            }

            conn.execute("""
                INSERT INTO robot_tasks(
                    cell_id,
                    approval_id,
                    task_name,
                    state_machine,
                    robot_status,
                    command_payload
                )
                VALUES (?, ?, '보식', 'WAIT_APPROVAL', '승인 대기', ?)
            """, (
                payload.cell_id,
                approval_id,
                json.dumps(command_payload, ensure_ascii=False)
            ))

            conn.execute("""
                INSERT INTO system_events(event_type, cell_id, message)
                VALUES (?, ?, ?)
            """, (
                "AI_DANGER",
                payload.cell_id,
                msg
            ))

        else:
            conn.execute("""
                INSERT INTO system_events(event_type, cell_id, message)
                VALUES (?, ?, ?)
            """, (
                "AI_NORMAL",
                payload.cell_id,
                "AI 판독: %s, 권장작업=%s" % (
                    risk_level,
                    recommended_task
                )
            ))

        return {
            "ai_reading_id": ai_reading_id,
            "risk_level": risk_level,
            "recommended_task": recommended_task,
            "approval_id": approval_id
        }


@app.post("/approval/{approval_id}/approve")
def approve_from_form(
    approval_id: int,
    approved_by: str = Form("admin")
):
    approve_approval(approval_id, approved_by)

    return RedirectResponse(
        url="/approvals",
        status_code=303
    )


@app.post("/approval/{approval_id}/reject")
def reject_from_form(
    approval_id: int,
    approved_by: str = Form("admin")
):
    with db() as conn:
        conn.execute("""
            UPDATE approvals
            SET
                approval_status = 'REJECTED',
                approved_by = ?,
                approved_at = datetime('now')
            WHERE id = ?
        """, (
            approved_by,
            approval_id
        ))

        conn.execute("""
            UPDATE robot_tasks
            SET
                state_machine = 'COMPLETE',
                control_state = 'STOP',
                robot_status = '관리자 반려'
            WHERE approval_id = ?
        """, (
            approval_id,
        ))

    return RedirectResponse(
        url="/approvals",
        status_code=303
    )


def approve_approval(
    approval_id: int,
    approved_by: str = "admin"
) -> dict:
    with db() as conn:
        approval = conn.execute("""
            SELECT *
            FROM approvals
            WHERE id = ?
        """, (
            approval_id,
        )).fetchone()

        if not approval:
            raise HTTPException(
                status_code=404,
                detail="approval not found"
            )

        conn.execute("""
            UPDATE approvals
            SET
                approval_status = 'APPROVED',
                approved_by = ?,
                approved_at = datetime('now')
            WHERE id = ?
        """, (
            approved_by,
            approval_id
        ))

        conn.execute("""
            UPDATE robot_tasks
            SET
                state_machine = 'EXECUTE_TASK',
                control_state = 'RUN',
                robot_status = '보식 명령 전송',
                started_at = datetime('now')
            WHERE approval_id = ?
        """, (
            approval_id,
        ))

        conn.execute("""
            INSERT INTO system_events(event_type, cell_id, message)
            VALUES (?, ?, ?)
        """, (
            "APPROVED",
            approval["cell_id"],
            "승인 완료: approval_id=%s" % approval_id
        ))

        return {
            "approval_id": approval_id,
            "state_machine": "EXECUTE_TASK"
        }


@app.post("/api/approval/{approval_id}/approve")
def approve_api(
    approval_id: int,
    approved_by: str = "admin"
):
    return approve_approval(approval_id, approved_by)


@app.post("/api/robot/status")
def robot_status(payload: RobotFeedbackInput):
    with db() as conn:
        task = conn.execute("""
            SELECT *
            FROM robot_tasks
            WHERE id = ?
        """, (
            payload.task_id,
        )).fetchone()

        if not task:
            raise HTTPException(
                status_code=404,
                detail="task not found"
            )

        conn.execute("""
            INSERT INTO robot_feedback(
                task_id,
                cell_id,
                progress_rate,
                temperature,
                humidity,
                sap_amount_ml,
                robot_status
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            payload.task_id,
            task["cell_id"],
            payload.progress_rate,
            payload.temperature,
            payload.humidity,
            payload.sap_amount_ml,
            payload.robot_status
        ))

        if payload.progress_rate >= 100:
            next_state = "COMPLETE"
        else:
            next_state = "REPORT_STATUS"

        if next_state == "COMPLETE":
            conn.execute("""
                UPDATE robot_tasks
                SET
                    progress_rate = ?,
                    robot_status = ?,
                    state_machine = ?,
                    completed_at = datetime('now')
                WHERE id = ?
            """, (
                payload.progress_rate,
                payload.robot_status,
                next_state,
                payload.task_id
            ))

            conn.execute("""
                INSERT INTO growth_records(
                    cell_id,
                    replant_date,
                    avg_growth_rate,
                    note
                )
                VALUES (
                    ?,
                    date('now'),
                    (
                        SELECT AVG(growth_rate)
                        FROM sensor_logs
                        WHERE cell_id = ?
                          AND growth_rate IS NOT NULL
                    ),
                    '로봇 작업 완료 후 자동 기록'
                )
            """, (
                task["cell_id"],
                task["cell_id"]
            ))

        else:
            conn.execute("""
                UPDATE robot_tasks
                SET
                    progress_rate = ?,
                    robot_status = ?,
                    state_machine = ?
                WHERE id = ?
            """, (
                payload.progress_rate,
                payload.robot_status,
                next_state,
                payload.task_id
            ))

        conn.execute("""
            INSERT INTO system_events(event_type, cell_id, message)
            VALUES (?, ?, ?)
        """, (
            "ROBOT_STATUS",
            task["cell_id"],
            "작업률=%s%%, 상태=%s" % (
                payload.progress_rate,
                payload.robot_status
            )
        ))

        return {
            "task_id": payload.task_id,
            "state_machine": next_state
        }


@app.get("/api/robot/next-task")
def next_robot_task():
    with db() as conn:
        task = conn.execute("""
            SELECT *
            FROM robot_tasks
            WHERE state_machine = 'EXECUTE_TASK'
              AND control_state = 'RUN'
            ORDER BY created_at ASC
            LIMIT 1
        """).fetchone()

        if not task:
            return {
                "task": None
            }

        return {
            "task": dict(task)
        }
