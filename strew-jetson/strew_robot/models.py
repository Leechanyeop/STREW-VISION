from dataclasses import dataclass, asdict
from typing import Any, Dict, Optional

@dataclass
class VisionResult:
    label: Optional[str]
    confidence: Optional[float] = None
    x_center: Optional[int] = None
    y_center: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None

    def to_payload(self) -> Dict[str, Any]:
        return asdict(self)

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
