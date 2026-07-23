"""[2026-07-18] Mega UART 진단 스크립트 - main.py의 워치독(무응답) 원인 격리용.

main.py 없이 순수하게 "Mega가 시리얼로 말을 하는가?"만 확인한다.
포트를 열고 -> START_CYCLE을 한 번 보내고 -> 10초간 들어오는 모든 바이트를 날것으로 출력.

사용법 (Jetson에서, main.py는 먼저 종료할 것 - 포트를 동시에 못 씀):
    python3 scripts/diag_mega.py                    # 기본 /dev/ttyACM0, 115200
    python3 scripts/diag_mega.py /dev/ttyUSB0 115200
"""

import sys
import time

import serial
import serial.tools.list_ports


def main() -> int:
    port = sys.argv[1] if len(sys.argv) > 1 else "/dev/ttyACM0"
    baud = int(sys.argv[2]) if len(sys.argv) > 2 else 115200

    print("=== 연결된 시리얼 포트 목록 ===")
    ports = list(serial.tools.list_ports.comports())
    if not ports:
        print("  (없음) - USB 케이블/전원 확인. 데이터용 케이블인지도 확인.")
    for p in ports:
        print(f"  {p.device}  |  {p.description}  |  {p.hwid}")
    print()

    print(f"=== {port} @ {baud} 열기 시도 ===")
    try:
        s = serial.Serial(port=port, baudrate=baud, timeout=1.0)
    except serial.SerialException as e:
        print(f"[실패] 포트를 못 엽니다: {e}")
        print("  - 포트 이름이 위 목록과 다르면 인자로 지정하세요.")
        print("  - 'Permission denied'면: sudo usermod -aG dialout $USER 후 재로그인.")
        print("  - 'Device or resource busy'면: Arduino IDE 시리얼 모니터/다른 프로그램이 포트를 쥐고 있음.")
        return 1

    print("  열림 OK. Mega 리셋 대기 2초...")
    time.sleep(2.0)
    s.reset_input_buffer()

    # 1) START_CYCLE 보내기 전에, 부팅 메시지 등 그냥 들어오는 게 있는지 3초 관찰
    print("\n=== [1/2] START_CYCLE 보내기 전 3초 관찰 ===")
    got_any = _drain(s, 3.0)

    # 2) START_CYCLE 보내고 10초 관찰
    print("\n=== [2/2] START_CYCLE 전송 후 10초 관찰 ===")
    s.write(b'{"type":"START_CYCLE"}\n')
    s.flush()
    print('  보냄: {"type":"START_CYCLE"}')
    got_any = _drain(s, 10.0) or got_any

    s.close()
    print("\n=== 결론 ===")
    if got_any:
        print("  Mega가 응답함 -> UART 정상. main.py 쪽 문제라면 별도 확인.")
    else:
        print("  Mega가 10초간 한 바이트도 안 보냄. 아래 순서로 점검:")
        print("   1) 펌웨어가 실제로 업로드됐는가 (Arduino IDE로 mega_firmware.ino 재업로드)")
        print("   2) 포트가 진짜 Mega인가 (위 목록에서 'Arduino'/'ttyACM' 확인)")
        print("   3) USB 케이블이 데이터용인가 (충전 전용 케이블이면 통신 불가)")
        print("   4) 보드 전원 LED가 켜져 있는가")
        print("   5) baud가 펌웨어 setup()의 Serial.begin 값과 같은가 (기본 115200)")
    return 0


def _drain(s, seconds: float) -> bool:
    """seconds 동안 들어오는 모든 줄을 출력. 뭐라도 받았으면 True."""
    end = time.monotonic() + seconds
    got = False
    while time.monotonic() < end:
        line = s.readline()
        if line:
            got = True
            print(f"  <- {line!r}")
    if not got:
        print("  (아무것도 안 옴)")
    return got


if __name__ == "__main__":
    raise SystemExit(main())
