import threading
from unittest.mock import MagicMock

from robot.uart import ArduinoLink


def _make_link(readline_return=None) -> ArduinoLink:
    link = ArduinoLink.__new__(ArduinoLink)  # __init__을 건너뛰고 빈 인스턴스만 생성 (실제 포트 없이 테스트)
    link._write_lock = threading.Lock()  # __init__을 건너뛰므로 send_json_line()이 쓰는 Lock도 직접 채워줘야 함
    mock_serial = MagicMock()
    mock_serial.is_open = True
    mock_serial.readline.return_value = readline_return
    link.serial = mock_serial
    return link


def test_send_json_line_writes_once_and_returns_true():
    # send_json_line은 "쓰기 전용" — 응답을 안 읽고 성공 여부(bool)만 돌려준다.
    link = _make_link(readline_return=b"")
    ok = link.send_json_line({"cmd": "RUN", "cycle_id": "t-1"})
    assert ok is True
    link.serial.write.assert_called_once()
    link.serial.flush.assert_called_once()


def test_send_json_line_returns_false_when_no_serial():
    link = ArduinoLink.__new__(ArduinoLink)
    link._write_lock = threading.Lock()
    link.serial = None
    assert link.send_json_line({"cmd": "RUN", "cycle_id": "t-1"}) is False


# 아래 _read_json_line() 테스트들은 robot/state_machine.py의 _uart_listener_loop()가
# (단일 소유자로서) 실제로 호출하는 읽기 경로를 검증한다.

def test_read_json_line_parses_valid_json():
    link = _make_link(readline_return=b'{"event":"STATE","seq":1,"cell":1,"state":"VISION_READY"}\r\n')
    assert link._read_json_line() == {"event": "STATE", "seq": 1, "cell": 1, "state": "VISION_READY"}


def test_read_json_line_returns_none_when_empty():
    # readline()이 빈 바이트를 돌려주는 경우 - 타임아웃/무응답 상황
    link = _make_link(readline_return=b"")
    assert link._read_json_line() is None


def test_read_json_line_wraps_non_json_as_raw():
    link = _make_link(readline_return=b"garbage-not-json\r\n")
    assert link._read_json_line() == {"raw": "garbage-not-json"}


def test_read_json_line_returns_none_when_no_serial():
    link = ArduinoLink.__new__(ArduinoLink)
    link._write_lock = threading.Lock()
    link.serial = None
    assert link._read_json_line() is None
