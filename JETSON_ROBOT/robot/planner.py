# 카메라/AI가 판단한 식물 상태(status)를 보고, 
# 로봇이 실제로 뭘 할지 결정하는 곳입니다. 
# Notion Chapter 05-4가 정한 규칙표는 이렇습니다.

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
