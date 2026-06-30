def build_detection_event(robot_id: str, result: dict) -> dict:
    return {"robot_id": robot_id, **result}
