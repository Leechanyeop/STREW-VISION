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
CMD_RESUME = "RESUME"  # 복구 재개(셀 단위). 필드: cell, task, state
CMD_ACK = "ACK"        # STATE 저장 완료 통보. 필드: seq
CMD_TASK = "TASK"      # 최종 결정 작업 전달 (이 셀의 4 View 촬영 완료 후). 필드: task
CMD_PING = "PING"      # 하트비트 요청
# [Phase C 설계 결정] NEXT_VIEW는 두지 않는다. "항상 4 View 고정 순서" 정책이므로
# Mega가 TOP->LEFT->RIGHT->FRONT를 자체 순회하고, 각 View마다 VISION_READY(view)를
# 보낸 뒤 ACK만 받으면 다음 View로 넘어간다. Jetson은 마지막(4번째) View 후에만 TASK를
# 추가로 내려 종합 판정을 전달한다. Early Stop/가변 View가 필요해지면 그때 Protocol v2.x
# 확장으로 CMD_NEXT_VIEW를 도입한다.

# ---- Mega -> Jetson (event) ----
EV_READY = "READY"        # 부팅/리셋 완료. Jetson은 이걸 받고 RUN(또는 RESUME)을 보낸다.
EV_STATE = "STATE"        # 상태 완료 보고. 필드: seq, cell, state
EV_COMPLETE = "COMPLETE"  # 현재 Cell 작업 전부 완료
EV_ERROR = "ERROR"        # 내부 런타임 에러. 필드: code
EV_PONG = "PONG"          # PING 응답

# VISION_READY: STATE의 state 값 중 특수 동기화 지점 (AI 요청 트리거).
STATE_VISION_READY = "VISION_READY"

# [Phase C] Multi-View Inspection. 모든 Cell은 이 View들을 항상 순서대로 촬영한다.
# (config로 바꿀 수 있게 두되 기본은 4개. Healthy 여부와 무관하게 전부 촬영 - 데이터 일관성.)
INSPECTION_VIEWS = ("TOP", "LEFT", "RIGHT", "FRONT")

# 병해충 의심으로 간주하는 status (관리자 승인 트리거).
DISEASE_STATUSES = ("powdery_mildew",)

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


# 우선순위: 병해충 > missing > empty > healthy. 이 순서로 낮은 값을 "더 심각"으로 본다.
_STATUS_SEVERITY = {
    "powdery_mildew": 0,
    "missing_plant": 1,
    "empty_cell": 2,
    "healthy": 3,
}


def aggregate_views(view_results):
    """[Phase C] 여러 View의 판독 결과를 종합해 최종 status를 정한다.

    정책: 단일 View로 판정하지 않는다. View들 중 "가장 심각한" status를 채택하되,
    같은 status가 여러 개면 그 중 최고 confidence를 대표값으로 삼는다.
    (병해충이 한 View에서라도 잡히면 놓치지 않는다 - 미검출 방지.)

    view_results: [{"view":..,"status":..,"confidence":..}, ...]
    반환: (final_status, best_confidence)
    """
    if not view_results:
        return "healthy", 0.0
    # 가장 심각한(severity 값이 작은) status 선택, 동률이면 confidence 높은 것.
    def key(r):
        sev = _STATUS_SEVERITY.get(r.get("status"), 99)
        conf = r.get("confidence") or 0.0
        return (sev, -conf)
    best = min(view_results, key=key)
    final_status = best.get("status") or "healthy"
    # 최종 status와 같은 View들 중 최고 confidence
    same = [r.get("confidence") or 0.0 for r in view_results if r.get("status") == final_status]
    return final_status, (max(same) if same else 0.0)
