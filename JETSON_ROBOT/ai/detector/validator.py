def is_valid_detection(result: dict) -> bool:
    return result.get("label") is not None
