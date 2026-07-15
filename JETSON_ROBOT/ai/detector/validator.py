# 최소의 데이터 형식 검증하는 파일

def is_valid_detection(result: dict) -> bool:
    return result.get("label") is not None
