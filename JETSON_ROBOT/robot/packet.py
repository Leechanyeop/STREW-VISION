"""robot/packet.py — 전송용 패킷 "인코딩 규칙"만 담당하는 파일.

설계 의도 (역할 분리):
- packet.py: 딕셔너리를 어떤 바이트 형식으로 바꿀지 "규칙"만 안다. 하드웨어를 전혀 모른다.
- uart.py:   그렇게 만들어진 바이트를 실제 시리얼 포트로 주고받는 "I/O"만 담당한다. 규칙은 모른다.

이렇게 나누는 이유:
1) 인코딩 규칙(JSON 구분자, 인코딩 방식, 개행 문자 등)이 바뀌어도 uart.py는 건드릴 필요가 없다.
2) 나중에 UART가 아닌 다른 전송 수단(예: cloud/mqtt.py)을 추가해도
   encode_packet()을 그대로 재사용할 수 있다 — 인코딩 규칙은 전송 수단과 무관하니까.
3) 시리얼 포트(하드웨어)나 mock 없이도 인코딩 로직만 독립적으로 테스트할 수 있다.
   (실제로 tests/test_robot.py가 이 함수만 따로 검증하고 있다.)
"""

import json
from typing import Any


def encode_packet(payload: dict[str, Any]) -> bytes:
    r"""딕셔너리를 "한 줄 JSON + 개행문자" 형태의 UTF-8 바이트로 변환한다.

    예: {"task": "MOVE", "x": 300} -> b'{"task":"MOVE","x":300}\n'

    - separators=(",", ":") : 공백 없이 압축해서 전송량을 줄인다.
    - ensure_ascii=False    : 한글이 유니코드 이스케이프(\uXXXX)로 안 바뀌고 그대로 전송된다.
    - 끝의 "\n"            : 아두이노가 Serial.readStringUntil('\n')(혹은 readline())으로
                              "패킷 한 줄이 끝났다"를 인식하는 구분자다. 이게 없으면 아두이노가
                              데이터를 계속 기다리기만 하고 파싱을 시작하지 않는다.
    """
    return (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode("utf-8")
