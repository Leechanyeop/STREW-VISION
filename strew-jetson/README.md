# STREW Jetson

Jetson side robot agent for camera capture, AI detection, task decision, AWS task polling, MQTT integration, and Arduino serial commands.


## Structure 구조

```text
ai/         AI execution, inference, preprocessing, parsing  # ai 관련
camera/     CSI camera, capture, calibration, Jetson camera drivers # 카메라 관련
config/     runtime configuration and logging config # 설정 관련
decision/   task planning, rules, priority, matching, robot agent loop
detection/  detection result models, JSON event builders, validators # 감지 관련
models/     model weights and model metadata  # 모델 관련
mqtt/       MQTT client, publisher, subscriber, topics # Mqtt 관련
robot/      Arduino command, packet, protocol, serial link # 아두이노 통신 관련
task/       AWS task loader, queue, scheduler, manager # AWS 관련
utils/      shared logging, file, timer, helper utilities # 공통 유틸리티
tests/      unit tests, manual tests, archived experiment artifacts # 테스트 관련
```

## Run 실행방법

```bash
python -m main
```

or:

```bash
scripts/run_agent.sh
```
