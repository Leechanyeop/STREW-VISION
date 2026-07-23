"""[2026-07-18] ESP32 센서 브리지.

ESP32가 MQTT(esp32/sensor)로 2초마다 보내는 온습도 JSON을 받아
AWS의 POST /sensor/log 로 전달한다.

ESP 페이로드 형식 (ESP_MQTT_01.ino 기준):
    {"sensor1": {"temp": 25.1, "humi": 60.0},
     "sensor2": {"temp": ..., "humi": ...},
     "sensor3": {"temp": ..., "humi": ...}}

매핑: sensor1 -> cell 1, sensor2 -> cell 2, sensor3 -> cell 3.

쓰로틀링: ESP 발행 주기(2초)를 그대로 전달하면 클라우드 쓰기가 과도해지므로
셀당 interval_sec(기본 10초)에 한 번만 전달한다. 전달 실패는 로봇 동작에
영향을 주면 안 되므로 조용히 버린다(fire-and-forget).
"""

import json
import time
from typing import Dict, Optional


def parse_esp_payload(payload: str) -> Dict[int, Dict[str, Optional[float]]]:
    """ESP JSON 문자열 -> {cell_id: {"temperature": t, "humidity": h}} 매핑.

    sensorN 키의 N을 cell_id로 쓴다. 형식이 안 맞는 항목은 건너뛴다.
    """
    data = json.loads(payload)
    result: Dict[int, Dict[str, Optional[float]]] = {}
    for key, value in data.items():
        if not key.startswith("sensor") or not isinstance(value, dict):
            continue
        try:
            cell_id = int(key.replace("sensor", ""))
        except ValueError:
            continue
        temp = value.get("temp")
        humi = value.get("humi")
        result[cell_id] = {
            "temperature": float(temp) if temp is not None else None,
            "humidity": float(humi) if humi is not None else None,
        }
    return result


class SensorBridge:
    def __init__(self, cloud_client, robot_id: str, interval_sec: float = 10.0, now=time.monotonic):
        self.cloud = cloud_client
        self.robot_id = robot_id
        self.interval_sec = interval_sec
        self._now = now  # 테스트에서 시계를 주입할 수 있게
        self._last_sent: Dict[int, float] = {}  # cell_id -> 마지막 전송 시각

    def handle_payload(self, payload: str) -> int:
        """MQTT 수신 콜백. 전달한 셀 개수를 반환한다(테스트/로그용)."""
        try:
            cells = parse_esp_payload(payload)
        except (json.JSONDecodeError, TypeError) as e:
            print(f"sensor bridge: payload 파싱 실패 (무시): {e}")
            return 0

        sent = 0
        now = self._now()
        for cell_id, values in cells.items():
            last = self._last_sent.get(cell_id)
            if last is not None and (now - last) < self.interval_sec:
                continue  # 쓰로틀링: 아직 interval이 안 지났으면 건너뜀
            try:
                self.cloud.post_sensor_log(self.robot_id, cell_id, values["temperature"], values["humidity"])
                self._last_sent[cell_id] = now
                sent += 1
            except Exception as e:
                # 클라우드 전달 실패는 로봇 동작에 영향 없이 버린다.
                # last_sent를 갱신하지 않으므로 다음 수신 때 자연히 재시도된다.
                print(f"sensor bridge: 전달 실패 cell={cell_id} (무시): {e}")
        return sent
