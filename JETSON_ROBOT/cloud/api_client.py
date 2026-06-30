from typing import Any, Dict, Optional
import requests

class CloudClient:
    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": api_key, "Content-Type": "application/json"})
        self.timeout = timeout

    def next_task(self, robot_id: str) -> Optional[Dict[str, Any]]:
        r = self.session.get(f"{self.base_url}/robot/next", params={"robot_id": robot_id}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post_response(self, task_id: str, robot_id: str, execute_task: str, completion_sign: str, message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {"task_id": task_id, "robot_id": robot_id, "execute_task": execute_task, "completion_sign": completion_sign, "message": message, "payload": payload}
        r = self.session.post(f"{self.base_url}/robot/response", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def post_vision_event(self, robot_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        body = {"robot_id": robot_id, "source": "jetson-csi-camera", **event}
        r = self.session.post(f"{self.base_url}/vision/event", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
