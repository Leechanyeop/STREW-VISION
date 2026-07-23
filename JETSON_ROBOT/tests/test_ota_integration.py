"""[2026-07-23] 젯슨 OTA 통합 테스트 - MQTT 메시지 문자열이 실제 배선을 타고
UpdateManager까지 도달하는지 검증. (MqttClient.on_update -> OtaService -> UpdateManager)

git/시리얼/네트워크는 전부 가짜. cloud/mqtt.py의 콜백 라우팅과 ota_service 배선을 함께 검증.
"""

from types import SimpleNamespace

from cloud.mqtt import MqttClient
from updater.ota_service import OtaService
from updater.update_manager import UpdateManager


class FakeRunner:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def run(self, args, check=False):
        self.calls.append(args)
        joined = " ".join(args)
        for subs, rc, out in self.script:
            if all(s in joined for s in subs):
                return SimpleNamespace(returncode=rc, stdout=out, stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")


class FakeArduino:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Cfg:
    robot_id = "robot-01"
    ota_repo_dir = None            # 테스트에서 tmp_path로 채움
    ota_status_topic = "robot/system/status"
    ota_arduino_fqbn = "arduino:avr:mega"
    ota_arduino_port = "/dev/ttyACM0"
    ota_firmware_sketch = "jetson_robot/mega_firmware"


def _wire(tmp_path, script):
    """실제 MqttClient + OtaService를 tmp repo와 가짜 runner로 배선한다."""
    cfg = Cfg()
    cfg.ota_repo_dir = str(tmp_path)

    published = []
    mqtt_client = MqttClient()
    mqtt_client.publish = lambda topic, payload: published.append((topic, payload))
    mqtt_client.update_topic = "robot/system/update"

    arduino = FakeArduino()
    svc = OtaService(cfg, mqtt_client, cloud_client=None, arduino_link=arduino)
    # UpdateManager의 runner/restart만 테스트용으로 교체(배선은 진짜 그대로).
    restarted = []
    svc.manager.runner = FakeRunner(script)
    svc.manager.restart_fn = lambda: restarted.append(True)
    svc.manager.now_fn = lambda: "2026-07-23 16:42:31"
    return mqtt_client, svc, published, restarted, arduino


def test_mqtt_message_routes_to_update_manager(tmp_path):
    # git diff에 python만 -> 재시작, arduino 안 건드림.
    script = [
        (["fetch"], 0, ""),
        (["rev-parse", "HEAD"], 0, "old"),
        (["rev-parse", "origin/main"], 0, "new"),
        (["pull"], 0, ""),
        (["diff", "--name-only"], 0, "jetson_robot/main.py\n"),
    ]
    mqtt_client, svc, published, restarted, arduino = _wire(tmp_path, script)

    # 실제 MQTT 수신을 흉내: on_message가 update_topic 메시지를 라우팅한다.
    msg = SimpleNamespace(topic="robot/system/update",
                          payload=b'{"command":"UPDATE","version":"20260723164200"}')
    mqtt_client.on_message(None, None, msg)

    # 상태가 status 토픽으로 발행됐고, 재시작까지 도달.
    statuses = [__import__("json").loads(p) for _, p in published]
    assert any(s["status"] == "UPDATING" for s in statuses)
    assert any(s["status"] == "UPDATE_COMPLETE" for s in statuses)
    assert restarted == [True]
    assert arduino.closed is False       # 펌웨어 변경 없음 -> UART 안 닫음


def test_mqtt_firmware_change_closes_uart_and_flashes(tmp_path):
    script = [
        (["fetch"], 0, ""),
        (["rev-parse", "HEAD"], 0, "old"),
        (["rev-parse", "origin/main"], 0, "new"),
        (["pull"], 0, ""),
        (["diff", "--name-only"], 0, "jetson_robot/mega_firmware/mega_firmware.ino\n"),
        (["arduino-cli", "compile"], 0, ""),
        (["arduino-cli", "upload"], 0, ""),
    ]
    mqtt_client, svc, published, restarted, arduino = _wire(tmp_path, script)
    msg = SimpleNamespace(topic="robot/system/update",
                          payload=b'{"command":"UPDATE","version":"20260723164200"}')
    mqtt_client.on_message(None, None, msg)

    assert arduino.closed is True        # 업로드 전 UART 해제됨
    assert any("arduino-cli" in " ".join(c) and "upload" in " ".join(c) for c in svc.manager.runner.calls)
    statuses = [__import__("json").loads(p) for _, p in published]
    assert statuses[-1]["status"] == "UPDATE_COMPLETE"
    assert statuses[-1]["firmware_updated"] is True


def test_non_update_topic_ignored(tmp_path):
    mqtt_client, svc, published, restarted, arduino = _wire(tmp_path, [])
    # 다른 토픽 메시지는 OTA를 트리거하지 않아야 한다.
    msg = SimpleNamespace(topic="some/other/topic", payload=b'{"command":"UPDATE"}')
    mqtt_client.on_message(None, None, msg)
    assert published == []
    assert restarted == []
