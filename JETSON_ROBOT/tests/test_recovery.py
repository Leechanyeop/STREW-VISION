"""[2026-07-25 Phase B] SQLite 기반 Recovery(RESUME) 검증.

_check_recovery()와 _on_ready()의 RUN/RESUME 분기를 하드웨어 없이 검증한다.
StateDB는 /tmp 임시 파일, ArduinoLink는 전송을 기록하는 가짜로 교체.
"""

import os
import tempfile

import pytest

from robot.state_machine import RobotAgent
from storage.state_db import StateDB


class FakeArduino:
    def __init__(self):
        self.sent = []
    def send_json_line(self, payload):
        self.sent.append(payload); return True
    def _read_json_line(self):
        return None
    def close(self):
        pass


def make_agent(tmp_db, aws_enabled=False):
    """RobotAgent를 하드웨어/스레드 없이 최소 구성으로 만든다."""
    agent = RobotAgent.__new__(RobotAgent)  # __init__ 우회 (스레드/시리얼 회피)

    class Cfg:
        robot_id = "robot-01"
    agent.cfg = Cfg()
    agent.cfg.aws_enabled = aws_enabled
    agent.arduino = FakeArduino()
    agent.state_db = StateDB(tmp_db)
    agent.current_task = None
    agent.cycle_active = False

    # _on_ready가 참조하는 것들 스텁
    agent.last_pong_time = 0.0

    class FakeCloud:
        def next_task(self, robot_id):
            return {"id": "aws-task-123"}
    agent.cloud = FakeCloud()
    return agent


@pytest.fixture()
def tmp_db():
    fd, path = tempfile.mkstemp(suffix=".db"); os.close(fd); os.unlink(path)
    yield path
    if os.path.exists(path):
        os.unlink(path)


def test_no_prior_task_sends_run(tmp_db):
    agent = make_agent(tmp_db)
    agent._on_ready()
    cmds = [m["cmd"] for m in agent.arduino.sent]
    assert "RUN" in cmds
    assert "RESUME" not in cmds


def test_interrupted_running_task_sends_resume(tmp_db):
    agent = make_agent(tmp_db)
    # 셀 3에서 작업 중 전원이 끊긴 상황을 흉내: status=RUNNING, cell=3
    agent.state_db.update_current_task(cycle_id="c-9", cell_id=3, state="TASK_DONE",
                                       task="REPLACE", status="RUNNING")
    agent._on_ready()
    resume = [m for m in agent.arduino.sent if m["cmd"] == "RESUME"]
    assert len(resume) == 1
    assert resume[0]["cell"] == 3
    assert resume[0]["cycle_id"] == "c-9"
    assert not any(m["cmd"] == "RUN" for m in agent.arduino.sent)


def test_completed_task_sends_run_not_resume(tmp_db):
    agent = make_agent(tmp_db)
    # 정상 완료(status=COMPLETE) -> 재개할 게 없으니 새 RUN
    agent.state_db.update_current_task(cycle_id="c-1", cell_id=4, state="COMPLETE",
                                       status="COMPLETE")
    agent._on_ready()
    cmds = [m["cmd"] for m in agent.arduino.sent]
    assert "RUN" in cmds
    assert "RESUME" not in cmds


def test_run_only_no_cell_sends_run(tmp_db):
    agent = make_agent(tmp_db)
    # RUN만 기록되고 STATE 전(cell_id=None) -> RESUME 대신 새 RUN이 낫다
    agent.state_db.update_current_task(cycle_id="c-2", cell_id=None, state="RUN",
                                       status="RUNNING")
    agent._on_ready()
    cmds = [m["cmd"] for m in agent.arduino.sent]
    assert "RUN" in cmds
    assert "RESUME" not in cmds


def test_check_recovery_returns_none_without_db(tmp_db):
    agent = make_agent(tmp_db)
    agent.state_db = None
    assert agent._check_recovery() is None
