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

    #AWS와 통신할 때 요청 제한 시간을 설정합니다. 기본값은 5초입니다.
    aws_timeout: float = float(os.getenv("AWS_TIMEOUT", "5.0"))
    aws_mqtt_broker: str = os.getenv("MQTT_BROKER_HOST", "localhost")
    aws_mqtt_port: int = int(os.getenv("MQTT_BROKER_PORT", "1883"))
    aws_mqtt_topic: str = os.getenv("MQTT_EMERGENCY_STOP_TOPIC", "robot/emergency_stop")
    # [2026-07-18] ESP32 센서 브리지. 기본값 ""(비활성) - AWS 서버가 esp32/sensor를
    # 직접 구독하는 방식(app/mqtt_ingest.py)으로 전환됐기 때문. Jetson 경유가 다시
    # 필요해지면 .env에 MQTT_SENSOR_TOPIC=esp32/sensor 로 켜면 된다.
    # (서버 구독과 동시에 켜면 데이터가 이중 저장되니 한쪽만 켤 것.)
    mqtt_sensor_topic: str = os.getenv("MQTT_SENSOR_TOPIC", "")
    sensor_forward_interval_sec: float = float(os.getenv("SENSOR_FORWARD_INTERVAL_SEC", "10"))

    # [2026-07-23] OTA 원격 자동 업데이트.
    ota_enabled: bool = os.getenv("OTA_ENABLED", "true").lower() in ("1", "true", "yes")
    ota_update_topic: str = os.getenv("OTA_UPDATE_TOPIC", "robot/system/update")
    ota_status_topic: str = os.getenv("OTA_STATUS_TOPIC", "robot/system/status")
    # 저장소 루트 - main.py가 있는 로봇 폴더의 부모(git 저장소 루트)에서 git이 돈다.
    # 실제 젯슨: C:\STREW_VISION\JETSON_ROBOT -> repo_dir=C:\STREW_VISION
    # 모노레포:  .../STREW-VISION_AWS/jetson_robot -> repo_dir=.../STREW-VISION_AWS
    ota_repo_dir: str = os.getenv("OTA_REPO_DIR", os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
    ota_arduino_fqbn: str = os.getenv("OTA_ARDUINO_FQBN", "arduino:avr:mega")
    ota_arduino_port: str = os.getenv("OTA_ARDUINO_PORT", os.getenv("ARDUINO_PORT", "/dev/ttyACM0"))
    # 펌웨어 스케치 경로(repo_dir 기준). 로봇 폴더명이 저장소마다 다르므로
    # (JETSON_ROBOT vs jetson_robot) 실제 폴더명을 자동 감지해서 맞춘다.
    ota_firmware_sketch: str = os.getenv(
        "OTA_FIRMWARE_SKETCH",
        os.path.basename(os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))) + "/mega_firmware",
    )

    arduino_port: str = os.getenv("ARDUINO_PORT", "/dev/ttyACM0")
    arduino_baudrate: int = int(os.getenv("ARDUINO_BAUDRATE", "115200"))
    poll_interval_sec: float = float(os.getenv("POLL_INTERVAL_SEC", "1.0"))
    vision_mode: str = os.getenv("VISION_MODE", "mock")
    csi_camera_index: int = int(os.getenv("CSI_CAMERA_INDEX", "0"))
    frame_width: int = int(os.getenv("FRAME_WIDTH", "1280"))
    frame_height: int = int(os.getenv("FRAME_HEIGHT", "720"))
    # [2026-07-15] ai/detector/camera.py의 TensorRT 로더는 .pt가 아니라 .engine 파일을
    # deserialize_cuda_engine()으로 읽는다. 예전 기본값 "models/best.pt"는 이 로더와
    # 맞지 않는 값이었음 - 실제로는 .onnx -> trtexec 빌드로 나온 .engine 파일 경로가 와야 한다.
    # 아직 실제 .engine 파일은 없음(팀원 ONNX export 대기 중) - 파일이 생기면 이 이름 그대로
    # models/ 밑에 두거나, .env의 YOLO_MODEL_PATH로 실제 경로를 지정하면 된다.
    yolo_model_path: str = os.getenv("YOLO_MODEL_PATH", "models/best.engine")
    # [2026-07-18] YOLOv8 추론 파라미터. 클래스 목록은 "모델을 학습시킨 순서"와 반드시
    # 일치해야 한다 - 다르게 학습했다면 .env의 YOLO_CLASS_NAMES로 콤마 구분 지정.
    yolo_conf_threshold: float = float(os.getenv("YOLO_CONF_THRESHOLD", "0.4"))
    yolo_iou_threshold: float = float(os.getenv("YOLO_IOU_THRESHOLD", "0.45"))
    yolo_input_size: int = int(os.getenv("YOLO_INPUT_SIZE", "640"))
    yolo_class_names: tuple = tuple(
        os.getenv("YOLO_CLASS_NAMES", "healthy,powdery_mildew,missing_plant,empty_cell").split(",")
    )


settings = Config()# Config 클래스의 인스턴스를 생성하고, 환경설정 값을 읽어와서 settings 변수에 저장합니다.
