"""[2026-07-21] Mega 펌웨어 v1.0 프로토콜 시뮬레이터 (하드웨어 없이 Jetson 로직 검증).

실제 Arduino 없이, mega_firmware.ino와 동일한 프로토콜로 응답하는 가짜 Mega를
파이썬으로 구현한다. ArduinoLink를 monkeypatch로 이 가짜에 물려서 RobotAgent의
전체 흐름(READY->RUN->STATE/ACK->VISION_READY->TASK->COMPLETE + PING/PONG)을
콘솔에서 눈으로 확인한다.

사용법:
    python3 scripts/sim_mega_v1.py          # AWS 없이(mock) 1 Cycle(4셀) 시뮬레이션
"""

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class FakeMega:
    """mega_firmware.ino의 프로토콜을 그대로 흉내내는 가짜 Mega. non-blocking 아님 -
    Jetson이 보낸 cmd에 즉시 반응하고, RUN을 받으면 4셀 순회를 진행한다."""

    def __init__(self):
        self.inbox = []          # Jetson -> Mega 로 들어온 cmd JSON들
        self.outbox = []          # Mega -> Jetson 로 나갈 event 줄(bytes)
        self.mode = "IDLE"
        self.cell = 1
        self.step = "MOVE"
        self.seq = 0
        self.pending_seq = None
        self.task = None
        self._boot_sent = False

    # ---- Jetson이 쓰는 쪽 (ArduinoLink.send_json_line이 호출) ----
    def write_cmd(self, payload: dict):
        cmd = payload.get("cmd")
        if cmd == "PING":
            self._emit({"event": "PONG"})
        elif cmd == "RUN":
            if self.mode == "IDLE":
                self.mode = "RUN"
                self.cell, self.step, self.pending_seq, self.task = 1, "MOVE", None, None
                print(f"  (Mega) RUN 수신 cycle_id={payload.get('cycle_id')} -> 순회 시작")
        elif cmd == "ACK":
            if payload.get("seq") == self.pending_seq:
                self.pending_seq = None
        elif cmd == "TASK":
            if self.step == "WAIT_TASK":
                self.task = payload.get("task")

    # ---- Jetson이 읽는 쪽 (ArduinoLink._read_json_line이 호출) ----
    def read_line(self):
        if not self._boot_sent:
            self._boot_sent = True
            self._emit({"event": "READY"})
        else:
            self._tick()  # 순회 한 스텝 진행
        return self.outbox.pop(0) if self.outbox else b""

    def _emit(self, doc: dict):
        self.outbox.append((json.dumps(doc) + "\n").encode())

    def _send_state(self, state):
        self.seq += 1
        self.pending_seq = self.seq
        self._emit({"event": "STATE", "seq": self.seq, "cell": self.cell, "state": state})
        return self.seq

    def _tick(self):
        if self.mode != "RUN":
            return
        if self.step == "MOVE":
            self._send_state("MOVE_CELL"); self.step = "WAIT_MOVE_ACK"
        elif self.step == "WAIT_MOVE_ACK":
            if self.pending_seq is None: self.step = "VISION"
        elif self.step == "VISION":
            self._send_state("VISION_READY"); self.task = None; self.step = "WAIT_TASK"
        elif self.step == "WAIT_TASK":
            if self.task is not None:
                print(f"  (Mega) TASK={self.task} 수신 -> 물리 동작(가상)")
                self.step = "DONE"
        elif self.step == "DONE":
            self._send_state("TASK_DONE"); self.step = "WAIT_DONE_ACK"
        elif self.step == "WAIT_DONE_ACK":
            if self.pending_seq is None:
                self._emit({"event": "COMPLETE", "cell": self.cell})
                if self.cell >= 4:
                    self.mode = "IDLE"; print("  (Mega) 4셀 순회 완료 -> IDLE")
                else:
                    self.cell += 1; self.step = "MOVE"


class FakeArduinoLink:
    def __init__(self, mega):
        self.mega = mega
    def send_json_line(self, payload):
        self.mega.write_cmd(payload); return True
    def _read_json_line(self):
        line = self.mega.read_line()
        if not line:
            return None
        return json.loads(line.decode())
    def close(self):
        pass


def main():
    import robot.state_machine as sm
    from config.settings import Config

    mega = FakeMega()

    # ArduinoLink를 가짜로 교체 + MQTT/vision을 가볍게 스텁.
    sm.ArduinoLink = lambda *a, **k: FakeArduinoLink(mega)

    class FakeMqtt:
        on_sensor = None
        def connect(self, *a, **k): pass
    sm.MqttClient = lambda *a, **k: FakeMqtt()

    # Config 기본값이 이미 aws_enabled=False, vision_mode=mock 이라 그대로 쓴다.
    cfg = Config()

    print("=== Mega v1.0 프로토콜 시뮬레이션 시작 (AWS 없이 mock) ===")
    agent = sm.RobotAgent(cfg)
    # 10초간 돌리면서 흐름 관찰 (4셀 순회는 수 초 내 끝남)
    t_end = time.time() + 10
    while time.time() < t_end and mega.mode == "RUN" or (time.time() < t_end and not mega._boot_sent):
        time.sleep(0.2)
    time.sleep(1.0)
    print("=== 종료 ===")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
