# JETSON_ROBOT 설명

## 핵심 파일

- `JETSON_ROBOT/strew_robot/main.py`: Jetson 프로그램 시작점이다.
- `JETSON_ROBOT/strew_robot/agent.py`: AWS 작업 수신, CSI 카메라 읽기, Arduino 전송, AWS 결과 보고를 순서대로 실행한다.
- `JETSON_ROBOT/strew_robot/cloud_client.py`: AWS 서버 API와 통신한다.
- `JETSON_ROBOT/strew_robot/arduino_link.py`: Arduino Mega와 USB 시리얼로 JSON을 주고받는다.
- `JETSON_ROBOT/strew_robot/vision_source.py`: CSI 웹캠을 OpenCV로 읽어 비전 결과를 만든다.
- `JETSON_ROBOT/arduino_mega/strew_mega_receiver.ino`: Arduino Mega에서 JSON 명령을 받는 예제다.
- `JETSON_ROBOT/systemd/strew-robot-agent.service`: Jetson 부팅 후 자동 실행용 서비스 파일이다.

## Jetson Nano 준비

CSI 카메라가 보이는지 먼저 확인한다.

```bash
ls /dev/video*
v4l2-ctl -d /dev/video0 --info
```

OpenCV가 없다면 Jetson에서는 보통 pip보다 apt 설치가 안정적이다.

```bash
sudo apt update
sudo apt install -y python3-opencv v4l-utils
```

## 실행 순서

```bash
cd ~/STREW_VISION/JETSON_ROBOT
cp .env.example .env
nano .env
bash scripts/run_agent.sh
```

`.env`에서 꼭 바꿀 값:

```bash
AWS_API_BASE=http://AWS서버주소
API_KEY=AWS_SYSTEM과_같은_키
ARDUINO_PORT=/dev/ttyACM0
VISION_MODE=csi
CSI_CAMERA_INDEX=0
```

## YOLO 연결 위치

현재 `vision_source.py`에는 YOLO 연결 위치가 `_read_with_yolo_placeholder()`로 분리되어 있다. `YOLO_MODEL_PATH`에 모델 경로를 넣고, 해당 함수에서 YOLO 추론 결과를 `VisionResult`로 바꾸면 된다.

처음 테스트할 때는 YOLO 없이 기본 윤곽선 감지로 카메라와 AWS/Arduino 흐름이 정상인지 먼저 확인하는 것이 좋다.
