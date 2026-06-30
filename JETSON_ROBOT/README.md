# STREW Jetson

Jetson side robot agent for camera capture, AI detection, task decision, AWS task polling, MQTT integration, and Arduino serial commands.

## Structure

```text
ai/         AI execution, inference, preprocessing, parsing
camera/     CSI camera, capture, calibration, Jetson camera drivers
config/     runtime configuration and logging config
decision/   task planning, rules, priority, matching, robot agent loop
detection/  detection result models, JSON event builders, validators
models/     model weights and model metadata
mqtt/       MQTT client, publisher, subscriber, topics
robot/      Arduino command, packet, protocol, serial link
task/       AWS task loader, queue, scheduler, manager
utils/      shared logging, file, timer, helper utilities
tests/      unit tests, manual tests, archived experiment artifacts
```

## Run

```bash
python -m main
```

or:

```bash
scripts/run_agent.sh
```
