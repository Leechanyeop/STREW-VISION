import time
import random
import threading
from typing import Any, Dict, Optional
from ai.detector.camera import create_vision_source

from cloud.api_client import CloudClient
from cloud.sync import CloudSync
from cloud.mqtt import MqttClient
from config.settings import Config
from robot.command import (
    MSG_START_CYCLE,
    MSG_REQUEST_VISION,
    MSG_VISION_RESULT,
    MSG_REPORT_RESULT,
    MSG_PROGRESS_UPDATE,
    MSG_CYCLE_COMPLETE,
    MSG_ERROR,
    MSG_RESET,
)
from robot.uart import ArduinoLink

# 참고: robot/planner.py의 ACTION_MAP(REPLACE/OBSERVE/SKIP 결정)은
# 이제 여기서 안 씀 -> 결정권이 Mega 펌웨어로 넘어갔기 때문. planner.py 자체는
# 삭제할지 테스트/시뮬레이션용으로만 남길지 아직 결정 안 됨 (task #20 후속 항목).

# Mega가 순회 중(cycle_active=True)인데 이 시간(초) 동안 UART로 아무 메시지도 안 오면
# "Mega가 응답 없이 멈췄다"고 간주하는 워치독 기준 시간. 4개 셀 순회가 정상적으로도
# 시간이 좀 걸릴 수 있어서 넉넉하게 잡음 - 실제 하드웨어 타이밍 보고 조정 필요.
MEGA_SILENCE_TIMEOUT_SEC = 120.0


# AWS가 꺼져 있을 때(cfg.aws_enabled=False) 대신 사용하는 로컬 랜덤 목업 작업.
# [2026-07-15 2차 수정] Mega가 1~4번 셀 전체 순회를 자체 관리하기로 확정되면서
# target_label(셀 지정)은 더 이상 의미가 없어짐 -> id만 남김. "task"는 이제
# "셀 하나"가 아니라 "순회 한 바퀴 전체"를 가리킨다.
def build_mock_task() -> Dict[str, Any]:
    return {
        "id": str(random.randint(1, 1000)),
    }


class RobotAgent:

    # RobotAgent 클래스는 로봇의 상태를 관리하고, AWS 클라우드와의 통신, 비전 처리, 아두이노 명령 전송 등을 담당합니다.
    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cloud = CloudClient(cfg.aws_api_base, cfg.api_key) #AWS 클라우드 API 클라이언트를 초기화합니다.
        self.vision = create_vision_source( # 카메라로 보는 도구 실제 비전인식 값
            cfg.vision_mode,
            cfg.csi_camera_index,
            cfg.frame_width,
            cfg.frame_height,
            cfg.yolo_model_path,
        )
        self.arduino = ArduinoLink(cfg.arduino_port, cfg.arduino_baudrate)
        self.mqtt_client = MqttClient()  # MQTT 클라이언트를 초기화합니다.
        self.cloud_sync = CloudSync(self.cloud)  # CloudSync 인스턴스를 초기화합니다.
        self.mqtt_client.connect(cfg.aws_mqtt_broker, cfg.aws_mqtt_topic, cfg.aws_mqtt_port)

        # 지금 Mega가 처리 중인 task (있으면). UART Listener Thread가 REPORT_RESULT를
        # 받았을 때 "이게 어느 task_id에 대한 결과인지" 알아야 AWS에 릴레이할 수 있는데,
        # 그 스레드는 run_once()처럼 task를 함수 인자로 받지 않으므로 self에 들고 있어야 함.
        self.current_task: Optional[Dict[str, Any]] = None

        # Mega가 지금 순회(RUN) 중인지 여부. True인 동안은 run_once()가 START_CYCLE을
        # 또 보내지 않는다 - Mega가 1~4번 순회 중인데 새 트리거가 겹쳐 들어가는 걸 방지.
        # CYCLE_COMPLETE를 받으면 False로 풀린다. ERROR나 워치독 타임아웃 시엔 일부러
        # False로 안 풀어서(안전 우선) 사람이 개입하기 전까지 자동으로 다음 순회를
        # 트리거하지 않는다.
        self.cycle_active: bool = False

        # 마지막으로 Mega한테서 뭔가(어떤 타입이든) 받은 시각. run_once()가 이걸 보고
        # "Mega가 순회 중이라고 하는데 너무 오래 조용하면" 무응답 정지로 간주한다
        # (ERROR 메시지를 보낼 새도 없이 그냥 멈춰버린 경우를 잡기 위함).
        self.last_uart_message_time: float = time.monotonic()

        # 최근 ERROR의 severity("minor"/"critical"). send_reset()이 이걸 보고
        # minor가 아니면 RESET을 보내지 않는다 (critical은 물리 리셋만 허용).
        self.last_error_severity: Optional[str] = None

        # UART 읽기는 이제 이 스레드 하나만 한다 (단일 소유자 — vision.read()도 이 스레드
        # 안에서만 호출됨). run_once()는 명령을 "보내기만" 하고 응답을 기다리지 않는다.
        # __init__에서 딱 한 번만 시작 (run_forever()의 while 루프 안에 넣으면 사이클마다
        # 스레드가 계속 새로 생겨버림).
        threading.Thread(target=self._uart_listener_loop, daemon=True).start()

    # close 메서드는 아두이노와 비전 소스를 닫는 역할을 합니다.
    # 아두이노와 비전 소스가 열려 있는 경우에만 닫습니다.
    def close(self) -> None:
        self.arduino.close()
        close = getattr(self.vision, "close", None)
        if close:
            close()

    # 사람이 ERROR를 확인한 뒤 "재시작해도 좋다"고 판단했을 때 호출하는 메서드.
    # (지금은 AWS 대시보드 버튼 -> 이 메서드 연결은 아직 안 돼있음 - AWS 서버 자체가
    # 없어서 그 배선은 별도 작업. 지금은 이 메서드가 존재한다는 것과 안전 규칙만 확정)
    #
    # severity가 "minor"였을 때만 RESET을 보낸다. "critical"(또는 정보 없음)이면
    # 거부한다 - 심각한 고장은 소프트웨어 재시작이 아니라 물리 리셋(전원 재시작 등)만
    # 허용해야 한다는 안전 원칙 때문. Mega 펌웨어도 critical일 때 RESET을 무시하도록
    # 만들어야 하며(이중 안전장치), 이건 Jetson 코드만으로 보장할 수 없어 Mega 개발자에게
    # 별도로 요청해둔 사항이다.
    def send_reset(self) -> bool:
        if self.last_error_severity != "minor":
            print(
                f"[!!!] RESET 거부됨 - 마지막 오류 severity={self.last_error_severity!r} "
                f"(minor가 아니면 물리 리셋만 허용됨)"
            )
            return False

        self.arduino.send_json_line({"type": MSG_RESET})
        self.cycle_active = False
        self.last_error_severity = None
        self.last_uart_message_time = time.monotonic()
        print("[RESET] Mega에 RESET 전송함 - 다음 run_once()부터 새 순회 트리거 가능")
        return True

    # run_once 메서드는 한 사이클마다 AWS에서 다음 task를 받아와 Mega한테
    # "순회 시작해"(START_CYCLE)라고만 트리거해준다. 셀 지정, REPLACE/OBSERVE/SKIP 판단,
    # 진행상황, 최종 결과 보고는 이제 전부 Mega가 결정/관리하고 비동기로 요청/보고하므로
    # run_once()는 응답을 기다리지 않는다 (기다리는 쪽은 _uart_listener_loop()).
    def run_once(self) -> None:

        if self.cycle_active:
            # 워치독: 순회 중이라고 돼있는데 너무 오래(MEGA_SILENCE_TIMEOUT_SEC) UART로
            # 아무 말도 없으면 - ERROR 메시지조차 못 보내고 조용히 멈춘 것으로 간주.
            # ERROR와 동일하게 안전 우선으로 cycle_active를 풀지 않고 AWS에 알리기만 한다.
            silence = time.monotonic() - self.last_uart_message_time
            if silence > MEGA_SILENCE_TIMEOUT_SEC:
                print(f"[!!!] Mega 무응답 {silence:.0f}초 - 응답 없이 멈춘 것으로 간주")
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.try_send(
                        self.cloud.post_response,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        execute_task="ERROR",
                        completion_sign="TIMEOUT",
                        message=f"Mega silent for {silence:.0f}s - assumed hung/stopped",
                        payload={},
                    )
                self.last_error_severity = "critical"  # 원인 불명 -> 안전하게 물리 확인 필요로 취급
            return

        if self.cfg.aws_enabled:
            task = self.cloud.next_task(self.cfg.robot_id)
            if not task:
                return
        else:
            task = build_mock_task()

        # _uart_listener_loop()가 나중에 REPORT_RESULT/CYCLE_COMPLETE를 받았을 때
        # 이 task_id로 AWS에 릴레이할 수 있도록 기억해둔다.
        self.current_task = task
        self.cycle_active = True
        self.last_uart_message_time = time.monotonic()

        self.arduino.send_json_line({"type": MSG_START_CYCLE})

        if not self.cfg.aws_enabled:
            print(
                f"[AWS disabled] task={task['id']} 순회 시작 트리거(START_CYCLE) 전송함 "
                f"(셀 지정 없음 - 1~4번 전체를 Mega가 자체 관리, 결과는 _uart_listener_loop에서 수신)"
            )

    # run_forever 메서드는 무한 루프를 돌며 run_once를 반복 실행합니다.
    # (UART Listener Thread는 __init__에서 이미 한 번 시작했으므로 여기서는 신경 안 써도 됨.)
    def run_forever(self) -> None:
        try:
            while True:
                self.run_once()
                time.sleep(self.cfg.poll_interval_sec)
        finally:
            self.close()

    # Mega가 먼저 말 걸어오는 메시지를 계속 듣는 루프.
    # UART 읽기와 vision.read()를 전부 이 스레드 한 곳에서만 처리한다 (단일 소유자) ->
    # 다른 스레드와 시리얼 포트/TensorRT를 동시에 건드릴 일이 원천적으로 없어짐.
    def _uart_listener_loop(self) -> None:
        while True:
            msg = self.arduino._read_json_line()

            if msg is None:
                continue  # 타임아웃/빈 줄 - 그냥 계속 듣는다

            # Mega한테서 뭐라도 왔다는 것 자체가 "살아있다"는 신호이므로,
            # 메시지 종류와 무관하게 무응답 워치독 기준 시각을 갱신한다.
            self.last_uart_message_time = time.monotonic()

            msg_type = msg.get("type")

            if msg_type == MSG_REQUEST_VISION:
                vision = self.vision.read().to_payload()
                self.arduino.send_json_line({
                    "type": MSG_VISION_RESULT,
                    "status": vision.get("status"),
                })
                if self.cfg.aws_enabled:
                    self.cloud_sync.try_send(self.cloud.post_vision_event, self.cfg.robot_id, vision)

            elif msg_type == MSG_PROGRESS_UPDATE:
                # Mega가 순회 도중 "지금 몇 번 셀에서 무슨 상태인지"를 알려주는 정보성 메시지.
                # 응답은 필요 없고, Jetson은 이걸 그대로 AWS에 중계만 한다(post_progress).
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.try_send(
                        self.cloud.post_progress,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        target=msg.get("target"),
                        state=msg.get("state"),
                        progress=msg.get("progress", 0),
                    )
                elif not self.cfg.aws_enabled:
                    print(f"[AWS disabled] Mega progress: {msg}")

            elif msg_type == MSG_REPORT_RESULT:
                # 셀 하나(target) 처리 결과. 한 순회(1~4번)당 최대 4번 올 수 있다.
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.flush_queue()
                    self.cloud_sync.try_send(
                        self.cloud.post_response,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        execute_task=msg.get("execute_task"),
                        completion_sign=msg.get("completion"),
                        message="Mega reported cell result",
                        payload={"mega_report": msg},
                    )
                elif not self.cfg.aws_enabled:
                    print(f"[AWS disabled] Mega cell report: {msg}")
                # 주의: 여기서는 current_task/cycle_active를 안 지운다 -
                # 아직 순회 중(다른 셀도 남아있을 수 있음)이라 CYCLE_COMPLETE가 와야 끝난 것.

            elif msg_type == MSG_CYCLE_COMPLETE:
                # 1~4번 전체 순회가 끝나고 Mega가 초기 위치로 복귀해 IDLE로 전환했다는 신호.
                # 이 신호를 받아야 다음 run_once()가 새 순회를 트리거할 수 있다.
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.try_send(
                        self.cloud.post_response,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        execute_task="CYCLE",
                        completion_sign="CYCLE_COMPLETE",
                        message="Mega completed full cycle",
                        payload={"mega_report": msg},
                    )
                elif not self.cfg.aws_enabled:
                    print(f"[AWS disabled] Mega cycle complete: {msg}")
                self.current_task = None
                self.cycle_active = False
                self.last_error_severity = None

            elif msg_type == MSG_ERROR:
                # Mega 내부 문제로 비상 정지된 상태. 안전을 위해 cycle_active를 일부러
                # False로 풀지 않는다 - 사람이 확인하고(필요하면 send_reset() 호출)
                # 재시작하기 전까지 run_once()가 자동으로 새 순회를 트리거하지 않게 막아두는 것.
                severity = msg.get("severity", "critical")  # 없으면 안전하게 critical로 간주
                self.last_error_severity = severity
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.try_send(
                        self.cloud.post_response,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        execute_task="ERROR",
                        completion_sign="ERROR",
                        message=str(msg.get("reason", "Mega reported internal error")),
                        payload={"mega_error": msg, "severity": severity},
                    )
                else:
                    print(f"[!!!] Mega ERROR (severity={severity}): {msg}")
