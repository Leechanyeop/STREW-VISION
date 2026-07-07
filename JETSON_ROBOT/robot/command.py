# Arduino에게 보낼 명령서(Command)를 만드는 파일입니다.

from dataclasses import asdict, dataclass
from typing import Any, Dict

#json 직렬화/역직렬화를 위해 asdict를 사용하여 dataclass를 딕셔너리로 변환합니다.
@dataclass
class ArduinoCommand:
    command: str
    target: str

    def to_dict(self) -> Dict[str, Any]: #
        return asdict(self)
