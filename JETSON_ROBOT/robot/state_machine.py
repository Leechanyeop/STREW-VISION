import time
import random
from typing import Any, Dict

from ai.detector.camera import create_vision_source
from config.settings import Config
from robot.command import ArduinoCommand
from robot.planner import plan_task
from robot.uart import ArduinoLink
from cloud.api_client import CloudClient


# AWS가 꺼져 있을 때(cfg.aws_enabled=False) 대신 사용하는 로컬 랜덤 목업 작업.
# 실제 AWS가 줄 법한 것만(id, target_label) 담고, execute_task는 plan_task()가 계산한다.
def build_mock_task() -> Dict[str, Any]:
    return {
        "id": str(random.randint(1, 1000)),
        "target_label": random.choice(["cell_1", "cell_2", "cell_3","cell_4"])
    }


class RobotAgent:

    # RobotAgent 클래스는 로봇의 상태를 관리하고, AWS 클라우드와의 통신, 비전 처리, 아두이노 명령 전송 등을 담당합니다.
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cloud = CloudClient(cfg.aws_api_base, cfg.api_key) #AWS 클라우드 API 클라이언트를 초기화합니다.
        self.vision = create_vision_source( # 카메라로 보는 도구 실제 비전인식 값
            cfg.vision_mode,
            cfg.csi_camera_index,
            cfg.frame_width,
            cfg.frame_height,
            cfg.yolo_model_path,
        )
        self.arduino = ArduinoLink(cfg.arduino_port, cfg.arduino_baudrate)

    # close 메서드는 아두이노와 비전 소스를 닫는 역할을 합니다. 
    # 아두이노와 비전 소스가 열려 있는 경우에만 닫습니다.
    def close(self) -> None:
        self.arduino.close()
        close = getattr(self.vision, "close", None)
        if close:
            close()

    # build_command 메서드는 주어진 task와 vision 정보를 기반으로 ArduinoCommand 객체를 생성합니다.
    def build_command(self, task: Dict[str, Any], vision: Dict[str, Any]) -> ArduinoCommand:
        return ArduinoCommand(
            task_id=task["id"],
            execute_task=task["execute_task"],
            move_sign=task.get("move_sign", "STOP"),
            target_label=task.get("target_label"),
            detected_label=vision.get("label"),
            x_center=vision.get("x_center"),
            y_center=vision.get("y_center"),
        )

    # run_once 메서드는 한 번의 작업 주기를 실행합니다.
    # AWS가 활성화되어 있으면 클라우드에서 작업을 가져오고,
    # 비전 정보를 읽어 아두이노로 명령을 전송하고,
    # 그 결과를 클라우드에 보고합니다. 
    # AWS가 비활성화되어 있으면 로컬 랜덤 목업 작업(build_mock_task())을 사용합니다.
    def run_once(self) -> None:
        
        
        # AWS가 활성화되어 있으면 클라우드에서 작업을 가져오고, 비활성화되어 있으면 로컬 랜덤 목업 작업을 사용합니다.
        if self.cfg.aws_enabled:
            task = self.cloud.next_task(self.cfg.robot_id)
            if not task:
                return
        else:
            task = build_mock_task()  # AWS가 비활성화되어 있으면 로컬 랜덤 목업 작업을 사용합니다.

        # vision 정보를 읽어옵니다. 이 정보는 카메라/AI가 판단한 식물 상태(status)를 포함합니다.
        vision = self.vision.read().to_payload()

        # AWS가 활성화되어 있으면 클라우드에 vision 이벤트를 보고합니다.
        if self.cfg.aws_enabled:
            self.cloud.post_vision_event(self.cfg.robot_id, vision)

        decision = plan_task(task, vision)  # task와 vision 정보를 기반으로 로봇이 실제로 수행할 작업을 결정합니다.
        # task와 vision 정보를 기반으로 아두이노로 보낼 2필드 명령을 생성합니다.
        command = {"command": decision["execute_task"],"target": task.get("target_label")}

        # 아두이노로 명령을 보내고, COMPLETE까지 진행상황을 하나씩 받습니다. 응답이 하나도 없으면 기본값으로 처리합니다.
        arduino_response  = {"state": "RECEIVED","progress": 0}
        
        for message in self.arduino.stream_progress(command):
            if message is not None:
                arduino_response = message
            
        completion = str(arduino_response.get("state","error")).upper()

        # AWS가 활성화되어 있으면 클라우드에 결과를 보고하고, 
        # 비활성화되어 있으면 콘솔에 결과를 출력합니다.
        if self.cfg.aws_enabled:

            self.cloud.post_response(
                task_id = task["id"],
                robot_id = self.cfg.robot_id,
                execute_task = decision["execute_task"],
                completion_sign = completion,
                message = str(arduino_response.get("message", "arduino processed command")),
                payload = {
                    "vision": vision,
                    "arduino_command": command,
                    "arduino_response": arduino_response,
                },
            )
        else:
            # AWS 없이 로컬에서만 돌릴 때는 서버에 보고하는 대신 콘솔에 결과를 남긴다.
            print(
                f"[AWS disabled] task={task['id']} execute_task={decision['execute_task']} "
                f"completion={completion} vision={vision}"
            )

    # run_forever 메서드는 무한 루프를 돌며 run_once를 반복 실행합니다.
    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
                time.sleep(self.cfg.poll_interval_sec)
        finally:
            self.close()
