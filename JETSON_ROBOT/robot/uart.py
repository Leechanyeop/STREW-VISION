import json # json 직렬화/역직렬화를 위해 json 모듈을 가져옵니다.
import time # time 모듈을 가져옵니다. Arduino가 재시작할 시간을 주기 위해, 그리고 타임아웃 계산을 위해 사용됩니다.
import threading # 여러 스레드가 동시에 쓰기를 시도할 때 순서를 보장하기 위한 Lock에 사용합니다.
from typing import Dict, Any, Optional # 문자열을 딕셔너리로 변환하고, 타입 힌트를 위해 사용합니다.
import serial # 아두이노 시리얼 통신을 위해 pyserial 모듈을 가져옵니다.
from robot.packet import encode_packet # 딕셔너리 -> 전송용 바이트 인코딩 규칙은 packet.py에 위임합니다.


class ArduinoLink:

    # ArduinoLink 클래스는 아두이노와의 시리얼 통신을 관리하는 클래스입니다.
    def __init__(self, port: str, baudrate: int = 115200, timeout: float = 1.0) -> None:
        self.serial: Optional[serial.Serial] = None

        # [2026-07-15 4차 수정] run_once()(메인 스레드)와 _uart_listener_loop()(별도 스레드)가
        # 각각 다른 시점에 send_json_line()을 부를 수 있어서, 두 쓰기가 타이밍 겹치면 바이트가
        # 섞여 나갈 위험이 있었다(문서/PDF에 계속 "미구현"으로 남아있던 항목). 여기서 쓰기 자체를
        # Lock으로 감싸서 "한 번에 한 스레드만 시리얼에 쓸 수 있다"를 클래스 레벨에서 보장한다.
        # 읽기(_read_json_line)는 _uart_listener_loop() 한 곳에서만 부르므로(단일 소유자) 별도
        # Lock이 필요 없다 - 이건 "쓰기가 여러 곳에서 발생할 수 있다"는 문제만 막는 것.
        self._write_lock = threading.Lock()

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

    # send_json_line: Mega에게 메시지를 "보내기만" 합니다. 응답은 읽지 않습니다.
    # (구버전엔 이 함수가 쓰기+읽기를 한 번에 다 처리했지만(stream_progress(), 이제 삭제됨),
    # 새 프로토콜은 Mega가 먼저 말을 걸 수도 있는 양방향 구조라서 "쓰기"와 "읽기"의 책임을
    # 완전히 나눴습니다. 읽기는 robot/state_machine.py의 _uart_listener_loop()가 전담합니다.)
    def send_json_line(self, payload: Dict[str, Any]) -> bool:
        if self.serial is None or not self.serial.is_open: # 시리얼 포트가 열려 있지 않으면 실패로 처리합니다.
            return False

        # 다른 스레드가 지금 쓰고 있으면 여기서 대기 - 두 스레드의 쓰기가 겹쳐서
        # 바이트가 섞여 나가는 것을 방지한다. encode_packet()으로 만든 한 줄(line) 전체가
        # write()+flush() 되는 동안은 이 Lock을 쥔 스레드만 시리얼에 쓸 수 있다.
        with self._write_lock:
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

    # [2026-07-15] 구버전 stream_progress()(명령 1번 -> RECEIVED~COMPLETE 세부 진행상황을
    # 이 함수 안에서 직접 읽던 제너레이터)는 새 프로토콜에서 완전히 대체되어 삭제함.
    # 이유: 새 프로토콜은 Mega가 REQUEST_VISION/PROGRESS_UPDATE/REPORT_RESULT 등으로
    # "먼저 말을 거는" 양방향 구조라서, 명령 하나 보내고 그 응답만 기다리는 방식 자체가
    # 안 맞음 - 읽기는 robot/state_machine.py의 _uart_listener_loop()가 전담한다(단일 소유자).
    # 옛 RECEIVED~COMPLETE 세부 스트리밍이 필요해지면 PROGRESS_UPDATE 쪽에서 재설계할 것.
