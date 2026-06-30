# 핵심 파일 지도

## AWS 서버

| 파일 | 역할 |
|---|---|
| `AWS_SYSTEM/app/main.py` | API 주소를 정의한다. 서버의 입구다. |
| `AWS_SYSTEM/app/schemas.py` | 데이터 모양을 정의한다. 작업/응답/비전 결과의 약속이다. |
| `AWS_SYSTEM/app/repository.py` | 데이터를 저장하고 읽는다. 로컬 JSON 또는 AWS DynamoDB를 사용한다. |
| `AWS_SYSTEM/app/static/index.html` | 작업을 넣어볼 수 있는 간단한 화면이다. |
| `AWS_SYSTEM/Dockerfile` | AWS에 올릴 서버 이미지를 만든다. |
| `AWS_SYSTEM/terraform/main.tf` | AWS 인프라를 코드로 만든다. |

## Jetson Nano

| 파일 | 역할 |
|---|---|
| `JETSON_ROBOT/strew_robot/main.py` | Jetson 프로그램 시작점이다. |
| `JETSON_ROBOT/strew_robot/agent.py` | 작업 수신부터 결과 보고까지 전체 순서를 담당한다. |
| `JETSON_ROBOT/strew_robot/cloud_client.py` | AWS 서버와 HTTP로 통신한다. |
| `JETSON_ROBOT/strew_robot/arduino_link.py` | Arduino Mega로 JSON 명령을 보낸다. |
| `JETSON_ROBOT/strew_robot/vision_source.py` | CSI 웹캠을 OpenCV로 읽고 비전 결과를 만든다. |
| `JETSON_ROBOT/.env.example` | Jetson 실행 설정 예시다. |

## Arduino Mega

| 파일 | 역할 |
|---|---|
| `JETSON_ROBOT/arduino_mega/strew_mega_receiver.ino` | Jetson에서 온 JSON 명령을 읽고 응답하는 예제 스케치다. |

## 기존 파일

| 파일 | 역할 |
|---|---|
| `STREW_VISION.drawio` | YOLO, Jetson, Web Server, Robot Request/Response 관계가 들어 있는 전체 구조 초안이다. |
| `JETSON/jetsontest.txt` | CSI 카메라 드라이버와 `/dev/video0` 확인 메모가 있다. |
| `VISION_DATA` | 학습 데이터와 비전 데이터가 들어 있다. |
