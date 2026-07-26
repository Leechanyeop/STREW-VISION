Part I. Foundation
Volume 01. Project Overview

프로젝트 개요 및 개발 목적

프로젝트 소개
개발 배경
스마트팜의 문제점
기존 시스템 분석
개발 목표
프로젝트 범위
전체 시스템 개요
기대 효과

약 15페이지

Volume 02. System Architecture Design Specification

전체 시스템 설계

Edge AI Architecture
Master / Slave 구조
Jetson
Mega
SQLite
MQTT
AWS
Dashboard
전체 데이터 흐름
계층 구조

약 20페이지

Part II. Platform Design
Volume 03. Arduino Mega Firmware Design
Motion Controller
State Machine
Inspection Manager
Inspection Workflow
Inspection Strategy
Replace Manager
UART Manager
Firmware Integration

약 25페이지

Volume 04. Jetson Nano Software Design
Jetson Software Architecture
Software Structure
Program Entry Point (main.py)
Application Core (RobotAgent)
System Initialization
Runtime Architecture
Event Processing
Vision Processing
Robot Communication Module
Storage Module
Cloud Module
Updater Module
Scripts
Configuration
Legacy & Future Compatibility

약 25페이지

Volume 05. AWS Server & Dashboard Design
Cloud Architecture
FastAPI Server
REST API
DynamoDB
Dashboard
MQTT Service
WebRTC Streaming
OTA Server
Security
Deployment
Configuration

약 25페이지

Part III. Functional Design
Volume 06. UART Communication Protocol
UART 개념
Packet Format
Command Structure
ACK / COMPLETE / ERROR
Heartbeat
Timeout

약 15페이지

Volume 07. Inspection System
Inspection 개념
Inspection Workflow
Inspection Strategy
Multi View
Confidence
Decision Process

약 15페이지

Volume 08. Vision System
Vision Pipeline
Camera Processing
Image Processing
Detection Flow
Result Processing

약 15페이지

Volume 09. AI Detection System
YOLO
Disease Detection
Healthy Detection
Confidence
Dataset
AI Pipeline

약 15페이지

Volume 10. Replace System
Replace Workflow
Replace Sequence
Safety
Approval Process

약 15페이지

Volume 11. MQTT Communication
MQTT Architecture
Broker
Topic
Publish
Subscribe
QoS
Message Flow

약 15페이지

Volume 12. Dashboard User Guide
Dashboard UI
Robot Monitoring
Vision Monitoring
Alarm
Administrator Approval
Error Log

약 15페이지

Volume 13. Robot Scheduler
Scheduler
Inspection Schedule
Maintenance Schedule
Daily Operation

약 15페이지

Volume 14. Daily Analysis System
Statistics
Confidence Analysis
Error Analysis
Report Generation

약 15페이지

Volume 15. Recovery System
Recovery Workflow
Resume
Fault Recovery
State Recovery

약 15페이지

Volume 16. Monitoring System
Mega Monitoring
Jetson Monitoring
AWS Monitoring
MQTT Monitoring
Network Monitoring

약 15페이지

Volume 17. Robot Configuration
Confidence Threshold
Operation Schedule
Inspection Configuration
Runtime Parameter

약 15페이지

Volume 18. Database & API Specification
REST API
SQLite Reference
DynamoDB Reference
MQTT Topic
UART Packet
JSON Format

약 20페이지

Volume 19. Failure & Safety Design
Failure Classification
Servo Failure
Camera Failure
Network Failure
Emergency Stop
Safety Policy

약 20페이지

Volume 20. Deployment & Operation Manual
Installation
Initial Setup
Calibration
Dashboard Operation
Maintenance
Update
Troublesbleshooting

약 25페이지