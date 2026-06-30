from robot.planner import plan_task


def test_planner_returns_task_and_vision():
    assert plan_task({"id": "1"}, {"label": "RED"}) == {
        "task": {"id": "1"},
        "vision": {"label": "RED"},
    }
