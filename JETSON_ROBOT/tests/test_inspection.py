"""[2026-07-25 Phase C] Multi-View Inspection 검증.

- aggregate_views(): 여러 View 종합 판정 로직 (순수 함수)
- _handle_vision_ready(): 4 View 순회 → NEXT_VIEW/TASK 분기 (하드웨어 없이)
"""

import os
import tempfile

import pytest

from robot.command import aggregate_views, INSPECTION_VIEWS
from robot.state_machine import RobotAgent
from storage.state_db import StateDB
from ai.detector.result import VisionResult


# ---------------- aggregate_views (순수 로직) ----------------

def test_aggregate_picks_most_severe():
    # 병해충이 한 View에서라도 잡히면 최종 병해충 (미검출 방지).
    views = [
        {"view": "TOP", "status": "healthy", "confidence": 0.9},
        {"view": "LEFT", "status": "healthy", "confidence": 0.8},
        {"view": "RIGHT", "status": "powdery_mildew", "confidence": 0.7},
        {"view": "FRONT", "status": "healthy", "confidence": 0.85},
    ]
    status, conf = aggregate_views(views)
    assert status == "powdery_mildew"
    assert conf == 0.7


def test_aggregate_all_healthy():
    views = [{"view": v, "status": "healthy", "confidence": 0.6} for v in INSPECTION_VIEWS]
    status, conf = aggregate_views(views)
    assert status == "healthy"
    assert conf == 0.6


def test_aggregate_same_status_takes_max_conf():
    views = [
        {"view": "TOP", "status": "powdery_mildew", "confidence": 0.55},
        {"view": "LEFT", "status": "powdery_mildew", "confidence": 0.82},
    ]
    status, conf = aggregate_views(views)
    assert status == "powdery_mildew"
    assert conf == 0.82


def test_aggregate_empty():
    assert aggregate_views([]) == ("healthy", 0.0)


# ---------------- _handle_vision_ready (View 순회) ----------------

class FakeArduino:
    def __init__(self):
        self.sent = []
    def send_json_line(self, payload):
        self.sent.append(payload); return True
    def _read_json_line(self):
        return None
    def close(self):
        pass


class SeqVision:
    """호출될 때마다 미리 정한 status를 순서대로 반환하는 가짜 Vision."""
    def __init__(self, statuses):
        self.statuses = list(statuses)
        self.i = 0
    def read(self):
        s = self.statuses[self.i]
        self.i += 1
        return VisionResult(label="x", confidence=0.7, status=s)


@pytest.fixture()
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.unlink(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def make_agent(tmp_db, statuses):
    agent = RobotAgent.__new__(RobotAgent)
    class Cfg:
        robot_id = "robot-01"; aws_enabled = False
    agent.cfg = Cfg()
    agent.arduino = FakeArduino()
    agent.state_db = StateDB(tmp_db)
    agent.current_task = {"id": "c-1"}
    agent.vision = SeqVision(statuses)
    agent._inspect_cell = None
    agent._inspect_results = []
    return agent


def _run_4_views(agent, cell=2):
    # Mega가 4번 VISION_READY(view)를 순서대로 보낸다고 흉내.
    # 설계 ②: View 진행은 ACK(_on_state)로 이뤄지므로 _handle_vision_ready는
    # 1~3번째엔 아무것도 안 보내고, 4번째(마지막)에만 TASK를 보낸다.
    for view in INSPECTION_VIEWS:
        agent._handle_vision_ready(cell, view)


def test_four_views_send_only_task_no_next_view(tmp_db):
    # 전부 healthy -> NEXT_VIEW 0번, TASK 1번(OBSERVE). View 진행은 ACK로.
    agent = make_agent(tmp_db, ["healthy"] * 4)
    _run_4_views(agent)
    cmds = [m["cmd"] for m in agent.arduino.sent]
    assert "NEXT_VIEW" not in cmds        # ② 설계: NEXT_VIEW 없음
    assert cmds.count("TASK") == 1        # 마지막 View 후에만 TASK
    task = [m for m in agent.arduino.sent if m["cmd"] == "TASK"][0]
    assert task["task"] == "OBSERVE"


def test_task_only_after_last_view(tmp_db):
    # 3번째 View까지는 TASK가 안 나가고, 4번째에만 나간다.
    agent = make_agent(tmp_db, ["healthy"] * 4)
    for view in INSPECTION_VIEWS[:3]:
        agent._handle_vision_ready(2, view)
    assert not any(m["cmd"] == "TASK" for m in agent.arduino.sent)   # 아직 판정 안 함
    agent._handle_vision_ready(2, INSPECTION_VIEWS[3])
    assert any(m["cmd"] == "TASK" for m in agent.arduino.sent)       # 4장째에 판정


def test_disease_in_one_view_results_replace(tmp_db):
    # RIGHT에서 병해충 -> 종합 판정 병해충 -> TASK=REPLACE (aws_enabled=False라 승인 생략)
    agent = make_agent(tmp_db, ["healthy", "healthy", "powdery_mildew", "healthy"])
    _run_4_views(agent)
    task = [m for m in agent.arduino.sent if m["cmd"] == "TASK"][0]
    assert task["task"] == "REPLACE"


def test_images_saved_per_view(tmp_db):
    agent = make_agent(tmp_db, ["healthy"] * 4)
    _run_4_views(agent)
    rows = agent.state_db.get_images("c-1", 2)
    assert len(rows) == 4
    assert [r["view"] for r in rows] == list(INSPECTION_VIEWS)
    assert all(r["confidence"] == 0.7 for r in rows)
