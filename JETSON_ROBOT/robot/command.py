# Jetson <-> Mega UART 메시지 상수.
#
# [2026-07-21 UART Protocol v1.0 전면 교체]
# 구버전(type 기반: START_CYCLE/REQUEST_VISION/VISION_RESULT/...)에서
# STREW_VISION UART Communication Protocol Specification v1.0으로 전환.
#
# 핵심 변화:
#   - 필드명 분리: Jetson->Mega는 "cmd", Mega->Jetson은 "event"
#   - STATE->ACK 핸드셰이크: Mega는 각 상태 완료를 STATE로 보고하고,
#     Jetson의 ACK(같은 seq)를 받아야 다음 상태로 진행한다.
#   - PING/PONG 하트비트: Jetson이 1초 주기로 PING, Mega는 즉시 PONG.
#     3회 연속 무응답이면 Mega Offline 판정 (기존 120초 침묵 워치독 대체).
#   - VISION_READY: STATE 중 특수 지점. "완료 보고"가 아니라 "AI 요청 동기화 지점".
#     Mega가 촬영 준비 완료(VISION_READY STATE)를 보내면, Jetson이 AI 판독 후
#     TASK(OBSERVE/REPLACE/SKIP)를 내려줘야 Mega가 물리 동작을 시작한다.
#   - cycle_id: RUN에 실린다. AWS task id를 그대로 쓴다.
#   - RESUME(복구)은 이번 범위에서 제외 - 다음 단계에서 별도 구현.

# ---- Jetson -> Mega (cmd) ----
CMD_RUN = "RUN"        # 새 Cycle 시작. 필드: cycle_id
CMD_RESUME = "RESUME"  # [미구현/예약] 복구 재개. 필드: cell, task, state
CMD_ACK = "ACK"        # STATE 저장 완료 통보. 필드: seq
CMD_TASK = "TASK"      # AI/관리자가 결정한 작업 전달. 필드: task (OBSERVE/REPLACE/SKIP)
CMD_PING = "PING"      # 하트비트 요청

# ---- Mega -> Jetson (event) ----
EV_READY = "READY"        # 부팅/리셋 완료. Jetson은 이걸 받고 RUN(또는 RESUME)을 보낸다.
EV_STATE = "STATE"        # 상태 완료 보고. 필드: seq, cell, state
EV_COMPLETE = "COMPLETE"  # 현재 Cell 작업 전부 완료
EV_ERROR = "ERROR"        # 내부 런타임 에러. 필드: code
EV_PONG = "PONG"          # PING 응답

# VISION_READY: STATE의 state 값 중 특수 동기화 지점 (AI 요청 트리거).
STATE_VISION_READY = "VISION_READY"

# TASK 종류
TASK_OBSERVE = "OBSERVE"
TASK_REPLACE = "REPLACE"
TASK_SKIP = "SKIP"

# vision.read()의 status -> TASK 매핑 (구 planner.py ACTION_MAP과 동일).
# healthy -> OBSERVE, powdery_mildew/missing_plant -> REPLACE, 그 외 -> SKIP.
STATUS_TO_TASK = {
    "healthy": TASK_OBSERVE,
    "powdery_mildew": TASK_REPLACE,
    "missing_plant": TASK_REPLACE,
}


def status_to_task(status: str) -> str:
    return STATUS_TO_TASK.get(status, TASK_SKIP)
