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
    
    # post_progress 메서드는 아두이노가 스트리밍으로 보내는 진행상황 메시지 하나하나를
    # 그때그때 AWS에 실시간으로 보고합니다. post_response와 달리 한 작업당 여러 번(최대 9회)
    # 호출될 수 있고, 매번 "지금 이 순간의 상태"만 가볍게 담아 보냅니다.
    def post_progress(self, robot_id: str, task_id: str, target: str, state: str, progress: int) -> Dict[str, Any]:
        body = {
            "robot_id": robot_id,
            "task_id": task_id,
            "target": target,
            "state": state,
            "progress": progress,
        }
        r = self.session.post(f"{self.base_url}/robot/progress", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # [2026-07-16 추가] 병해충 의심 판독(예: powdery_mildew)이 나왔을 때 관리자 판단을
    # 요청하는 메서드. cloud_sync.try_send로 감싸지 않고 항상 직접 호출한다 - state_machine
    # 쪽에서 vision_event_id/request_id를 바로 받아서 폴링에 써야 하는데, try_send는
    # 실패시 큐에 넣고 반환값을 버리는 fire-and-forget이라 이 흐름엔 안 맞음.
    def create_decision_request(self, robot_id: str, vision_event_id: str, detected_status: str) -> Dict[str, Any]:
        body = {"robot_id": robot_id, "vision_event_id": vision_event_id, "detected_status": detected_status}
        r = self.session.post(f"{self.base_url}/vision/decision-request", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # get_decision_request 메서드는 판단 요청 하나의 현재 상태(pending/resolved_treat/
    # resolved_ignore)를 조회한다. state_machine이 관리자 응답을 기다리는 동안 주기적으로
    # 이 메서드를 폴링한다.
    def get_decision_request(self, request_id: str) -> Optional[Dict[str, Any]]:
        r = self.session.get(f"{self.base_url}/vision/decision-request/{request_id}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # [2026-07-16 추가] WebRTC 시그널링(StreamSession) 메서드 3종. robot/webrtc_publisher.py의
    # DiseaseStreamPublisher가 사용한다 - Jetson(offerer)이 offer_sdp를 들고 세션을 만들고,
    # 관리자 answer_sdp/ICE가 왔는지 폴링하고, 판단이 끝나면 세션을 닫는다.
    def create_stream_session(self, robot_id: str, decision_request_id: str, offer_sdp: str) -> Dict[str, Any]:
        body = {"robot_id": robot_id, "decision_request_id": decision_request_id, "offer_sdp": offer_sdp}
        r = self.session.post(f"{self.base_url}/stream/session", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def get_stream_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        r = self.session.get(f"{self.base_url}/stream/session/{session_id}", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def close_stream_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        r = self.session.post(f"{self.base_url}/stream/session/{session_id}/close", timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # [2026-07-18] ESP32 센서 브리지용. MQTT(esp32/sensor)로 받은 온습도를 AWS의
    # POST /sensor/log 로 전달한다. 서버가 임계치 검사(env_warning)까지 해서 저장한다.
    def post_sensor_log(self, robot_id: str, cell_id: int, temperature: Optional[float], humidity: Optional[float]) -> Dict[str, Any]:
        body = {"robot_id": robot_id, "cell_id": cell_id, "temperature": temperature, "humidity": humidity}
        r = self.session.post(f"{self.base_url}/sensor/log", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    # [2026-07-23] OTA: 업데이트 진행/결과를 AWS에 보고(대시보드가 조회).
    def post_ota_status(self, robot_id: str, status: Dict[str, Any]) -> Dict[str, Any]:
        body = {"robot_id": robot_id, **status}
        r = self.session.post(f"{self.base_url}/robot/ota-status", json=body, timeout=self.timeout)
        r.raise_for_status()
        return r.json()
