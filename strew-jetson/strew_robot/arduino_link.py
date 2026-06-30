import json
import time
from typing import Dict, Any, Optional
import serial

class ArduinoLink:
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)
        time.sleep(2.0)
        self.serial.reset_input_buffer()

    def close(self) -> None:
        self.serial.close()

    def send_json_line(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        line = json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n"
        self.serial.write(line.encode("utf-8"))
        self.serial.flush()
        response = self.serial.readline().decode("utf-8", errors="replace").strip()
        if not response:
            return None
        try:
            return json.loads(response)
        except json.JSONDecodeError:
            return {"raw": response}
