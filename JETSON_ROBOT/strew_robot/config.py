import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()

@dataclass(frozen=True)
class Config:
    robot_id: str = os.getenv("ROBOT_ID", "robot-01")
    aws_api_base: str = os.getenv("AWS_API_BASE", "http://localhost:8000").rstrip("/")
    api_key: str = os.getenv("API_KEY", "change-me")
    arduino_port: str = os.getenv("ARDUINO_PORT", "/dev/ttyACM0")
    arduino_baudrate: int = int(os.getenv("ARDUINO_BAUDRATE", "115200"))
    poll_interval_sec: float = float(os.getenv("POLL_INTERVAL_SEC", "1.0"))
    vision_mode: str = os.getenv("VISION_MODE", "csi")
    csi_camera_index: int = int(os.getenv("CSI_CAMERA_INDEX", "0"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))
    yolo_model_path: str = os.getenv("YOLO_MODEL_PATH", "")
