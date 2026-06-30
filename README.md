<div align="center">

<img src="docs/images/logo.png" width="320"/>

# STREW VISION

### Physical AI Smart Agriculture Platform

<img width="100" height="100" alt="STREW_VISION" src="https://github.com/user-attachments/assets/9cd002d5-9056-4a8d-899e-42c89168d362" />

### Organic Tech Fusion

**Jetson Nano · YOLOv5 · OpenCV · FastAPI · AWS · MQTT · Arduino Mega2560**

![Python](https://img.shields.io/badge/Python-3.11-blue)
![YOLOv5](https://img.shields.io/badge/YOLOv5-v7.0-green)
![Jetson](https://img.shields.io/badge/NVIDIA-Jetson%20Nano-76B900)
![FastAPI](https://img.shields.io/badge/FastAPI-009688)
![MQTT](https://img.shields.io/badge/MQTT-E66000)
![AWS](https://img.shields.io/badge/AWS-Cloud-orange)

---

### AI Vision meets Agricultural Robotics

An integrated Physical AI platform that combines computer vision,
robotics, and cloud technologies to automate strawberry cultivation.

</div>

---

# Overview

STREW VISION is a Physical AI platform designed for intelligent strawberry cultivation.

The system combines

- AI Vision
- Robot Automation
- Cloud Computing
- Smart Monitoring

into a single autonomous platform capable of detecting plant diseases,
identifying plants using QR technology, executing robotic tasks, and
managing the entire cultivation process remotely.

---

# Key Features

- AI-based Disease Detection
- Strawberry & Pot Detection
- QR Plant Identification
- Autonomous Robot Arm Control
- Real-time Dashboard
- Cloud Task Management
- MQTT Device Communication
- Automated Task Scheduling
- Centralized Database Logging

---

# System Architecture

```
                      Dashboard

                          │

                          ▼

                  FastAPI Backend

                          │

                    AWS Cloud

                          │

                  MQTT / REST API

                          │

                    Jetson Nano

          ┌───────────────┴───────────────┐

          ▼                               ▼

      YOLOv5 AI                     QR Recognition

          ▼                               ▼

             AI Decision Engine

                     │

                     ▼

              Arduino Mega2560

                     │

                     ▼

          DFRobot IO Expansion Shield

                     │

                     ▼

               Robot Arm Controller

                     │

                     ▼

             Linear Rail System

                     │

                     ▼

             Strawberry Cultivation
```

---

# Hardware Configuration

<img width="1690" height="710" alt="KakaoTalk_20260607_213808454" src="https://github.com/user-attachments/assets/5019faa7-c6dc-4211-b3bd-b61e627fc02f" />

<img width="1102" height="1198" alt="KakaoTalk_20260607_185320921" src="https://github.com/user-attachments/assets/840dd259-3c2b-46b2-b920-e9fa4743e798" />

```
Linear Rail

↓

6DOF Robot Arm

↓

End Effector

↓

IMX708 Camera

↓

Jetson Nano

↓

Arduino Mega2560

↓

DFRobot IO Shield

↓

Servo Motors

↓

Photo Sensors
```

---

# AI Pipeline

```
Camera

↓

Image Acquisition

↓

YOLOv5 Detection

↓

Disease Classification

↓

QR Recognition

↓

Task Decision

↓

Robot Motion Planning

↓

Robot Execution

↓

Cloud Synchronization

↓

Dashboard Update
```

---

# Software Architecture

```
Dashboard

↓

Backend API

↓

MQTT Broker

↓

Jetson Runtime

↓

Vision Engine

↓

Decision Engine

↓

Robot Controller

↓

Database
```

---

# Repository Structure

```
STREW-VISION
│
├── docs/
│   ├── architecture/
│   ├── database/
│   ├── interface/
│   ├── reports/
│   └── images/
│
├── strew-backend/
│
├── strew-dashboard/
│
├── strew-arduino/
│
├── strew-hardware/
│
├── JETSON_ROBOT/
│   ├── ai/
│   ├── detector/
│   ├── segmentation/
│   ├── qr/
│   ├── robot/
│   ├── mqtt/
│   ├── cloud/
│   ├── models/
│   └── scripts/
│
└── tools/
```

---

# Technology Stack

| Category | Technology |
|------------|-------------------------------|
| AI | YOLOv5 |
| Vision | OpenCV |
| Backend | FastAPI |
| Dashboard | Streamlit |
| Cloud | AWS EC2 |
| Database | DynamoDB |
| Embedded | Arduino Mega2560 |
| SBC | NVIDIA Jetson Nano |
| Communication | MQTT / Serial |
| Language | Python / C++ / Arduino |

---

# Project Workflow

```
Task Creation

↓

Cloud Server

↓

Jetson Nano

↓

AI Detection

↓

Decision Engine

↓

Robot Task

↓

Robot Feedback

↓

Database

↓

Dashboard
```

---

# Directory Modules

| Module | Description |
|----------|------------------------------|
| docs | Project Documentation |
| JETSON_ROBOT | AI Runtime & Robot Control |
| strew-backend | FastAPI Backend |
| strew-dashboard | Monitoring Dashboard |
| strew-arduino | Robot Firmware |
| strew-hardware | CAD & Hardware |
| tools | Dataset & Utilities |

---

# Development Roadmap

- [x] Hardware Design
- [x] System Architecture
- [x] Database Design
- [x] Robot CAD Design
- [x] Jetson Runtime
- [ ] Robot Integration
- [ ] AI Optimization
- [ ] Dashboard Completion
- [ ] Field Test
- [ ] Final Deployment

---

# Team

| Name | Role |
|----------|----------------------------|
| 이찬엽 | System Integration / Jetson / AWS |
| 한도경 | AI Vision |
| 김재신 | Robot Control |
| 차서현 | Hardware Design |
| 서채연 | Documentation |

---

# License

This project is developed for the 2026 Hanium DreamUp Smart Agriculture Project.

© 2026 STREW VISION Team



