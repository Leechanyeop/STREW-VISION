from typing import Any, Dict, Optional
import requests

class CloudClient:# AWS 클라우드 API와 통신하는 클라이언트 클래스입니다.

    # __init__ 메서드는 클라이언트 객체를 초기화합니다. base_url은 AWS API의 기본 URL, api_key는 인증에 필요한 API 키, timeout은 요청 제한 시간을 설정합니다.
    def __init__(self, base_url: str, api_key: str, timeout: float = 5.0) -> None:
        self.base_url = base_url.rstrip("/") # rstrip("/")를 사용하여 base_url의 끝에 있는 슬래시를 제거합니다.
        
        # requests.Session()을 사용하여 세션 객체를 생성합니다.
        self.session = requests.Session() 

        # API 키와 콘텐츠 타입을 헤더에 추가합니다.
        self.session.headers.update({"X-API-Key": api_key, "Content-Type": "application/json"}) 
        self.timeout = timeout

    # next_task 메서드는 주어진 robot_id에 대한 다음 작업을 AWS 클라우드에서 가져옵니다.
    def next_task(self, robot_id: str) -> Optional[Dict[str, Any]]:
        r = self.session.get(f"{self.base_url}/robot/next", params={"robot_id": robot_id}, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # post_response 메서드는 주어진 파라미터들을 사용하여 AWS 클라우드에 응답을 전송합니다.
    def post_response(self, task_id: str, robot_id: str, execute_task: str, completion_sign: str, message: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        body = {"task_id": task_id, "robot_id": robot_id, "execute_task": execute_task, "completion_sign": completion_sign, "message": message, "payload": payload}
        r = self.session.post(f"{self.base_url}/robot/response", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # post_vision_event 메서드는 주어진 파라미터들을 사용하여 AWS 클라우드에 비전 이벤트를 전송합니다.
    def post_vision_event(self, robot_id: str, event: Dict[str, Any]) -> Dict[str, Any]:
        body = {"robot_id": robot_id, "source": "jetson-csi-camera", **event}
        r = self.session.post(f"{self.base_url}/vision/event", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
