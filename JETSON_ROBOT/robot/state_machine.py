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
)
from robot.uart import ArduinoLink

# 참고: robot/planner.py의 ACTION_MAP(REPLACE/OBSERVE/SKIP 결정)은
# 이제 여기서 안 씀 -> 결정권이 Mega 펌웨어로 넘어갔기 때문. planner.py 자체는
# 삭제할지 테스트/시뮬레이션용으로만 남길지 아직 결정 안 됨 (task #20 후속 항목).

# Mega가 순회 중(cycle_active=True)인데 이 시간(초) 동안 UART로 아무 메시지도 안 오면
# "Mega가 응답 없이 멈췄다"고 간주하는 워치독 기준 시간. 4개 셀 순회가 정상적으로도
# 시간이 좀 걸릴 수 있어서 넉넉하게 잡음 - 실제 하드웨어 타이밍 보고 조정 필요.
MEGA_SILENCE_TIMEOUT_SEC = 120.0

# [2026-07-16 추가] 병해충 감시 도중 이 상태로 판독되면 즉시 VISION_RESULT를 회신하지
# 않고, AWS에 판단 요청을 만들어 관리자 응답을 기다린다. 나중에 다른 병징 라벨이
# 추가되면 여기에만 더하면 됨 - 판정 로직 자체를 여러 곳에서 안 고쳐도 되게.
DISEASE_SUSPECT_STATUSES = {"powdery_mildew"}

# 관리자 판단 대기 중 "아직 응답 안 왔나?"를 AWS에 물어보는 간격(초).
DECISION_POLL_INTERVAL_SEC = 5.0


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
        #
        # [2026-07-15 4차 수정 → 5차 수정에서 단순화] 처음엔 ERROR에 severity(minor/
        # critical)를 붙여서 minor일 때만 소프트웨어 RESET으로 cycle_active를 풀어주는
        # 경로를 만들었었다. 그런데 실제로는 센서(전류/엔코더/리밋스위치 등)가 하나도
        # 없어서, 물리적 문제(그리퍼 걸림/모터 이상 등)인지 그냥 느린 건지 소프트웨어가
        # 구분할 방법이 없다는 게 명확해짐 - 구분 못 하는 걸 억지로 구분하는 척 하는 것
        # 자체가 위험. 그래서 severity 구분과 RESET 메시지를 통째로 제거하고, ERROR는
        # 항상 "사람이 물리적으로 확인하고 전원을 재시작해야 하는 상태"로 단순화했다.
        # cycle_active는 ERROR/워치독 타임아웃 이후 사람이 직접 재시작(전원 재시작 등)
        # 하기 전까지 계속 True로 남아있는다.
        self.cycle_active: bool = False

        # 마지막으로 Mega한테서 뭔가(어떤 타입이든) 받은 시각. run_once()가 이걸 보고
        # "Mega가 순회 중이라고 하는데 너무 오래 조용하면" 무응답 정지로 간주한다
        # (ERROR 메시지를 보낼 새도 없이 그냥 멈춰버린 경우를 잡기 위함).
        self.last_uart_message_time: float = time.monotonic()

        # [2026-07-16 추가] 병해충 의심 판독 때문에 관리자 응답을 기다리는 중인지 여부.
        # True인 동안은 run_once()의 무응답 워치독을 꺼야 한다 - Mega가 멈춘 게 아니라
        # Jetson이 일부러 VISION_RESULT 답장을 늦추고 있는 것뿐이라서, 이걸 무응답으로
        # 오판하면 관리자가 아직 판단 중인데도 TIMEOUT/ERROR가 나가버린다.
        self.awaiting_decision: bool = False

        # UART 읽기는 이제 이 스레드 하나만 한다 (단일 소유자 — vision.read()도 이 스레드
        # 안에서만 호출됨). run_once()는 명령을 "보내기만" 하고 응답을 기다리지 않는다.
        # __init__에서 딱 한 번만 시작 (run_forever()의 while 루프 안에 넣으면 사이클마다
        # 스레드가 계속 새로 생겨버린다).
        threading.Thread(target=self._uart_listener_loop, daemon=True).start()

    # close 메서드는 아두이노와 비전 소스를 닫는 역할을 합니다.
    # 아두이노와 비전 소스가 열려 있는 경우에만 닫습니다.
    def close(self) -> None:
        self.arduino.close()
        close = getattr(self.vision, "close", None)
        if close:
            close()

    # run_once 메서드는 한 사이클마다 AWS에서 다음 task를 받아와 Mega한테
    # "순회 시작해"(START_CYCLE)라고만 트리거해준다. 셀 지정, REPLACE/OBSERVE/SKIP 판단,
    # 진행상황, 최종 결과 보고는 이제 전부 Mega가 결정/관리하고 비동기로 요청/보고하므로
    # run_once()는 응답을 기다리지 않는다 (기다리는 쪽은 _uart_listener_loop()).
    def run_once(self) -> None:

        if self.cycle_active:
            # [2026-07-16 추가] 관리자 판단 대기 중이면 워치독 자체를 건너뛴다. Mega가
            # 멈춘 게 아니라 Jetson이 REQUEST_VISION 응답을 일부러 늦추고 있는 정상
            # 상황이라, 이 시간 동안 UART가 조용한 건 무응답 정지의 증거가 아니다.
            if self.awaiting_decision:
                return

            # 워치독: 순회 중이라고 돼있는데 너무 오래(MEGA_SILENCE_TIMEOUT_SEC) UART로
            # 아무 말도 없으면 - ERROR 메시지조차 못 보내고 조용히 멈춘 것으로 간주.
            # ERROR와 동일하게 안전 우선으로 cycle_active를 풀지 않고 AWS에 알리기만 한다.
            # (사람이 물리적으로 확인 후 전원 재시작해야 다음 run_once()가 다시 순회를 건다 -
            # 이 프로젝트엔 물리 센서가 없어서 소프트웨어가 "괜찮아 보이니 자동 재시작"을
            # 스스로 판단할 근거 자체가 없다.)
            silence = time.monotonic() - self.last_uart_message_time
            if silence > MEGA_SILENCE_TIMEOUT_SEC:
                print(f"[!!!] Mega 무응답 {silence:.0f}초 - 응답 없이 멈춘 것으로 간주. 물리 확인 필요.")
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

    # [2026-07-16 추가] 병해충 의심 판독이 나왔을 때 호출된다. AWS에 판단 요청을 만들고
    # 관리자가 treat(병징 확정)/ignore(오탐) 응답할 때까지 폴링하며 기다린 뒤, 그 결정에
    # 따른 최종 status를 반환한다.
    #   - treat: 원래 판독값 그대로 반환 -> Mega가 기존 REPLACE 등 처리를 그대로 진행
    #   - ignore: "healthy"로 덮어써서 반환 -> Mega가 오탐으로 보고 그냥 다음 셀로 넘어감
    # 응답 대기 시간엔 상한을 두지 않는다(관리자가 답할 때까지) - 이 시간 동안
    # run_once()의 워치독은 self.awaiting_decision 플래그로 꺼둔다(위 참고).
    # 안전장치: 애초에 vision_event_id가 없거나(이벤트 기록 실패) 판단 요청 생성 자체가
    # 실패하면, 관리자에게 물어볼 방법이 없다는 뜻이므로 무한정 기다리지 않고 원래
    # 판독값 그대로 반환한다 - 이 경우 로그를 크게 남겨서 나중에 확인 가능하게 한다.
    def _await_admin_decision(self, status: str, vision_event_id: Optional[str]) -> str:
        if vision_event_id is None:
            print(f"[!!!] vision 이벤트 기록 실패로 판단 요청 불가 - 원래 판독값({status})으로 진행")
            return status

        try:
            req = self.cloud.create_decision_request(self.cfg.robot_id, vision_event_id, status)
        except Exception as e:
            print(f"[!!!] 판단 요청 생성 실패 - 관리자 개입 없이 원래 판독값({status})으로 진행: {e}")
            return status

        request_id = req.get("id")
        self.awaiting_decision = True
        print(f"[대기] 병해충 의심({status}) 판단 요청 생성됨(id={request_id}) - 관리자 응답 대기 중...")

        # [2026-07-16 추가] 관리자가 화면으로 직접 보고 판단할 수 있게, 가능하면 여기서
        # WebRTC 라이브 스트림도 같이 띄운다. vision 소스가 mock이거나(get_shared_camera
        # 없음) 스트림 시작 자체가 실패해도(예: aiortc 미설치, 카메라 문제) 판단 대기
        # 자체는 막지 않는다 - 라이브 영상은 "있으면 좋은" 보조 수단이지, 이게 없다고
        # 관리자가 판단을 못 내리는 건 아니기 때문(요청 내용만으로도 판단 가능).
        publisher = None
        get_shared_camera = getattr(self.vision, "get_shared_camera", None)
        if get_shared_camera is not None:
            try:
                from robot.webrtc_publisher import DiseaseStreamPublisher

                publisher = DiseaseStreamPublisher(self.cloud, get_shared_camera(), self.cfg.robot_id)
                publisher.start(request_id)
                print("[스트림] 관리자용 라이브 영상 세션 시작 시도됨")
            except Exception as e:
                print(f"[!] WebRTC 스트림 시작 실패(무시하고 판단 대기는 계속): {e}")
                publisher = None

        try:
            while True:
                time.sleep(DECISION_POLL_INTERVAL_SEC)
                try:
                    resolved = self.cloud.get_decision_request(request_id)
                except Exception as e:
                    print(f"[!] 판단 요청 조회 실패, 재시도: {e}")
                    continue
                if resolved and resolved.get("status") != "pending":
                    decision = resolved.get("status")
                    print(f"[재개] 관리자 판단 수신: {decision}")
                    return status if decision == "resolved_treat" else "healthy"
        finally:
            self.awaiting_decision = False
            if publisher is not None:
                try:
                    publisher.stop()
                except Exception as e:
                    print(f"[!] 스트림 종료 중 오류(무시): {e}")

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
                status = vision.get("status")

                # [2026-07-16 변경] vision 이벤트를 먼저 (필요하면) 직접 기록해서 id를
                # 확보한다. 예전처럼 cloud_sync.try_send로 감싸면 실패시 큐에만 쌓이고
                # id를 못 받아오는데, 병해충 의심 케이스에서는 그 id로 판단 요청을 만들어야
                # 해서 여기서는 직접 호출한다(실패해도 무시하고 계속 진행 - 기록 실패가
                # 로봇 동작 자체를 막으면 안 됨).
                vision_event_id = None
                if self.cfg.aws_enabled:
                    try:
                        event = self.cloud.post_vision_event(self.cfg.robot_id, vision)
                        vision_event_id = event.get("id")
                    except Exception as e:
                        print(f"[!] vision 이벤트 기록 실패(무시하고 계속 진행): {e}")

                # [2026-07-16 추가] 병해충 의심 판독이면, 즉시 회신하지 않고 관리자
                # 판단을 기다린다. AWS가 꺼져 있거나 방금 이벤트 기록 자체가 실패했으면
                # (vision_event_id 없음) 관리자한테 물어볼 방법이 없으므로 원래
                # 판독값 그대로 진행한다.
                if self.cfg.aws_enabled and status in DISEASE_SUSPECT_STATUSES:
                    status = self._await_admin_decision(status, vision_event_id)

                self.arduino.send_json_line({
                    "type": MSG_VISION_RESULT,
                    "status": status,
                })

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

            elif msg_type == MSG_ERROR:
                # Mega 내부 문제로 비상 정지된 상태.
                # [2026-07-15 5차 수정] severity 구분/RESET 원격 복구 경로를 제거함 - 물리
                # 센서가 없어서 "가벼운 문제"인지 소프트웨어가 확인할 방법이 없기 때문.
                # 이제 ERROR는 항상 "사람이 직접 확인하고 전원을 재시작해야 하는 상태"로
                # 취급한다. cycle_active를 일부러 False로 풀지 않아서, 사람이 물리적으로
                # 확인하고 재시작하기 전까지 run_once()가 자동으로 새 순회를 트리거하지 않는다.
                if self.cfg.aws_enabled and self.current_task is not None:
                    self.cloud_sync.try_send(
                        self.cloud.post_response,
                        robot_id=self.cfg.robot_id,
                        task_id=self.current_task["id"],
                        execute_task="ERROR",
                        completion_sign="ERROR",
                        message=str(msg.get("reason", "Mega reported internal error")),
                        payload={"mega_error": msg},
                    )
                else:
                    print(f"[!!!] Mega ERROR: {msg}")
