import os #운영체제와 상호작용하기 위한 모듈을 가져옵니다. 환경 변수 읽기 등에 사용됩니다.
from dataclasses import dataclass #  설정객체를 쉽게 만들기위해 사용

from dotenv import load_dotenv #.env 파일을 읽어 환경변수로 설정하기 위한 모듈을 가져옵니다.


load_dotenv()

'''
load_dotenv()

프로젝트 안에는 보통

.env

파일이 있습니다.

예를 들어

ROBOT_ID=robot-01
API_KEY=123456
AWS_API_BASE=http://192.168.0.10:8000

이렇게 적혀 있습니다.

load_dotenv()는

.env

↓

읽기

↓

프로그램에서 사용할 수 있도록 등록

하는 역할을 합니다.

robot_id = os.getenv("ROBOT_ID", "robot-01")

의 의미는

환경변수에

ROBOT_ID

가 있으면

↓

그 값을 사용

없으면

↓

robot-01 사용

입니다.

즉,

기본값까지 미리 준비해 놓은 것입니다.
'''

#환경설정 읽기
@dataclass(frozen=True)# frozen=True로 설정하여 인스턴스 생성 후 속성 변경을 방지합니다.
class Config: #모든 설정값을 담는 Config 클래스입니다. 
    robot_id: str = os.getenv("ROBOT_ID", "robot-01")
    # AWS 서버 연동을 켜고 끄는 스위치. .env에 AWS_ENABLED=true 로 적으면 켜짐.
    # 값이 없으면(기본값) False -> AWS 없이 로컬 Mock 작업만으로 동작.
    aws_enabled: bool = os.getenv("AWS_ENABLED", "false").lower() in ("1", "true", "yes")
    aws_api_base: str = os.getenv("AWS_API_BASE", "http://localhost:8000").rstrip("/")
    api_key: str = os.getenv("API_KEY", "change-me")
    arduino_port: str = os.getenv("ARDUINO_PORT", "/dev/ttyACM0")
    arduino_baudrate: int = int(os.getenv("ARDUINO_BAUDRATE", "115200"))
    poll_interval_sec: float = float(os.getenv("POLL_INTERVAL_SEC", "1.0"))
    vision_mode: str = os.getenv("VISION_MODE", "csi")
    csi_camera_index: int = int(os.getenv("CSI_CAMERA_INDEX", "0"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))
    yolo_model_path: str = os.getenv("YOLO_MODEL_PATH", "models/best.pt")


settings = Config()# Config 클래스의 인스턴스를 생성하고, 환경설정 값을 읽어와서 settings 변수에 저장합니다.
