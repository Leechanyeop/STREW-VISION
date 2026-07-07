from robot.planner import plan_task

# 테스트는 pytest를 사용하여 작성되었습니다. 
# pytest를 설치한 후, 터미널에서 `pytest tests/test_decision.py` 
# 명령어를 실행하면 테스트를 수행할 수 있습니다.
def test_healthy_means_observe():
    result = plan_task({"id": "1"}, {"status": "healthy"})
    assert result["execute_task"] == "OBSERVE" # 


def test_powdery_mildew_means_replace():
    result = plan_task({"id": "1"}, {"status": "powdery_mildew"})
    assert result["execute_task"] == "REPLACE"


def test_missing_plant_means_replace():
    result = plan_task({"id": "1"}, {"status": "missing_plant"})
    assert result["execute_task"] == "REPLACE"


def test_unknown_or_missing_status_defaults_to_skip():
    assert plan_task({"id": "1"}, {})["execute_task"] == "SKIP"
    assert plan_task({"id": "1"}, {"status": "garbage"})["execute_task"] == "SKIP"


def test_original_task_and_vision_are_preserved():
    # execute_task가 추가되어도 원래 task/vision 정보가 사라지면 안 된다.
    task = {"id": "42", "cell_id": 3}
    vision = {"status": "healthy", "x_center": 640}
    result = plan_task(task, vision)
    assert result["task"] == task
    assert result["vision"] == vision
