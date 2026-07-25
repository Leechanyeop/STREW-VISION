"""[2026-07-25] Jetson 상태 SQLite DB 검증 (Phase A). 임시 파일 DB로 격리."""

import os
import tempfile

import pytest

from storage.state_db import StateDB


@pytest.fixture()
def db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    os.unlink(path)   # StateDB가 새로 만들게
    d = StateDB(path)
    yield d
    d.close()
    if os.path.exists(path):
        os.unlink(path)


def test_config_defaults_seeded(db):
    assert db.get_config_float("confidence_threshold") == 0.8
    assert db.get_config_int("max_view") == 5


def test_config_set_and_get(db):
    db.set_config("confidence_threshold", 0.9)
    assert db.get_config_float("confidence_threshold") == 0.9
    db.set_config("max_view", 3)
    assert db.get_config_int("max_view") == 3


def test_current_task_upsert_keeps_single_row(db):
    db.update_current_task(cycle_id="c1", cell_id=1, state="MOVE_CELL", task=None, view=None)
    db.update_current_task(cycle_id="c1", cell_id=1, state="VISION_READY", task=None, view="TOP")
    cur = db.get_current_task()
    assert cur["state"] == "VISION_READY"      # 최신값
    assert cur["view"] == "TOP"
    assert cur["status"] == "RUNNING"
    # 항상 1행만 유지되는지
    rows = db.conn.execute("SELECT COUNT(*) c FROM current_task").fetchone()
    assert rows["c"] == 1


def test_recovery_reads_last_state(db):
    # 전원 OFF 흉내: 상태 저장 후 새 커넥션으로 다시 읽어도 남아있어야 한다.
    db.update_current_task(cycle_id="c9", cell_id=3, state="TASK_DONE", task="REPLACE", view="FRONT")
    path = db.conn.execute("PRAGMA database_list").fetchone()["file"]
    db.close()
    db2 = StateDB(path)
    cur = db2.get_current_task()
    assert cur["cell_id"] == 3
    assert cur["task"] == "REPLACE"
    db2.close()


def test_detection_log(db):
    db.add_detection("c1", 2, "Disease", 0.96, "TOP")
    db.add_detection("c1", 2, "Healthy", 0.40, "LEFT")
    rows = db.list_detections()
    assert len(rows) == 2
    assert rows[0]["detection_class"] == "Healthy"   # 최신순
    assert rows[1]["confidence"] == 0.96


def test_inspection_images_5_views(db):
    for view in ("TOP", "LEFT", "RIGHT", "LOW", "FRONT"):
        db.add_image("c1", 5, view, f"/data/img/c1_cell5_{view}.jpg")
    imgs = db.get_images("c1", 5)
    assert len(imgs) == 5
    assert [i["view"] for i in imgs] == ["TOP", "LEFT", "RIGHT", "LOW", "FRONT"]


def test_task_history_start_finish(db):
    tid = db.start_task("c1", 4, "REPLACE")
    hist = db.list_task_history()
    assert hist[0]["result"] is None            # 시작만 한 상태
    db.finish_task(tid, "COMPLETE")
    hist = db.list_task_history()
    assert hist[0]["result"] == "COMPLETE"
    assert hist[0]["end_time"] is not None


def test_clear_current_task(db):
    db.update_current_task(cycle_id="c1", cell_id=1, state="MOVE_CELL")
    db.clear_current_task()
    assert db.get_current_task()["status"] == "COMPLETE"
