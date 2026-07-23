"""[2026-07-18] ESP32 센서 브리지 검증 - 브로커/네트워크 없이 파싱·매핑·쓰로틀링만 단위 테스트."""

from cloud.sensor_bridge import SensorBridge, parse_esp_payload


ESP_PAYLOAD = '{"sensor1":{"temp":25.1,"humi":60},"sensor2":{"temp":26.0,"humi":55},"sensor3":{"temp":24.2,"humi":70}}'


class FakeCloud:
    def __init__(self, fail=False):
        self.calls = []
        self.fail = fail

    def post_sensor_log(self, robot_id, cell_id, temperature, humidity):
        if self.fail:
            raise RuntimeError("network down")
        self.calls.append((robot_id, cell_id, temperature, humidity))
        return {"ok": True}


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_parse_maps_sensor_n_to_cell_n():
    cells = parse_esp_payload(ESP_PAYLOAD)
    assert set(cells.keys()) == {1, 2, 3}
    assert cells[1] == {"temperature": 25.1, "humidity": 60.0}
    assert cells[3]["humidity"] == 70.0


def test_parse_skips_malformed_entries():
    cells = parse_esp_payload('{"sensor1":{"temp":25},"weird":{"temp":1},"sensorX":{"temp":2},"sensor2":"broken"}')
    assert set(cells.keys()) == {1}
    assert cells[1]["temperature"] == 25.0
    assert cells[1]["humidity"] is None


def test_forwards_all_cells_first_time():
    cloud, clock = FakeCloud(), FakeClock()
    bridge = SensorBridge(cloud, "robot-01", interval_sec=10, now=clock)
    sent = bridge.handle_payload(ESP_PAYLOAD)
    assert sent == 3
    assert len(cloud.calls) == 3
    assert cloud.calls[0][0] == "robot-01"


def test_throttles_within_interval():
    cloud, clock = FakeCloud(), FakeClock()
    bridge = SensorBridge(cloud, "robot-01", interval_sec=10, now=clock)
    bridge.handle_payload(ESP_PAYLOAD)      # t=0: 3건 전송
    clock.t = 5.0
    assert bridge.handle_payload(ESP_PAYLOAD) == 0   # 10초 안 지남 -> 전부 스킵
    clock.t = 10.0
    assert bridge.handle_payload(ESP_PAYLOAD) == 3   # 10초 지남 -> 다시 전송
    assert len(cloud.calls) == 6


def test_cloud_failure_is_swallowed_and_retried_next_time():
    cloud, clock = FakeCloud(fail=True), FakeClock()
    bridge = SensorBridge(cloud, "robot-01", interval_sec=10, now=clock)
    assert bridge.handle_payload(ESP_PAYLOAD) == 0   # 실패해도 예외가 밖으로 안 나감

    # 실패 시 last_sent를 기록하지 않으므로, 시간이 안 지나도 다음 수신 때 재시도된다.
    cloud.fail = False
    assert bridge.handle_payload(ESP_PAYLOAD) == 3


def test_garbage_payload_returns_zero():
    cloud, clock = FakeCloud(), FakeClock()
    bridge = SensorBridge(cloud, "robot-01", interval_sec=10, now=clock)
    assert bridge.handle_payload("not json at all {{{") == 0
    assert cloud.calls == []
