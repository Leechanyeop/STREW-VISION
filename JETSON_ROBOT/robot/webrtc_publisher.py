"""
[2026-07-16 추가] 병해충 의심 판정 시에만 켜지는 WebRTC 영상 publisher (Jetson = offerer).

배경: state_machine._await_admin_decision()이 관리자 판단을 기다리는 동안, 관리자가
IMX708 라이브 영상을 보고 판단할 수 있어야 한다. AWS_SYSTEM에는 이미 StreamSession
시그널링 모델(offer/answer/ICE를 폴링으로 주고받는 "우체통")이 구현돼 있으므로, 여기서는
그 우체통에 offer를 넣고 answer/ICE를 받아오는 Jetson 쪽 절반을 구현한다.

*** 중요: 이 모듈은 aiortc 공식 예제(apprtc/webcam) 패턴을 따라 작성했지만, Jetson Nano의
ARM+CUDA 스택에서 aiortc/PyAV(av)가 실제로 설치·구동되는지는 아직 실기기에서 검증되지
않았다. pip install aiortc av 가 Jetson에서 실패하거나(특히 libavcodec 계열 네이티브
빌드 의존성 때문에) 성능이 안 나올 수 있음 - 반드시 실기기에서 먼저 설치 테스트가
필요하다 (사용자가 직접 확인하기로 함).

또한 이 모듈이 쓰는 카메라는 반드시 ai/detector/camera.py의 CsiCameraVisionSource가
이미 열어둔 SharedFrameCamera 하나를 그대로 받아써야 한다 - 새로 cv2.VideoCapture를
또 열면 안 된다(V4L2 장치 중복 오픈 문제, frame_hub.py 참고).
"""

import asyncio
import threading
from typing import Any, Optional

from cloud.api_client import CloudClient

# 목표 프레임레이트. 병해충 판단용 육안 확인이 목적이라 굳이 30fps씩 안 보내도 되고,
# Jetson Nano 리소스를 아끼기 위해 낮게 잡는다. 실기기 테스트 후 조정.
STREAM_FPS = 10.0

# 관리자의 answer_sdp/trickled ICE가 왔는지 확인하는 폴링 간격(초).
STREAM_POLL_INTERVAL_SEC = 2.0

# [발견된 버그 수정 3] 관리자 대시보드(JS)는 RTCPeerConnection 생성 시
# stun:stun.l.google.com:19302를 명시하는데, Jetson 쪽은 이 상수가 추가되기 전까지
# ICE 서버를 아예 지정하지 않고 있었다 - 같은 공유기 안에서는 host candidate만으로도
# 연결되니 문제가 안 드러나지만, Jetson이 NAT 뒤에 있고 관리자가 다른 네트워크에서
# 접속하면 server-reflexive candidate가 없어서 연결이 실패할 수 있다. 양쪽을 맞춘다.
# 방화벽이 빡빡한 네트워크(대부분의 농장/사내망)에서는 STUN만으로 안 될 수 있으니,
# 실사용 단계에서 연결이 계속 실패하면 TURN 서버 추가를 고려할 것.
ICE_SERVERS = ["stun:stun.l.google.com:19302"]


def _frame_track_class():
    """aiortc/av는 이 함수가 실제로 호출되는 시점(=병해충 의심 판정이 나서 스트림이
    필요해진 시점)에만 import한다 - cv2/tensorrt와 같은 이유로, 이 무거운 선택적
    의존성이 없는 환경(mock 모드, 이 프로젝트를 pytest로 돌리는 개발 PC)에서도
    나머지 코드는 문제없이 동작해야 하기 때문."""
    import av
    from aiortc import VideoStreamTrack

    class SharedFrameVideoTrack(VideoStreamTrack):
        """SharedFrameCamera의 최신 프레임을 계속 읽어서 WebRTC 영상 트랙으로 내보낸다."""

        def __init__(self, shared_camera: Any, fps: float = STREAM_FPS) -> None:
            super().__init__()
            self.shared_camera = shared_camera
            self._frame_interval = 1.0 / fps

        async def recv(self):
            pts, time_base = await self.next_timestamp()
            frame = self.shared_camera.get_latest_frame()
            if frame is None:
                # 카메라가 아직 첫 프레임을 못 읽었을 때를 대비한 최소 placeholder.
                # aiortc는 recv()가 매번 실제 프레임 객체를 반환하길 기대해서 None을 못 준다.
                import numpy as np

                frame = np.zeros((480, 640, 3), dtype="uint8")
            video_frame = av.VideoFrame.from_ndarray(frame, format="bgr24")
            video_frame.pts = pts
            video_frame.time_base = time_base
            await asyncio.sleep(self._frame_interval)
            return video_frame

    return SharedFrameVideoTrack


def _ice_candidate_from_dict(cand: dict):
    """AWS StreamSession의 answerer_ice 항목({candidate, sdpMid, sdpMLineIndex})을
    aiortc의 RTCIceCandidate 객체로 변환한다. aiortc 공식 예제(examples/webcam,
    examples/apprtc)가 trickled candidate를 받을 때 쓰는 것과 같은 패턴:
    "candidate:" 접두어를 뗀 나머지를 candidate_from_sdp로 파싱한 뒤 sdpMid/
    sdpMLineIndex를 별도로 채워 넣는다."""
    from aiortc.sdp import candidate_from_sdp

    raw = cand.get("candidate") or ""
    if not raw:
        return None
    body = raw.split("candidate:", 1)[-1] if "candidate:" in raw else raw
    ice = candidate_from_sdp(body)
    ice.sdpMid = cand.get("sdpMid")
    ice.sdpMLineIndex = cand.get("sdpMLineIndex")
    return ice


class DiseaseStreamPublisher:
    """병해충 의심 판정으로 관리자 판단을 기다리는 동안에만 생성/사용되는 1회성
    WebRTC publisher. 나머지 로봇 코드베이스는 전부 동기/스레드 기반이라, 이 클래스는
    자체 asyncio 이벤트 루프를 별도 데몬 스레드에서 돌려서 state_machine.py의 동기
    흐름과 자연스럽게 맞물리게 한다 (state_machine 쪽은 start()/stop()만 동기 함수로
    호출하면 됨 - 내부적으로 asyncio를 쓴다는 걸 몰라도 됨).
    """

    def __init__(self, cloud: CloudClient, shared_camera: Any, robot_id: str) -> None:
        self.cloud = cloud
        self.shared_camera = shared_camera
        self.robot_id = robot_id
        self._pc: Optional[Any] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_flag = threading.Event()
        self._negotiate_future: Optional["asyncio.Future"] = None
        self.session_id: Optional[str] = None

    def start(self, decision_request_id: str) -> Optional[str]:
        """세션을 만들고 백그라운드 스레드에서 offer 생성 -> AWS 등록 -> answer/ICE 폴링을
        진행한다. 세션 등록까지만 동기적으로 기다렸다가 session_id를 반환하고, 그 이후
        (answer 대기, ICE 교환)는 백그라운드에서 계속 진행된다. aiortc/av가 이 환경에
        없거나 카메라 접근에 실패하면 예외를 그대로 올린다 - 호출부(state_machine)가
        이미 try/except로 감싸서 "스트림 실패해도 판단 대기 자체는 계속"하도록 처리함."""
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        fut = asyncio.run_coroutine_threadsafe(self._create_session(decision_request_id), self._loop)
        self.session_id = fut.result(timeout=15.0)

        # 여기서부터(answer/ICE 대기)는 세션 생성과 별개로 백그라운드에서 계속 돈다 -
        # 관리자가 답할 때까지 몇 분이 걸릴 수도 있는데, start()가 그동안 안 막혀야
        # _await_admin_decision()의 폴링 루프가 정상적으로 계속 돌 수 있기 때문.
        self._negotiate_future = asyncio.run_coroutine_threadsafe(self._negotiate_loop(), self._loop)
        return self.session_id

    def stop(self) -> None:
        """관리자 응답을 받아 판단 대기가 끝났을 때(또는 스트림 시작 자체가 실패했을 때)
        호출 - PeerConnection을 닫고 AWS에도 세션 종료를 알린 뒤 이벤트 루프를 정리한다."""
        self._stop_flag.set()
        if self.session_id:
            try:
                self.cloud.close_stream_session(self.session_id)
            except Exception as e:
                print(f"[!] 스트림 세션 종료 알림 실패(무시): {e}")
        # [발견된 버그 수정 2] _negotiate_loop()가 answer/ICE를 기다리며 sleep 중일 때
        # 루프를 그냥 멈춰버리면 이 코루틴이 "완료도 취소도 안 된 채" 파괴돼서
        # "Task was destroyed but it is pending!" 경고가 남는다(실제 테스트에서 재현
        # 확인함). stop()이 호출됐다는 건 이 태스크가 더 이상 필요 없다는 뜻이므로
        # 명시적으로 취소해서 깔끔하게 정리한다.
        if self._negotiate_future is not None:
            self._negotiate_future.cancel()
        if self._loop is not None and self._pc is not None:
            # [발견된 버그 수정] run_coroutine_threadsafe는 코루틴 실행을 "예약"만 하고
            # 바로 반환한다 - .result()로 기다리지 않고 곧장 루프를 멈추면 pc.close()가
            # 채 끝나기도 전에 이벤트 루프가 죽어서 "coroutine was never awaited" 경고와
            # 함께 리소스가 제대로 안 정리될 수 있다(실제 테스트에서 재현 확인함).
            close_fut = asyncio.run_coroutine_threadsafe(self._pc.close(), self._loop)
            try:
                close_fut.result(timeout=3.0)
            except Exception as e:
                print(f"[!] PeerConnection 종료 대기 중 오류(무시): {e}")
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=2.0)

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    async def _create_session(self, decision_request_id: str) -> str:
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection

        SharedFrameVideoTrack = _frame_track_class()
        ice_config = RTCConfiguration(iceServers=[RTCIceServer(urls=u) for u in ICE_SERVERS])
        self._pc = RTCPeerConnection(configuration=ice_config)
        self._pc.addTrack(SharedFrameVideoTrack(self.shared_camera))

        offer = await self._pc.createOffer()
        await self._pc.setLocalDescription(offer)

        # 폴링 기반 시그널링(우체통)이라 trickle ICE보다 "수집 완료 후 완전한 SDP를 한 번에
        # 보내는" 방식이 훨씬 단순하고 안전하다 - 수집 도중 SDP를 보내면 관리자 브라우저가
        # 일부 host candidate를 놓칠 수 있다. 그래서 offerer(Jetson) 쪽은 ICE 수집이 끝날
        # 때까지 기다린 뒤에야 AWS로 세션을 만든다.
        while self._pc.iceGatheringState != "complete":
            await asyncio.sleep(0.1)

        session = self.cloud.create_stream_session(
            self.robot_id, decision_request_id, self._pc.localDescription.sdp
        )
        return session["id"]

    async def _negotiate_loop(self) -> None:
        """answer_sdp를 폴링해서 받아오고(1회), 그 뒤로는 관리자 브라우저가 trickle로
        보내는 ICE candidate를 계속 폴링해서 추가한다. 관리자가 라이브뷰를 닫거나
        stop()이 호출되면(둘 다 결국 status가 closed가 되거나 _stop_flag가 켜짐) 종료."""
        seen_answerer_ice = 0
        answered = False
        while not self._stop_flag.is_set():
            await asyncio.sleep(STREAM_POLL_INTERVAL_SEC)
            try:
                current = self.cloud.get_stream_session(self.session_id)
            except Exception as e:
                print(f"[!] 스트림 세션 조회 실패, 재시도: {e}")
                continue
            if current is None:
                continue

            if not answered and current.get("answer_sdp"):
                from aiortc import RTCSessionDescription

                answer = RTCSessionDescription(sdp=current["answer_sdp"], type="answer")
                await self._pc.setRemoteDescription(answer)
                answered = True
                print("[스트림] 관리자 브라우저 answer 수신 - WebRTC 연결 진행 중")

            answerer_ice = current.get("answerer_ice") or []
            for cand in answerer_ice[seen_answerer_ice:]:
                try:
                    ice = _ice_candidate_from_dict(cand)
                    if ice is not None:
                        await self._pc.addIceCandidate(ice)
                except Exception as e:
                    print(f"[!] ICE candidate 추가 실패(무시): {e}")
            seen_answerer_ice = len(answerer_ice)

            if current.get("status") == "closed":
                break
