# 카메라/AI가 판단한 식물 상태(status)를 보고,
# 로봇이 실제로 뭘 할지 결정하는 곳입니다.
# Notion Chapter 05-4가 정한 규칙표는 이렇습니다.
#
# [2026-07-15 아키텍처 변경 이후: 더 이상 런타임 경로에서 안 씀]
# 결정권(REPLACE/OBSERVE/SKIP)이 Jetson에서 Mega로 이전되면서, 실제 실행 중엔
# robot/state_machine.py가 이 파일을 더 이상 import/호출하지 않는다.
# 그래도 지우지 않고 남겨둔 이유: (1) tests/test_decision.py가 이 로직을 테스트하고
# 있어서 지우면 그 커버리지가 사라짐, (2) 이 ACTION_MAP이 곧 Mega 펌웨어(C++)로
# 그대로 옮겨 심어야 할 "정답 스펙" 역할을 함 — 나중에 mega_firmware.ino에 결정
# 로직을 포팅할 때 여기를 보고 그대로 옮기면 됨. 포팅 끝나고 나면 이 파일은
# 그때 가서 삭제해도 됨.

#
ACTION_MAP = {
    "healthy": "OBSERVE",
    "powdery_mildew": "REPLACE",
    "missing_plant": "REPLACE",
    
} 

# task는 AWS 에서 내려주는 작업(task)입니다.
# vision은 카메라/AI가 판단한 식물 상태(status)입니다.
# execute_task는 로봇이 실제로 수행할 작업입니다.

def plan_task(task: dict, vision: dict) -> dict:

 
    
    status = vision.get("status") #카메라/AI가 판단한 식물 상태(status)를 가져옵니다.

   
    execute_task = ACTION_MAP.get(status, "SKIP") # 상태가 없으면 기본값으로 "SKIP"를 사용합니다.


    return {"task":task, "vision": vision, "execute_task": execute_task}
