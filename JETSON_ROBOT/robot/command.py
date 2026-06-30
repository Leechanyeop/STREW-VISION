from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional


@dataclass
class ArduinoCommand:
    task_id: str
    execute_task: str
    move_sign: str
    target_label: Optional[str]
    detected_label: Optional[str]
    x_center: Optional[int]
    y_center: Optional[int]

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
