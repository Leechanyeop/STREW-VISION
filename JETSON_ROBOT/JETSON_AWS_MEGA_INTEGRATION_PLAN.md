# Jetson-AWS-MEGA Integration Plan

## Target Role Split

- AWS server owns the database, dashboard, approval workflow, task queue, and long-term logs.
- Jetson Nano owns the robot orchestration loop between AWS and Arduino Mega.
- Arduino Mega owns real-time motor, actuator, pump, emergency input, and low-level sensor reads.

Jetson should not become the main database. It should be the field gateway that claims AWS tasks, reads camera/AI state, sends UART commands to Mega, receives progress/status, and reports every meaningful result back to AWS.

## Recommended End-to-End Flow

1. AWS keeps active cells in `cells`.
2. AWS creates an `OBSERVE` task for a target cell, or Jetson requests/claims the next queued task.
3. Jetson receives task data with `task_id`, `cell_id`, `task_name`, `execute_task`, `move_sign`, `target_label`, and `command_payload`.
4. Jetson sends a UART JSON command to Mega.
5. Mega moves to the cell and returns `RUNNING`, `DONE`, or `FAILED` messages with progress.
6. Jetson posts progress to AWS as robot feedback/status.
7. Once positioned, Jetson captures camera/YOLO data and posts a vision or AI reading to AWS.
8. AWS writes `sensor_logs`, `ai_readings`, `approvals`, `robot_tasks`, `robot_feedback`, and `system_events`.
9. If approval is required, AWS keeps the task in `WAIT_APPROVAL`.
10. After approval, AWS changes the task to executable state and Jetson claims it.
11. Jetson sends the approved command to Mega and reports completion.

## Current Code Fit

### JETSON_ROBOT

Current files already provide a useful basic loop:

- `strew_robot/agent.py` polls AWS, reads vision once, sends one JSON command to Arduino, and posts one final response.
- `strew_robot/cloud_client.py` supports `/robot/next`, `/robot/response`, and `/vision/event`.
- `strew_robot/arduino_link.py` sends one newline-delimited JSON message and waits for one response.

Main gap: the loop is task/response oriented, not cell lifecycle oriented. It does not yet handle `cell_id`, status streaming, sensor payloads, approval wait states, retries, emergency stop, or multi-step task execution.

### AWS_SYSTEM

There are two backend shapes:

- `AWS_SYSTEM/app` is a simple FastAPI task queue with local JSON or DynamoDB.
- `AWS_SYSTEM/jetson_greenhouse_system` is closer to the database document. It has SQLite tables and endpoints for cells, sensor logs, AI readings, approvals, robot tasks, robot feedback, and vision events.

Main gap: Jetson currently targets the simple FastAPI route style by default, but the richer greenhouse backend uses `/api/...` paths and richer task fields.

## What Should Change In JETSON_ROBOT

1. Update `CloudClient` to support the greenhouse API:
   - `GET /api/robot/next?robot_id=robot-01`
   - `POST /api/robot/status`
   - `POST /api/robot/response`
   - `POST /api/vision/event`
   - optionally `POST /api/sensor` and `POST /api/ai`

2. Extend task parsing:
   - keep `id` and `task_id` compatible
   - include `cell_id`, `task_name`, `state_machine`, `control_state`, `progress_rate`, `robot_status`, and `command_payload`
   - use `command_payload` as the primary command source when present

3. Replace the one-shot Arduino exchange with a command session:
   - send command once
   - read multiple Mega status lines until `DONE` or `FAILED`
   - forward each `RUNNING` update to AWS
   - apply timeout and retry policy

4. Define a stricter UART command schema:
   - Jetson to Mega: `task_id`, `cell_id`, `execute_task`, `task_name`, `move_sign`, `target_label`, `x_center`, `y_center`, `payload`
   - Mega to Jetson: `task_id`, `completion_sign`, `progress_rate`, `robot_status`, `temperature`, `humidity`, `sap_amount_ml`, `error_code`, `message`

5. Add Jetson state handling:
   - `IDLE`
   - `CLAIM_TASK`
   - `SEND_TO_MEGA`
   - `WAIT_MEGA`
   - `CAPTURE_VISION`
   - `REPORT_RESULT`
   - `ERROR_OR_ESTOP`

6. Add local resilience:
   - cache unsent feedback locally when AWS is offline
   - resend cached events later
   - never duplicate a completed actuator command without checking task status

## What Should Change In AWS_SYSTEM

1. Choose one backend as the source of truth.
   - For the current greenhouse DB flow, use `AWS_SYSTEM/jetson_greenhouse_system`.
   - Keep `AWS_SYSTEM/app` only if you plan to deploy FastAPI/DynamoDB and migrate the full schema into it.

2. Normalize API paths for Jetson.
   - Either teach Jetson to use `/api/robot/next`, or add compatibility aliases `/robot/next`, `/robot/response`, `/vision/event` to the greenhouse backend.

3. Keep task queue semantics strict:
   - task is claimable only when `state_machine = 'EXECUTE_TASK'`
   - `control_state = 'RUN'`
   - `queue_status IN ('queued', 'sent')`
   - approval-required tasks must stay out of the claim queue until approved

4. Store every robot update:
   - `/api/robot/status` for `RUNNING`
   - `/api/robot/response` for terminal `DONE` or `FAILED`
   - both should insert into `robot_feedback`

5. Add or confirm API key protection on greenhouse endpoints before real deployment.

6. Add a clear cell cycle endpoint or scheduler:
   - create next `OBSERVE` task for cells 1 through 4
   - log `SCAN_COMPLETE` when all active cells are done
   - wait until next measurement cycle

## Preferred Next Implementation Order

1. Make Jetson compatible with `/api/robot/next` and `/api/robot/response`.
2. Add `cell_id` and `command_payload` pass-through to the Mega UART command.
3. Change Arduino serial read from single ACK to streaming status.
4. Add `/api/robot/status` posting during long movement or nutrition tasks.
5. Connect vision result to `/api/vision/event` with `cell_id`.
6. Decide where sensor values originate:
   - if Mega reads sensors, return them in UART status and Jetson posts them
   - if ESP32 posts directly, Jetson only references the latest sensor log
7. Add approval-gated nutrition execution.
8. Add offline retry cache and emergency-stop handling.

