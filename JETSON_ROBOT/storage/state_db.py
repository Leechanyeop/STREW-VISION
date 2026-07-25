"""[2026-07-25] Jetson 상태 관리 SQLite DB (System Architecture v2.0).

이 DB가 로봇 상태의 Source of Truth다. STATE를 받을 때마다 여기 저장하고,
Recovery(전원/네트워크 끊김 복구)는 EEPROM이 아니라 이 DB를 기준으로 수행한다.
AWS가 끊겨도 Jetson은 이 DB만으로 계속 동작·복구할 수 있어야 한다.

테이블 (v2.0 문서 + 협의 반영):
  current_task       현재 작업 상태 (Recovery 기준). cycle당 1행 유지(덮어씀).
  detection_log      Vision 판독 결과 로그 (Healthy/Disease, confidence, view).
  inspection_images  Inspection 사진 5장(TOP/LEFT/RIGHT/LOW/FRONT) 경로 관리.
  task_history       작업 이력 (REPLACE 등, 시작/종료/결과).
  system_config      Dashboard 설정값 (confidence_threshold, max_view 등).

파이썬 3.6(젯슨 나노) 호환 - sqlite3 표준 라이브러리만 사용.
"""

import sqlite3
import time
from typing import Any, Dict, List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS current_task (
    id           INTEGER PRIMARY KEY CHECK (id = 1),  -- 항상 1행만
    cycle_id     TEXT,
    cell_id      INTEGER,
    state        TEXT,
    task         TEXT,
    view         TEXT,
    status       TEXT,                                -- RUNNING / COMPLETE
    updated_at   TEXT
);

CREATE TABLE IF NOT EXISTS detection_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id        TEXT,
    cell_id         INTEGER,
    detection_class TEXT,                             -- Healthy / Disease
    confidence      REAL,
    view            TEXT,
    created_at      TEXT
);

CREATE TABLE IF NOT EXISTS inspection_images (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id    TEXT,
    cell_id     INTEGER,
    view        TEXT,                                 -- TOP/LEFT/RIGHT/LOW/FRONT
    image_path  TEXT,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS task_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    cycle_id    TEXT,
    cell_id     INTEGER,
    task        TEXT,
    result      TEXT,                                 -- COMPLETE / ERROR
    start_time  TEXT,
    end_time    TEXT
);

CREATE TABLE IF NOT EXISTS system_config (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""

# system_config 기본값 (없으면 채운다).
DEFAULT_CONFIG = {
    "confidence_threshold": "0.8",   # 이 값 이상이어야 Disease로 확정
    "max_view": "5",                 # Observation Planner 최대 View 촬영 횟수
}


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


class StateDB:
    def __init__(self, db_path: str = "data/robot_state.db"):
        # check_same_thread=False: UART 리스너 스레드와 메인이 함께 접근할 수 있어서.
        # 쓰기는 짧고 커밋 단위라 커넥션 하나 + 기본 락으로 충분하다.
        import os
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._seed_config()
        self.conn.commit()

    def _seed_config(self) -> None:
        for k, v in DEFAULT_CONFIG.items():
            self.conn.execute(
                "INSERT OR IGNORE INTO system_config(key, value) VALUES (?, ?)", (k, v)
            )

    # ---------- current_task (Recovery 기준) ----------
    def update_current_task(self, cycle_id=None, cell_id=None, state=None, task=None,
                            view=None, status="RUNNING") -> None:
        """현재 작업 상태를 갱신(항상 id=1 행 하나만 유지). STATE 받을 때마다 호출.

        INSERT OR REPLACE를 쓴다(모든 컬럼을 매번 넘기므로 안전). ON CONFLICT DO UPDATE는
        SQLite 3.24+ 전용인데 젯슨 나노(Ubuntu 18.04)는 3.22라 못 쓴다.
        """
        self.conn.execute("""
            INSERT OR REPLACE INTO current_task(id, cycle_id, cell_id, state, task, view, status, updated_at)
            VALUES (1, ?, ?, ?, ?, ?, ?, ?)
        """, (cycle_id, cell_id, state, task, view, status, _now()))
        self.conn.commit()

    def get_current_task(self) -> Optional[Dict[str, Any]]:
        row = self.conn.execute("SELECT * FROM current_task WHERE id = 1").fetchone()
        return dict(row) if row else None

    def clear_current_task(self) -> None:
        self.conn.execute("UPDATE current_task SET status='COMPLETE', updated_at=? WHERE id=1", (_now(),))
        self.conn.commit()

    # ---------- detection_log ----------
    def add_detection(self, cycle_id, cell_id, detection_class, confidence, view) -> int:
        cur = self.conn.execute("""
            INSERT INTO detection_log(cycle_id, cell_id, detection_class, confidence, view, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (cycle_id, cell_id, detection_class, confidence, view, _now()))
        self.conn.commit()
        return cur.lastrowid

    def list_detections(self, limit=50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM detection_log ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- inspection_images (사진 5장) ----------
    def add_image(self, cycle_id, cell_id, view, image_path) -> int:
        cur = self.conn.execute("""
            INSERT INTO inspection_images(cycle_id, cell_id, view, image_path, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (cycle_id, cell_id, view, image_path, _now()))
        self.conn.commit()
        return cur.lastrowid

    def get_images(self, cycle_id, cell_id) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM inspection_images WHERE cycle_id=? AND cell_id=? ORDER BY id",
            (cycle_id, cell_id),
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- task_history ----------
    def start_task(self, cycle_id, cell_id, task) -> int:
        cur = self.conn.execute("""
            INSERT INTO task_history(cycle_id, cell_id, task, result, start_time)
            VALUES (?, ?, ?, NULL, ?)
        """, (cycle_id, cell_id, task, _now()))
        self.conn.commit()
        return cur.lastrowid

    def finish_task(self, task_row_id, result) -> None:
        self.conn.execute(
            "UPDATE task_history SET result=?, end_time=? WHERE id=?",
            (result, _now(), task_row_id),
        )
        self.conn.commit()

    def list_task_history(self, limit=50) -> List[Dict[str, Any]]:
        rows = self.conn.execute(
            "SELECT * FROM task_history ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

    # ---------- system_config ----------
    def get_config(self, key, default=None) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM system_config WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def get_config_float(self, key, default=0.0) -> float:
        v = self.get_config(key)
        try:
            return float(v) if v is not None else default
        except ValueError:
            return default

    def get_config_int(self, key, default=0) -> int:
        v = self.get_config(key)
        try:
            return int(float(v)) if v is not None else default
        except ValueError:
            return default

    def set_config(self, key, value) -> None:
        # INSERT OR REPLACE (구 SQLite 호환). key가 PRIMARY KEY라 값만 갈아끼워진다.
        self.conn.execute(
            "INSERT OR REPLACE INTO system_config(key, value) VALUES (?, ?)", (key, str(value))
        )
        self.conn.commit()

    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass
