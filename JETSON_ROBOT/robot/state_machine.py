import time
import threading
from typing import Any, Dict, Optional
from ai.detector.camera import create_vision_source

from cloud.api_client import CloudClient
from cloud.sync import CloudSync
from cloud.mqtt import MqttClient
from cloud.sensor_bridge import SensorBridge
from config.settings import Config
from robot.command import (
    CMD_RUN,
    CMD_ACK,
    CMD_TASK,
    CMD_PING,
    EV_READY,
    EV_STATE,
    EV_COMPLETE,
    EV_ERROR,
    EV_PONG,
    STATE_VISION_READY,
    status_to_task,
)
from robot.uart import ArduinoLink

# [2026-07-21 UART Protocol v1.0]
# 하트비트: Jetson이 PING을 1초 주기로 보내고 Mega는 즉시 PONG. 이 시간(초) 넘게
# PONG이 없으면 Mega Offline로 판정한다(스펙: 3회 무응답 = Offline).
HEARTBEAT_INTERVAL_SEC = 1.0
HEARTBEAT_TIMEOUT_SEC = 3.0

# 병해충 의심 판독. 즉시 TASK를 내리지 않고 AWS에 판단 요청 후 관리자 응답을 기다린다.
DISEASE_SUSPECT_STATUSES = {"powdery_mildew"}

# 관리자 판단 대기 중 폴링 간격(초).
DECISION_POLL_INTERVAL_SEC = 5.0


def build_mock_cycle_id() -> str:
    # AWS 미연동(개발/시뮬)일 때 cycle_id 대용. 실제로는 AWS task id를 쓴다.
    return f"mock-{int(time.time())}"


class RobotAgent:
    """Jetson(Master) 측 UART Protocol v1.0 구현.

    역할: AI(vision) 수행, DB(AWS) 저장, 관리자 승인 처리, UART 관리, 하트비트.
    모터/물리 동작은 전혀 안 한다(그건 Mega). Jetson은 명령(cmd)을 주고 상태(event)를 받는다.
    """

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self.cloud = CloudClient(cfg.aws_api_base, cfg.api_key)
        self.vision = create_vision_source(
            cfg.vision_mode, cfg.csi_camera_index, cfg.frame_width, cfg.frame_height, cfg.yolo_model_path,
        )
        self.arduino = ArduinoLink(cfg.arduino_port, cfg.arduino_baudrate)
        self.mqtt_client = MqttClient()
        self.cloud_sync = CloudSync(self.cloud)

        # ESP32 센서 브리지 (기본 비활성 - 서버가 직접 MQTT 구독하는 방식이 기본).
        self.sensor_bridge = (
            SensorBridge(self.cloud, cfg.robot_id, cfg.sensor_forward_interval_sec)
            if cfg.aws_enabled and cfg.mqtt_sensor_topic else None
        )
        if self.sensor_bridge is not None:
            self.mqtt_client.on_sensor = self.sensor_bridge.handle_payload

        # [2026-07-23] OTA 원격 자동 업데이트 서비스 - update 토픽 구독 + UpdateManager 연결.
        self.ota_service = None
        if getattr(cfg, "ota_enabled", False):
            try:
                from updater.ota_service import OtaService

                self.ota_service = OtaService(cfg, self.mqtt_client, self.cloud, arduino_link=self.arduino)
            except Exception as e:
                print(f"[OTA] 초기화 실패(무시하고 계속): {e}")

        self.mqtt_client.connect(
            cfg.aws_mqtt_broker, cfg.aws_mqtt_topic, cfg.aws_mqtt_port,
            sensor_topic=cfg.mqtt_sensor_topic if self.sensor_bridge is not None else None,
            update_topic=cfg.ota_update_topic if self.ota_service is not None else None,
        )

        # 현재 진행 중인 Cycle의 AWS task (COMPLETE/ERROR를 이 task_id로 릴레이).
        self.current_task: Optional[Dict[str, Any]] = None
        self.cycle_active: bool = False

        # 관리자 판단 대기 중 여부. 이 동안은 하트비트 오프라인 판정을 유예한다 -
        # 리스너 스레드가 판단 폴링으로 블로킹돼서 PONG을 못 읽는 것뿐이지 Mega가 죽은
        # 게 아니기 때문.
        self.awaiting_decision: bool = False

        # 하트비트 상태.
        self.last_pong_time: float = time.monotonic()
        self.mega_online: bool = True
        self._offline_reported: bool = False

        # UART 읽기는 리스너 스레드 하나만 한다(단일 소유자). 쓰기는 write_lock으로 보호됨.
        self._listener = threading.Thread(target=self._uart_listener_loop, daemon=True)
        self._heartbeat = threading.Thread(target=self._heartbeat_loop, daemon=True)
        self._listener.start()
        self._heartbeat.start()

    # ---------------------------------------------------------------------
    # 하트비트: 1초마다 PING, HEARTBEAT_TIMEOUT_SEC 넘게 PONG 없으면 Offline.
    # ---------------------------------------------------------------------
    def _heartbeat_loop(self) -> None:
        while True:
            time.sleep(HEARTBEAT_INTERVAL_SEC)
            self.arduino.send_json_line({"cmd": CMD_PING})

            if self.awaiting_decision:
                continue  # 판단 대기 중엔 오프라인 판정 유예

            silence = time.monotonic() - self.last_pong_time
            if silence > HEARTBEAT_TIMEOUT_SEC:
                if not self._offline_reported:
                    self.mega_online = False
                    self._offline_reported = True
                    print(f"[!!!] Mega Offline - PONG {silence:.0f}초간 없음 (연결/전원 확인 필요)")
                    if self.cfg.aws_enabled and self.current_task is not None:
                        self.cloud_sync.try_send(
                            self.cloud.post_response,
                            robot_id=self.cfg.robot_id,
                            task_id=self.current_task["id"],
                            execute_task="ERROR",
                            completion_sign="ERROR",
                            message="Mega heartbeat timeout (offline)",
                            payload={"reason": "heartbeat_timeout"},
                        )
            else:
                if self._offline_reported:
                    print("[복구] Mega 하트비트 재개 - 다시 Online")
                self.mega_online = True
                self._offline_reported = False

    # ---------------------------------------------------------------------
    # 수신 이벤트 처리 루프.
    # ---------------------------------------------------------------------
    def _uart_listener_loop(self) -> None:
        while True:
            msg = self.arduino._read_json_line()
            if msg is None:
                continue

            event = msg.get("event")
            if event == EV_PONG:
                self.last_pong_time = time.monotonic()
                continue
            if event == EV_READY:
                self._on_ready()
            elif event == EV_STATE:
                self._on_state(msg)
            elif event == EV_COMPLETE:
                self._on_complete(msg)
            elif event == EV_ERROR:
                self._on_error(msg)
            # 알 수 없는 event는 무시.

    # READY: Mega 부팅/리셋 완료. task를 확보해 RUN을 내린다.
    def _on_ready(self) -> None:
        self.last_pong_time = time.monotonic()  # READY도 살아있음의 신호
        print("[READY] Mega 부팅 완료 - Cycle 준비")
        if self.cfg.aws_enabled:
            task = self.cloud.next_task(self.cfg.robot_id)
            if not task:
                print("[READY] 대기 중인 작업 없음 - RUN 보류")
                return
        else:
            task = {"id": build_mock_cycle_id()}

        self.current_task = task
        self.cycle_active = True
        cycle_id = task["id"]
        self.arduino.send_json_line({"cmd": CMD_RUN, "cycle_id": cycle_id})
        print(f"[RUN] cycle_id={cycle_id} 전송")

    # STATE: 상태 완료 보고. DB 저장(릴레이) 후 ACK. VISION_READY면 AI 수행 후 TASK.
    def _on_state(self, msg: Dict[str, Any]) -> None:
        seq = msg.get("seq")
        cell = msg.get("cell")
        state = msg.get("state")

        # 진행상황을 AWS로 릴레이(있으면 좋은 정보 - 실패해도 무시).
        if self.cfg.aws_enabled and self.current_task is not None:
            self.cloud_sync.try_send(
                self.cloud.post_progress,
                robot_id=self.cfg.robot_id,
                task_id=self.current_task["id"],
                target=f"cell_{cell}" if cell is not None else None,
                state=state,
                progress=0,
            )

        # 스펙: STATE는 반드시 ACK. VISION_READY도 ACK를 먼저 보낸다.
        self.arduino.send_json_line({"cmd": CMD_ACK, "seq": seq})

        # VISION_READY는 "완료 보고"가 아니라 "AI 요청 동기화 지점".
        # AI 판독 -> (병해충 의심이면 관리자 판단) -> TASK를 내려줘야 Mega가 물리 동작 시작.
        if state == STATE_VISION_READY:
            self._handle_vision_ready()

    def _handle_vision_ready(self) -> None:
        vision = self.vision.read().to_payload()
        status = vision.get("status")

        vision_event_id = None
        if self.cfg.aws_enabled:
            try:
                event = self.cloud.post_vision_event(self.cfg.robot_id, vision)
                vision_event_id = event.get("id")
            except Exception as e:
                print(f"[!] vision 이벤트 기록 실패(무시하고 진행): {e}")

        # 병해충 의심이면 관리자 판단을 기다린다(정상 판독은 그대로 자동 진행).
        if self.cfg.aws_enabled and status in DISEASE_SUSPECT_STATUSES:
            status = self._await_admin_decision(status, vision_event_id)

        task = status_to_task(status)
        self.arduino.send_json_line({"cmd": CMD_TASK, "task": task})
        print(f"[TASK] vision={status} -> {task} 전송")

    # COMPLETE: 현재 Cell 작업 완료. AWS로 완료 보고.
    def _on_complete(self, msg: Dict[str, Any]) -> None:
        print(f"[COMPLETE] {msg}")
        if self.cfg.aws_enabled and self.current_task is not None:
            self.cloud_sync.try_send(
                self.cloud.post_response,
                robot_id=self.cfg.robot_id,
                task_id=self.current_task["id"],
                execute_task="CYCLE",
                completion_sign="DONE",
                message="Mega cell complete",
                payload={"mega_report": msg},
            )

    # ERROR: Mega 내부 런타임 에러. AWS로 보고(에러 코드 포함).
    def _on_error(self, msg: Dict[str, Any]) -> None:
        code = msg.get("code", "UNKNOWN")
        print(f"[!!!] Mega ERROR: code={code} raw={msg}")
        if self.cfg.aws_enabled and self.current_task is not None:
            self.cloud_sync.try_send(
                self.cloud.post_response,
                robot_id=self.cfg.robot_id,
                task_id=self.current_task["id"],
                execute_task="ERROR",
                completion_sign="ERROR",
                message=f"Mega error: {code}",
                payload={"mega_error": msg},
            )

    # 병해충 의심 판독 시 AWS 판단 요청 + 관리자 응답 폴링. treat면 원래 status, ignore면 healthy.
    def _await_admin_decision(self, status: str, vision_event_id: Optional[str]) -> str:
        if vision_event_id is None:
            print(f"[!!!] vision 이벤트 기록 실패로 판단 요청 불가 - 원래 판독값({status})으로 진행")
            return status

        try:
            req = self.cloud.create_decision_request(self.cfg.robot_id, vision_event_id, status)
        except Exception as e:
            print(f"[!!!] 판단 요청 생성 실패 - 원래 판독값({status})으로 진행: {e}")
            return status

        request_id = req.get("id")
        self.awaiting_decision = True
        print(f"[대기] 병해충 의심({status}) 판단 요청 생성(id={request_id}) - 관리자 응답 대기...")

        publisher = None
        get_shared_camera = getattr(self.vision, "get_shared_camera", None)
        if get_shared_camera is not None:
            try:
                from robot.webrtc_publisher import DiseaseStreamPublisher

                publisher = DiseaseStreamPublisher(self.cloud, get_shared_camera(), self.cfg.robot_id)
                publisher.start(request_id)
                print("[스트림] 관리자용 라이브 영상 세션 시작 시도")
            except Exception as e:
                print(f"[!] WebRTC 스트림 시작 실패(무시): {e}")
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
            self.last_pong_time = time.monotonic()  # 대기 끝난 직후 오프라인 오판 방지
            if publisher is not None:
                try:
                    publisher.stop()
                except Exception as e:
                    print(f"[!] 스트림 종료 중 오류(무시): {e}")

    def run_forever(self) -> None:
        # 리스너/하트비트 스레드가 모든 일을 하므로 메인은 살아있기만 하면 된다.
        try:
            while True:
                time.sleep(1.0)
        finally:
            self.close()

    def close(self) -> None:
        try:
            self.arduino.close()
        except Exception:
            pass
        try:
            self.vision.close()
        except Exception:
            pass
