from enum import Enum
import time

class State(Enum):
    AI_DETECT = 1
    WAIT_APPROVAL = 2
    EXECUTE_TASK = 3
    REPORT_STATUS = 4
    COMPLETE = 5

class RobotSystem:
    def __init__(self, plant_id):
        self.state = State.AI_DETECT
        self.plant_id = plant_id
        self.disease_name = None
        self.probability = 0
        self.approved = False
        self.task_name = None

    def ai_detect(self, disease_name, probability):
        self.disease_name = disease_name
        self.probability = probability
        print(f"[AI 판독] {self.plant_id}번 셀: {disease_name} {probability}%")
        if probability >= 80:
            self.state = State.WAIT_APPROVAL
        else:
            self.state = State.COMPLETE

    def wait_approval(self):
        print("[웹 서버] 검토창 표시 중…")
        # 관리자 승인 대기
        time.sleep(2)
        self.approved = True  # 예시로 자동 승인
        if self.approved:
            self.state = State.EXECUTE_TASK

    def execute_task(self, task_name):
        self.task_name = task_name
        print(f"[로봇] {self.plant_id}번 셀 {task_name} 작업 수행 중…")
        time.sleep(3)
        self.state = State.REPORT_STATUS

    def report_status(self):
        print(f"[젯슨나노] {self.plant_id}번 셀 작업률 100% 완료")
        self.state = State.COMPLETE

    def run(self):
        while self.state != State.COMPLETE:
            if self.state == State.AI_DETECT:
                self.ai_detect("흰곰팡이병", 85)
            elif self.state == State.WAIT_APPROVAL:
                self.wait_approval()
            elif self.state == State.EXECUTE_TASK:
                self.execute_task("보식")
            elif self.state == State.REPORT_STATUS:
                self.report_status()
        print("[DB] 작업 완료 및 데이터 갱신")

# 실행 예시
robot = RobotSystem(plant_id=4)
robot.run()
