# Arduino에게 보낼 명령서(Command)를 만드는 파일입니다.

# [2026-07-15] 구버전 2필드(command/target) 프로토콜의 ArduinoCommand 데이터클래스는
# 새 프로토콜(type 기반 JSON, 아래 MSG_* 상수)로 완전히 대체되어 코드 어디서도 더 이상
# 쓰이지 않아 삭제함(grep으로 참조 없음 확인). 구버전 필드 구조 자체는
# ARDUINO_MEGA2560_프로토콜.md의 "구버전 프로토콜" 절에 문서로만 남아있음.

# Mega <-> Jetson 메시지 종류 (새 아키텍처: 결정권이 Mega로 이동, Jetson은 요청에 응답만 함)
# 문자열을 여기저기 하드코딩하면 오타로 다른 뜻이 될 위험이 있어서 상수로 모아둠.
#
# [2026-07-15 2차 수정] Mega가 1~4번 셀 "전체 순회"를 자체 관리하는 것으로 확정됨에 따라
# MSG_ASSIGN_TARGET(셀 하나 지정)은 더 이상 안 쓰고 MSG_START_CYCLE(순회 시작 트리거,
# 셀 지정 없음)로 대체한다. ASSIGN_TARGET 상수 자체는 하위 호환/문서 추적 목적으로 남겨둠.
#
# [2026-07-15 3차 수정] ERROR 복구 경로 추가: ERROR 메시지에 severity(minor/critical) 필드가
# 붙고, severity가 minor일 때만 MSG_RESET으로 원격 재시작이 가능하다. critical이면 Mega가
# RESET을 무시하고 물리 리셋(전원 재시작 등)만 받아들이도록 Mega 펌웨어 쪽에서 강제해야
# 한다 - Jetson이 실수로 RESET을 보내도 Mega 스스로 거부하는 이중 안전장치가 목적.
MSG_ASSIGN_TARGET = "ASSIGN_TARGET"      # [사용 중단, START_CYCLE로 대체됨] Jetson -> Mega: 셀 하나 지정
MSG_START_CYCLE = "START_CYCLE"          # Jetson -> Mega: 순회 시작 트리거 (셀 지정 없음 - 1~4번 전체를 Mega가 자체 관리)
MSG_REQUEST_VISION = "REQUEST_VISION"    # Mega -> Jetson: 지금 비전 상태 확인해줘 (순회 중 셀마다 호출)
MSG_VISION_RESULT = "VISION_RESULT"      # Jetson -> Mega: 날것 status만 회신 (판단 없음)
MSG_REPORT_RESULT = "REPORT_RESULT"      # Mega -> Jetson: 셀 하나 처리 결과 보고 (Jetson이 AWS로 릴레이). 순회당 최대 4회.
MSG_PROGRESS_UPDATE = "PROGRESS_UPDATE"  # Mega -> Jetson: 작업 중 셀 번호(target)+상태머신(state) 중계 보고
                                          # (응답 필요 없음, 그냥 정보 전달 - Jetson은 AWS로 릴레이만 함)
MSG_CYCLE_COMPLETE = "CYCLE_COMPLETE"    # Mega -> Jetson: 1~4번 전체 순회 끝, 초기 위치 복귀 후 IDLE 전환. 순회당 1회.
MSG_ERROR = "ERROR"                      # Mega -> Jetson: 내부 문제로 비상 정지(ERROR 상태).
                                          # 필드: reason(선택, 문자열), severity(선택, "minor"|"critical" - 없으면 critical로 간주)
MSG_RESET = "RESET"                      # Jetson -> Mega: ERROR에서 복구해 IDLE로 돌아가라는 원격 재시작 요청.
                                          # severity가 "minor"였던 경우에만 유효 - critical이면 Mega가 반드시 무시해야 함.
