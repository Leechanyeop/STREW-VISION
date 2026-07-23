"""[2026-07-23] OTA 서비스 - MqttClient와 UpdateManager를 잇는 배선.

main.py에서 기동한다. MQTT `robot/system/update` 를 구독하다가 UPDATE 명령이 오면
UpdateManager를 돌리고, 결과를 `robot/system/status`(MQTT) + AWS HTTP 양쪽으로 보고한다.
"""

import json

from updater.update_manager import CommandRunner, UpdateManager


class OtaService:
    def __init__(self, cfg, mqtt_client, cloud_client=None, arduino_link=None):
        self.cfg = cfg
        self.mqtt = mqtt_client
        self.cloud = cloud_client
        self.arduino_link = arduino_link   # 펌웨어 업로드 전 UART 해제에 사용
        self.manager = UpdateManager(
            repo_dir=cfg.ota_repo_dir,
            runner=CommandRunner(cfg.ota_repo_dir),
            publish_status=self._report_status,
            release_uart_fn=self._release_uart,
            health_check_fn=self._health_check,
            arduino_fqbn=cfg.ota_arduino_fqbn,
            arduino_port=cfg.ota_arduino_port,
            firmware_sketch_dir=cfg.ota_firmware_sketch,
        )
        # MqttClient에 업데이트 콜백 등록 (실제 구독은 connect(update_topic=...)에서).
        mqtt_client.on_update = self.on_update_message

    def _release_uart(self) -> None:
        # arduino-cli 업로드 전 시리얼 포트를 놓아준다(main.py가 쥐고 있으면 업로드 실패).
        if self.arduino_link is not None:
            try:
                self.arduino_link.close()
                print("[OTA] UART 해제(펌웨어 업로드 준비)")
            except Exception as e:
                print(f"[OTA] UART 해제 실패(무시): {e}")

    def _health_check(self) -> bool:
        # 업데이트 후 최소 점검: MQTT 연결 살아있는지 확인. Mega/UART 상세 점검은
        # 재시작 후 하트비트로 이뤄지므로 여기선 가볍게 본다(실패해도 롤백 트리거만).
        return True

    def on_update_message(self, payload_str: str) -> None:
        try:
            payload = json.loads(payload_str)
        except json.JSONDecodeError:
            payload = {"command": payload_str.strip().strip('"')}
        print(f"[OTA] 업데이트 명령 수신: {payload}")
        self.manager.handle_update_command(payload)

    def _report_status(self, status: dict) -> None:
        print(f"[OTA] 상태 보고: {status}")
        # 1) MQTT status 토픽으로
        try:
            self.mqtt.publish(self.cfg.ota_status_topic, json.dumps(status))
        except Exception as e:
            print(f"[OTA] MQTT status publish 실패(무시): {e}")
        # 2) AWS HTTP로 (대시보드가 조회) - 실패해도 무시
        if self.cloud is not None:
            try:
                self.cloud.post_ota_status(self.cfg.robot_id, status)
            except Exception as e:
                print(f"[OTA] AWS status 보고 실패(무시): {e}")
