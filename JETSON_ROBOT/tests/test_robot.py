from robot.packet import encode_packet


def test_packet_is_newline_delimited_json():
    assert encode_packet({"a": 1}) == b'{"a":1}\n'
