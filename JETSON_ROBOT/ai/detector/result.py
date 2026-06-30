from dataclasses import asdict, dataclass
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
