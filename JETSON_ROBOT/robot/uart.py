import json # json 직렬화/역직렬화를 위해 json 모듈을 가져옵니다.
import time # time 모듈을 가져옵니다. Arduino가 재시작할 시간을 주기 위해, 그리고 타임아웃 계산을 위해 사용됩니다.
from typing import Dict, Any, Optional, Iterator # 문자열을 딕셔너리로 변환하고, 타입 힌트를 위해 사용합니다.
import serial # 아두이노 시리얼 통신을 위해 pyserial 모듈을 가져옵니다.
from robot.packet import encode_packet # 딕셔너리 -> 전송용 바이트 인코딩 규칙은 packet.py에 위임합니다.


class ArduinoLink:

    # ArduinoLink 클래스는 아두이노와의 시리얼 통신을 관리하는 클래스입니다.
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self.serial: Optional[serial.Serial] = None
        try:
            self.serial = serial.Serial(port=port, baudrate=baudrate, timeout=timeout)

            # Arduino가 재시작할 시간을 주기 위해 2초 대기 후 입력 버퍼를 초기화합니다.
            time.sleep(2.0)
            if self.serial is not None:
                self.serial.reset_input_buffer()
        except serial.SerialException as e:
            raise RuntimeError(f"아두이노 포트 연결 실패: {e}") from e

    # close 메서드는 시리얼 포트를 닫는 역할을 합니다. 시리얼 포트가 열려 있는 경우에만 닫습니다.
    def close(self) -> None:
        if self.serial is not None and self.serial.is_open:
            self.serial.close()

    # send_json_line: Mega에게 명령을 "보내기만" 합니다. 응답은 읽지 않습니다.
    # (예전엔 이 함수가 쓰기+읽기를 한 번에 다 처리했지만, 새 프로토콜은 명령 1번에
    # 응답이 여러 번(RECEIVED~COMPLETE) 오기 때문에 "쓰기"와 "읽기"의 책임을 나눴습니다.
    # 응답을 읽는 책임은 아래 stream_progress()가 담당합니다.)
    def send_json_line(self, payload: Dict[str, Any]) -> bool:
        if self.serial is None or not self.serial.is_open: # 시리얼 포트가 열려 있지 않으면 실패로 처리합니다.
            return False

        try:
            line = encode_packet(payload) # 인코딩 규칙은 packet.py의 encode_packet()이 담당합니다.
            self.serial.write(line)
            self.serial.flush() # 버퍼에 남아 있는 데이터를 모두 전송합니다.
            return True
        except serial.SerialException as e:
            print(f"시리얼 통신 오류: {e}")
            return False

    # _read_json_line: 시리얼에서 한 줄을 읽어서 딕셔너리로 파싱하는 부분만 따로 뗀 헬퍼입니다.
    # bytes(원시 데이터) -> str(decode) -> dict(json.loads) 순서로 변환합니다.
    def _read_json_line(self) -> Optional[Dict[str, Any]]:
        if self.serial is None or not self.serial.is_open:
            return None

        try:
            # readline()은 bytes를 반환하므로, decode()로 문자열로 바꾸고 strip()으로 개행문자를 제거합니다.
            response = self.serial.readline().decode("utf-8", errors="replace").strip()
        except (serial.SerialException, OSError) as e:
            print(f"시리얼 통신 오류: {e}")
            return None

        if not response: # 응답이 비어 있으면(타임아웃) None을 반환합니다.
            return None

        try: # JSON 디코딩을 시도하고, 성공하면 딕셔너리를 반환합니다.
            return json.loads(response)
        except json.JSONDecodeError:
            print(f"JSON 디코딩 오류: {response}")
            return {"raw": response}

    # stream_progress: 명령을 딱 한 번 보내고, Mega가 RECEIVED~COMPLETE까지 보내는
    # 진행상황 메시지를 하나씩 yield로 내보내는 제너레이터입니다.
    #
    # timeout_sec: 마지막 메시지를 받은 뒤로 이 시간(초) 이상 새 메시지가 없으면
    # 로봇이 멈췄다고 보고 반복을 중단합니다. (상태(state)마다 다른 정밀한 시간을 재는 대신,
    # "마지막 메시지 이후 공통 기준 시간"으로 판단합니다 — 아직 하드웨어 실측 데이터가 없기 때문입니다.)
    def stream_progress(self, payload: Dict[str, Any], timeout_sec: float = 30.0) -> Iterator[Dict[str, Any]]:
        if not self.send_json_line(payload): # 명령 전송 자체가 실패하면 진행상황을 기다릴 필요도 없습니다.
            return

        last_received = time.monotonic() # 마지막으로 메시지를 받은 시각을 기록합니다.

        while True:
            message = self._read_json_line()

            if message is None:
                # 응답이 없었던 경우 - 아직 작업 중일 수도, 고장났을 수도 있습니다.
                # 마지막 메시지 이후 timeout_sec가 지났으면 포기하고 반복을 멈춥니다.
                if time.monotonic() - last_received > timeout_sec:
                    print(f"타임아웃: {timeout_sec}초 동안 응답 없음")
                    return
                continue

            last_received = time.monotonic() # 새 메시지를 받았으니 타임아웃 기준 시각을 갱신합니다.
            yield message

            if message.get("state") == "COMPLETE": # 완료 상태를 받으면 반복을 끝냅니다.
                return
