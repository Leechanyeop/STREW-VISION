# STREW VISION 전체 시스템 개요

## 한 줄 요약

STREW VISION은 CSI 웹캠으로 물체를 보고, Jetson Nano가 판단한 내용을 Arduino Mega로 보내 실제 로봇을 움직이며, AWS 서버가 작업 요청과 결과를 관리하는 시스템이다.

## 전체 구조

1. 웹 대시보드 또는 외부 프로그램이 AWS 서버에 로봇 작업을 등록한다.
2. Jetson Nano가 AWS 서버에서 자기 로봇에게 온 작업을 가져온다.
3. Jetson Nano가 CSI 웹캠(`/dev/video0` 등)으로 현재 화면을 읽는다.
4. Jetson Nano가 작업 내용과 비전 결과를 합쳐 Arduino Mega로 JSON 명령을 보낸다.
5. Arduino Mega가 모터, 그리퍼, 센서 같은 실제 장치를 제어한다.
6. Arduino Mega가 처리 결과를 Jetson Nano로 돌려준다.
7. Jetson Nano가 AWS 서버에 작업 완료 또는 실패를 보고한다.

## 구현된 폴더

- `AWS_SYSTEM`: AWS에 올릴 FastAPI 서버, 대시보드, Docker, Terraform
- `JETSON_ROBOT`: Jetson Nano 실행 프로그램, CSI 카메라 입력, Arduino 시리얼 통신
- `docs`: 전체 설명 문서
- `VISION_DATA`: 기존 학습 데이터와 비전 데이터
- `JETSON`: 기존 Jetson 관련 메모와 테스트 파일

## Notion 문서 반영 상태

현재 세션에는 Notion 원문을 직접 가져오는 도구가 연결되어 있지 않아 두 Notion 문서를 실제로 읽지는 못했다. 대신 로컬 `STREW_VISION.drawio`와 사용자가 말한 `Jetson Nano -> Arduino Mega 데이터 전송`, 그리고 CSI 웹캠 사용 조건을 기준으로 구현했다.

Notion 연결이 가능해지면 문서의 정확한 필드명, 화면 구성, 업무 흐름에 맞춰 API와 데이터 구조를 보정하면 된다.
