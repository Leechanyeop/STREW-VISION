import time
from typing import Any, Dict
from .arduino_link import ArduinoLink
from .cloud_client import CloudClient
from .config import Config
from .models import ArduinoCommand
from .vision_source import create_vision_source

class RobotAgent:
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cloud = CloudClient(cfg.aws_api_base, cfg.api_key)
        self.vision = create_vision_source(cfg.vision_mode, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path)
        self.arduino = ArduinoLink(cfg.arduino_port, cfg.arduino_baudrate)

    def close(self) -> None:
        self.arduino.close()
        close = getattr(self.vision, "close", None)
        if close:
            close()

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

    def run_once(self) -> None:
        task = self.cloud.next_task(self.cfg.robot_id)
        if not task:
            return
        vision = self.vision.read().to_payload()
        self.cloud.post_vision_event(self.cfg.robot_id, vision)
        command = self.build_command(task, vision).to_dict()
        arduino_response = self.arduino.send_json_line(command) or {"completion_sign": "DONE", "message": "sent without ack"}
        completion = str(arduino_response.get("completion_sign", "DONE")).upper()
        self.cloud.post_response(
            task_id=task["id"],
            robot_id=self.cfg.robot_id,
            execute_task=task["execute_task"],
            completion_sign=completion,
            message=str(arduino_response.get("message", "arduino processed command")),
            payload={"vision": vision, "arduino_command": command, "arduino_response": arduino_response},
        )

    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
                time.sleep(self.cfg.poll_interval_sec)
        finally:
            self.close()
