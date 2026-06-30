# AWS_SYSTEM 설명

## 핵심 파일

- `AWS_SYSTEM/app/main.py`: API 서버의 입구다. 작업 생성, 작업 가져오기, 응답 저장, 비전 이벤트 저장 기능이 있다.
- `AWS_SYSTEM/app/schemas.py`: 서버가 주고받는 데이터 모양을 정한다.
- `AWS_SYSTEM/app/repository.py`: 데이터를 저장한다. 로컬에서는 JSON 파일, AWS에서는 DynamoDB를 사용한다.
- `AWS_SYSTEM/app/static/index.html`: 작업을 넣고 확인하는 간단한 웹 대시보드다.
- `AWS_SYSTEM/Dockerfile`: AWS ECS에 올릴 서버 이미지를 만든다.
- `AWS_SYSTEM/terraform/main.tf`: VPC, 로드밸런서, ECS Fargate, DynamoDB를 만든다.

## 로컬 실행

```powershell
cd "J:\#PROJECT\# STREW_VISION\AWS_SYSTEM"
copy .env.example .env
powershell -ExecutionPolicy Bypass -File .\scripts\run_local.ps1
```

실행 후 `http://localhost:8000`을 열면 대시보드가 나온다.

## AWS 배포 순서

1. AWS CLI, Docker, Terraform을 설치한다.
2. AWS ECR 저장소 `strew-robot-api`를 만든다.
3. `scripts/build_and_push_ecr.ps1`로 Docker 이미지를 ECR에 올린다.
4. `terraform init` 후 `terraform apply`를 실행한다.
5. 출력된 `api_url`을 Jetson Nano `.env`의 `AWS_API_BASE`에 넣는다.

## API 목록

- `GET /health`: 서버 상태 확인
- `POST /robot/request`: 새 로봇 작업 생성
- `GET /robot/next`: Jetson Nano가 다음 작업을 가져감
- `POST /robot/response`: Jetson Nano가 작업 결과를 보고
- `POST /vision/event`: Jetson Nano가 CSI 웹캠 비전 결과를 저장
- `GET /robot/tasks`: 작업 목록 조회
- `GET /robot/responses`: 응답 목록 조회
