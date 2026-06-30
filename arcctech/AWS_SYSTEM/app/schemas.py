from datetime import datetime, timezone
from typing import Any, Dict, Literal, Optional
from uuid import uuid4
from pydantic import BaseModel, Field

TaskStatus = Literal["queued", "sent", "running", "done", "failed", "cancelled"]


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RobotTaskCreate(BaseModel):
    robot_id: str = "robot-01"
    execute_task: str = Field(..., examples=["PICK_BY_VISION"])
    move_sign: str = Field(default="STOP", examples=["LEFT", "RIGHT", "FORWARD", "BACKWARD", "STOP"])
    target_label: Optional[str] = Field(default=None, examples=["box"])
    payload: Dict[str, Any] = Field(default_factory=dict)


class RobotTask(RobotTaskCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: TaskStatus = "queued"
    created_at: str = Field(default_factory=utc_now)
    updated_at: str = Field(default_factory=utc_now)


class RobotResponseCreate(BaseModel):
    task_id: str
    robot_id: str = "robot-01"
    execute_task: str
    completion_sign: str = Field(..., examples=["DONE", "FAILED", "RUNNING"])
    message: str = ""
    payload: Dict[str, Any] = Field(default_factory=dict)


class RobotResponse(RobotResponseCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=utc_now)


class VisionEventCreate(BaseModel):
    robot_id: str = "robot-01"
    source: str = "jetson-csi-camera"
    label: Optional[str] = None
    confidence: Optional[float] = None
    x_center: Optional[int] = None
    y_center: Optional[int] = None
    width: Optional[int] = None
    height: Optional[int] = None
    payload: Dict[str, Any] = Field(default_factory=dict)


class VisionEvent(VisionEventCreate):
    id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: str = Field(default_factory=utc_now)
