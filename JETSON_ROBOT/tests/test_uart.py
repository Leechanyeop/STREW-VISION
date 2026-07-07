from unittest.mock import MagicMock

from robot.uart import ArduinoLink


def _make_link(readline_side_effect=None, readline_return=None) -> ArduinoLink:
    link = ArduinoLink.__new__(ArduinoLink)  # __init__을 건너뛰고 빈 인스턴스만 생성 (실제 포트 없이 테스트)
    mock_serial = MagicMock()
    mock_serial.is_open = True
    if readline_side_effect is not None:
        mock_serial.readline.side_effect = readline_side_effect
    else:
        mock_serial.readline.return_value = readline_return
    link.serial = mock_serial
    return link


def test_send_json_line_writes_once_and_returns_true():
    # send_json_line은 이제 "쓰기 전용" — 응답을 안 읽고 성공 여부(bool)만 돌려준다.
    link = _make_link(readline_return=b"")
    ok = link.send_json_line({"command": "REPLACE", "target": "cell_5"})
    assert ok is True
    link.serial.write.assert_called_once()
    link.serial.flush.assert_called_once()


def test_send_json_line_returns_false_when_no_serial():
    link = ArduinoLink.__new__(ArduinoLink)
    link.serial = None
    assert link.send_json_line({"command": "PING"}) is False


def test_stream_progress_yields_each_state_until_complete():
    # Mega가 RECEIVED -> MOVE_TO_CELL -> COMPLETE 순으로 보내는 상황을 흉내낸다.
    responses = [
        b'{"task":"REPLACE","target":"cell_5","state":"RECEIVED","progress":0}\r\n',
        b'{"task":"REPLACE","target":"cell_5","state":"MOVE_TO_CELL","progress":10}\r\n',
        b'{"task":"REPLACE","target":"cell_5","state":"COMPLETE","progress":100}\r\n',
    ]
    link = _make_link(readline_side_effect=responses)

    messages = list(link.stream_progress({"command": "REPLACE", "target": "cell_5"}))

    assert [m["state"] for m in messages] == ["RECEIVED", "MOVE_TO_CELL", "COMPLETE"]
    assert link.serial.write.call_count == 1  # 명령은 딱 한 번만 보내야 함 (쓰기/읽기 분리 확인)


def test_stream_progress_stops_reading_after_complete():
    # COMPLETE 다음에 메시지가 더 있어도 읽지 않고 멈춰야 한다.
    responses = [
        b'{"task":"SKIP","target":"cell_9","state":"RECEIVED","progress":0}\r\n',
        b'{"task":"SKIP","target":"cell_9","state":"COMPLETE","progress":100}\r\n',
        b'{"task":"SKIP","target":"cell_9","state":"SHOULD_NOT_BE_READ","progress":999}\r\n',
    ]
    link = _make_link(readline_side_effect=responses)

    messages = list(link.stream_progress({"command": "SKIP", "target": "cell_9"}))

    assert len(messages) == 2
    assert messages[-1]["state"] == "COMPLETE"


def test_stream_progress_wraps_non_json_line_as_raw():
    responses = [
        b"garbage-not-json\r\n",
        b'{"task":"OBSERVE","target":"cell_1","state":"COMPLETE","progress":100}\r\n',
    ]
    link = _make_link(readline_side_effect=responses)

    messages = list(link.stream_progress({"command": "OBSERVE", "target": "cell_1"}))

    assert messages[0] == {"raw": "garbage-not-json"}
    assert messages[1]["state"] == "COMPLETE"


def test_stream_progress_times_out_when_arduino_goes_silent():
    # 항상 빈 응답만 오는(고장 또는 무응답) 상황 - 타임아웃으로 빠져나와야 한다.
    link = _make_link(readline_return=b"")

    messages = list(
        link.stream_progress({"command": "REPLACE", "target": "cell_5"}, timeout_sec=0.05)
    )

    assert messages == []


def test_stream_progress_returns_nothing_when_send_fails():
    # 시리얼 연결 자체가 없어서 명령 전송이 실패하는 상황 - 아예 아무것도 안 나와야 한다.
    link = ArduinoLink.__new__(ArduinoLink)
    link.serial = None

    messages = list(link.stream_progress({"command": "REPLACE", "target": "cell_5"}))

    assert messages == []
