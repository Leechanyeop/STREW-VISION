/*
  mega_firmware.ino — Arduino Mega2560 펌웨어
  ARDUINO_MEGA2560_프로토콜.md (2026-07-16, 6차 개정) 스펙을 그대로 구현한다.
  6차 개정(ERROR 복구 정책 v6, EEPROM 기반 nextCell 재개)은 하드웨어 배선과 무관하게
  완전히 구현돼 있다 - AVR 내장 EEPROM만 쓰고 별도 센서/배선이 필요 없어서, 아래
  TODO 목록에는 포함되지 않는다.

  ============================================================================
  *** 실제 하드웨어 배선 전 반드시 확인/수정해야 할 것들 (TODO 모아둠) ***
  ============================================================================
  이 펌웨어는 "젯슨이 결정을 안 하고 Mega가 순회/판단/물리 동작을 전부 관리한다"는
  최신 프로토콜의 메시지 흐름과 상태머신은 100% 문서대로 구현했지만, 실제 모터/그리퍼/
  센서 핀 번호와 동작 타이밍은 실물 로봇 배선을 몰라서 채울 수 없다. 아래 표시된
  함수/상수들은 전부 "컴파일은 되지만 아무 물리 동작도 하지 않는" 자리표시자(placeholder)다:
    - PIN 상수 섹션 전체 (아래 "핀 배치 (TODO)" 참고)
    - moveToCell(), returnToHome() : 실제 이동 로직 없음 - 시간만 흉내냄
    - pickOldPot(), dropOldPot(), pickNewPot(), placeNewPot() : 그리퍼/서보 제어 없음
    - positionCamera(), performInspection() : 카메라 자세 정렬 없음(카메라 자체는 Jetson이
      REQUEST_VISION/VISION_RESULT로 대신 처리하므로 여기선 자세만 잡으면 됨)
    - checkForHardwareFault() : 항상 false 반환 - 실제 센서(전류/엔코더/리밋스위치 등)가
      하나도 없다고 확인된 상태라 ERROR로 전환할 근거 자체가 없음(문서 참고). 나중에
      센서가 추가되면 여기서 감지 로직을 채우면 된다.
  이 파일을 실제 로봇에 올리기 전에 위 함수들부터 실제 배선에 맞게 채워 넣을 것.
  ============================================================================
*/

#include <ArduinoJson.h>
#include <EEPROM.h>
// #include <Servo.h>  // 그리퍼/서보를 실제로 쓰게 되면 주석 해제

// LCD가 실제로 배선돼 있지 않다면 0으로 바꾸면 LCD 관련 코드가 전부 빠진다.
// (구버전 스케치가 LiquidCrystal_I2C를 썼던 걸 그대로 이어받되, 최신 프로토콜엔
// LCD 언급이 전혀 없어서 옵션으로 뺐다 - 실제 하드웨어에 LCD가 없으면 0으로.)
#define USE_LCD 1
#if USE_LCD
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#define LCD_ADDR 0x27
LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);
#endif

// ============================================================================
// 핀 배치 (TODO — 실제 배선에 맞게 반드시 수정)
// ============================================================================
// 아래는 전부 예시값이다. 실제 모터 드라이버/서보/리밋스위치가 연결된 핀 번호로
// 바꿔야 한다. 지금은 어떤 핀도 실제로 의미 있게 쓰이지 않는다(placeholder 함수들이
// 시간 지연만 흉내내고 있어서).
const int PIN_MOTOR_STEP = 2;   // TODO: 실제 스텝 모터 STEP 핀
const int PIN_MOTOR_DIR = 3;    // TODO: 실제 스텝 모터 DIR 핀
const int PIN_GRIPPER_SERVO = 9; // TODO: 실제 그리퍼 서보 핀

// ============================================================================
// 새 프로토콜 메시지 타입 문자열 (robot/command.py의 MSG_* 상수와 정확히 일치해야 함)
// ============================================================================
const char* const MSG_START_CYCLE = "START_CYCLE";
const char* const MSG_REQUEST_VISION = "REQUEST_VISION";
const char* const MSG_VISION_RESULT = "VISION_RESULT";
const char* const MSG_REPORT_RESULT = "REPORT_RESULT";
const char* const MSG_PROGRESS_UPDATE = "PROGRESS_UPDATE";
const char* const MSG_CYCLE_COMPLETE = "CYCLE_COMPLETE";
const char* const MSG_ERROR = "ERROR";

// ============================================================================
// Mega 상위 동작 상태 (문서 표 그대로: IDLE / RUN / ERROR)
// ============================================================================
enum MegaMode { MODE_IDLE, MODE_RUN, MODE_ERROR };
MegaMode megaMode = MODE_IDLE;

// 순회 진행 단계 (RUN 상태 내부에서만 의미 있음). 셀 하나를 처리하는 하위 단계들.
enum CycleStep {
  STEP_MOVE_TO_CELL,     // 대상 셀로 이동 중
  STEP_AWAIT_VISION,     // REQUEST_VISION 보내고 VISION_RESULT 기다리는 중
  STEP_EXECUTE_ACTION,   // OBSERVE/REPLACE/SKIP 물리 동작 수행 중
  STEP_REPORT_RESULT,    // 이 셀 결과를 REPORT_RESULT로 보고
  STEP_ADVANCE_OR_HOME,  // 다음 셀로 넘어가거나(4번 끝났으면) 초기 위치 복귀
};
CycleStep cycleStep = STEP_MOVE_TO_CELL;

// [2026-07-15 아키텍처] robot/planner.py의 ACTION_MAP을 그대로 포팅한 것.
// healthy -> OBSERVE, powdery_mildew/missing_plant -> REPLACE, 그 외(empty_cell 등) -> SKIP.
enum ExecuteTask { TASK_OBSERVE, TASK_REPLACE, TASK_SKIP };

// 물리 동작 하위 상태머신(OBSERVE/REPLACE/SKIP). 문서의 "구버전 상태머신" 표에 있던
// state 이름/progress 값을 그대로 재사용한다 - 관리자 대시보드/로그에서 계속 보던
// 값이라 굳이 새로 정의하지 않고 문서와 100% 맞춰 이어받음.
enum ActionState {
  ST_RECEIVED,
  ST_MOVE_TO_CELL,
  ST_POSITION_CAMERA,
  ST_INSPECTION,
  ST_RETURN_HOME_ACTION,
  ST_PICK_OLD_POT,
  ST_MOVE_TO_DISPOSAL,
  ST_DROP_OLD_POT,
  ST_MOVE_TO_NEW_POT,
  ST_PICK_NEW_POT,
  ST_PLACE_NEW_POT,
  ST_SKIPPED,
  ST_COMPLETE,
};

// 현재 순회 중인 셀 번호(1~4), 현재 vision 판독값, 현재 execute_task, 하위 상태.
int currentCell = 1;
const int TOTAL_CELLS = 4;
String currentVisionStatus = "";
ExecuteTask currentExecuteTask = TASK_SKIP;
ActionState currentActionState = ST_RECEIVED;
unsigned long actionStepStartMs = 0;

// ============================================================================
// [2026-07-16 6차 개정] ERROR 복구 정책 v6 — EEPROM에 "다음에 시작할 셀 번호"만 저장.
// ============================================================================
// 왜 "현재 위치"가 아니라 "다음 셀 번호"를 저장하는가: 지금 하드웨어엔 엔코더/절대
// 위치 센서/토크 센서가 하나도 없어서, 모터 스텝 수나 서보 각도를 EEPROM에 저장해봤자
// 리셋 후 그게 실제 물리적으로 맞는 위치인지 확인할 방법이 없다. 반면 "다음엔 몇 번
// 셀부터 하면 되는지"는 순수 논리 상태라 신뢰할 수 있고, 재개 시 HOME부터 다시 이동해서
// 그 셀 작업을 처음부터(비전 재확인 포함) 다시 하면 되므로 안전하다.
//
// v5(이전) 방식: ERROR -> 리셋 -> 항상 Cell1부터 재시작. 가장 단순하지만 Cell3에서
// 오류가 나도 Cell1, Cell2를 다시 해야 하는 낭비가 있었다.
// v6(이번 개정): 셀 하나가 "정상적으로 완료"될 때마다(REPORT_RESULT 전송 직후) EEPROM에
// nextCell을 갱신한다. ERROR로 리셋돼도 setup()에서 이 값을 읽어 그 셀부터 재개한다.
const int EEPROM_ADDR_NEXT_CELL = 0;

// 한 번도 쓴 적 없는 EEPROM은 보통 0xFF(255)로 읽힌다(공장 출고 상태) - 이 경우나
// 값이 1~TOTAL_CELLS 범위를 벗어나면(깨졌거나 첫 부팅) 안전하게 1번부터 시작한다.
// v6 설계 문서엔 이 폴백이 명시돼 있지 않았는데, 첫 부팅 시 255를 셀 번호로 잘못
// 쓰지 않도록 반드시 필요해서 추가함.
uint8_t loadNextCellFromEeprom() {
  uint8_t value = EEPROM.read(EEPROM_ADDR_NEXT_CELL);
  if (value < 1 || value > TOTAL_CELLS) {
    return 1;
  }
  return value;
}

// EEPROM.write() 대신 EEPROM.update()를 쓴다 - 값이 이전과 같으면 실제 쓰기를
// 건너뛴다. AVR EEPROM은 주소당 쓰기 수명이 약 10만 회로 한정돼 있어서(같은 셀에서
// 반복적으로 ERROR가 나 같은 nextCell 값을 계속 쓰는 경우 등), 공짜로 얻는 수명
// 절약책이라 기본으로 적용한다.
void saveNextCellToEeprom(uint8_t nextCell) {
  EEPROM.update(EEPROM_ADDR_NEXT_CELL, nextCell);
}

// [2026-07-16 5차 개정 — 핵심] REQUEST_VISION을 보낸 뒤 VISION_RESULT를 기다리는 동안
// 절대 자체 타임아웃으로 ERROR 전환하면 안 된다 - 병해충 의심 판독이면 관리자 응답을
// 기다리느라 수 분 이상 걸리는 게 정상이기 때문(문서 "병해충 의심 판단 대기" 절 참고).
// VISION_RESULT_SELF_TIMEOUT_MS를 0으로 두면 "자체 타임아웃 없음"(문서 권장 방식) -
// 정 필요하면 최소 30분(1800000ms) 이상의 아주 넉넉한 값으로만 설정할 것.
const unsigned long VISION_RESULT_SELF_TIMEOUT_MS = 0;  // 0 = 타임아웃 없음 (권장)
unsigned long visionRequestSentMs = 0;

// ============================================================================
// 시리얼 한 줄 읽기 (non-blocking) - '\n' 올 때까지 버퍼에 계속 쌓는다.
// Serial.readline()류의 블로킹 함수를 안 쓰는 이유: REQUEST_VISION 응답을 몇 분씩
// 기다릴 수도 있는데, 그동안 loop()가 멈춰있으면 안 되기 때문(물리 동작 진행,
// PROGRESS_UPDATE 전송 등도 계속 돌아가야 함).
// ============================================================================
const int SERIAL_BUF_SIZE = 256;
char serialBuf[SERIAL_BUF_SIZE];
int serialBufLen = 0;

// 한 줄이 완성되면 true를 반환하고 line에 담아준다(개행 문자 제외).
bool readSerialLine(String& line) {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      serialBuf[serialBufLen] = '\0';
      line = String(serialBuf);
      serialBufLen = 0;
      return true;
    }
    if (c != '\r' && serialBufLen < SERIAL_BUF_SIZE - 1) {
      serialBuf[serialBufLen++] = c;
    }
    // 버퍼가 꽉 찼는데 개행이 안 오면 그냥 계속 덮어쓰지 않고 버림(방어적) -
    // 비정상적으로 긴 줄은 무시하고 다음 줄을 기다린다.
  }
  return false;
}

// ============================================================================
// 전송 헬퍼 - packet.py의 encode_packet()과 동일한 형식(구분자 없는 압축 JSON + '\n')
// ============================================================================
void sendTyped(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}

void sendRequestVision() {
  StaticJsonDocument<64> doc;
  doc["type"] = MSG_REQUEST_VISION;
  sendTyped(doc);
  visionRequestSentMs = millis();
}

void sendProgressUpdate(const char* target, const char* state, int progress) {
  StaticJsonDocument<192> doc;
  doc["type"] = MSG_PROGRESS_UPDATE;
  doc["target"] = target;
  doc["state"] = state;
  doc["progress"] = progress;
  sendTyped(doc);
}

void sendReportResult(const char* target, const char* executeTaskStr, const char* completion, bool success) {
  StaticJsonDocument<192> doc;
  doc["type"] = MSG_REPORT_RESULT;
  doc["target"] = target;
  doc["execute_task"] = executeTaskStr;
  doc["completion"] = completion;
  doc["success"] = success;
  sendTyped(doc);
}

void sendCycleComplete() {
  StaticJsonDocument<64> doc;
  doc["type"] = MSG_CYCLE_COMPLETE;
  sendTyped(doc);
}

void sendError(const char* reason) {
  StaticJsonDocument<192> doc;
  doc["type"] = MSG_ERROR;
  doc["reason"] = reason;
  sendTyped(doc);
}

// ============================================================================
// 레거시(구버전) 수동 점검용 명령 응답 - 프로토콜 문서상 "지금도 유효"로 명시된 부분.
// {"status": "...", "command": "..."} 단발 응답 형식 그대로 유지.
// ============================================================================
void sendLegacyResponse(const char* status, const char* command) {
  StaticJsonDocument<128> response;
  response["status"] = status;
  response["command"] = command;
  serializeJson(response, Serial);
  Serial.println();
}

#if USE_LCD
void showMessage(const char* line1, const char* line2) {
  lcd.clear();
  lcd.setCursor(0, 0);
  lcd.print(line1);
  lcd.setCursor(0, 1);
  lcd.print(line2);
}
#endif

// ============================================================================
// 물리 동작 placeholder들 - 위 파일 상단 TODO 참고. 지금은 시간만 흉내낸다.
// ============================================================================
void moveToCell(int cellIndex) { /* TODO: 실제 셀 위치로 이동하는 모터 제어 */ }
void returnToHome() { /* TODO: 실제 초기 위치 복귀 모터 제어 */ }
void positionCamera() { /* TODO: 카메라 검사 자세로 정렬 */ }
void performInspection() { /* TODO: 정밀 검사(필요시 6축 제어) */ }
void pickOldPot() { /* TODO: 기존 화분 집기(그리퍼 제어) */ }
void dropOldPot() { /* TODO: 폐기 위치에 내려놓기 */ }
void pickNewPot() { /* TODO: 새 화분 집기 */ }
void placeNewPot() { /* TODO: 대상 셀에 새 화분 배치 */ }

// 실제 하드웨어에 전류 센서/엔코더/리밋스위치가 없다고 확인된 상태 - 항상 false.
// (문서 "ERROR 복구 방법" 절 참고: 물리 상태를 확인할 방법이 없어서 severity 구분
// 자체를 포기한 설계. 나중에 센서가 추가되면 여기서 실제 감지 로직을 채울 것.)
bool checkForHardwareFault() { return false; }

// ============================================================================
// ACTION_MAP 포팅 (robot/planner.py의 ACTION_MAP과 정확히 동일한 매핑)
// ============================================================================
ExecuteTask mapStatusToAction(const String& status) {
  if (status == "healthy") return TASK_OBSERVE;
  if (status == "powdery_mildew") return TASK_REPLACE;
  if (status == "missing_plant") return TASK_REPLACE;
  return TASK_SKIP;  // empty_cell 등 매핑 안 된 값은 전부 SKIP (문서 표 그대로)
}

const char* executeTaskToString(ExecuteTask t) {
  switch (t) {
    case TASK_OBSERVE: return "OBSERVE";
    case TASK_REPLACE: return "REPLACE";
    default: return "SKIP";
  }
}

// 셀 라벨 문자열 (target 필드용) - "cell_1"~"cell_4"
String cellLabel(int cellIndex) {
  return "cell_" + String(cellIndex);
}

// ============================================================================
// OBSERVE/REPLACE/SKIP 하위 상태머신 진행 (non-blocking, millis() 기반)
// 문서의 구버전 상태머신 표(state/progress)를 그대로 재사용한다.
// 각 단계는 STEP_DURATION_MS만큼 "물리 동작을 흉내내는 시간"을 쓴 뒤 다음 단계로
// 넘어간다 - 실제 배선 후에는 이 시간 대신 실제 센서/완료 신호로 다음 단계로
// 넘어가도록 바꾸는 게 정석이다(지금은 순수 placeholder).
// ============================================================================
const unsigned long STEP_DURATION_MS = 500;  // TODO: 실제 동작 시간에 맞게 조정

bool advanceActionStateMachine() {
  // true를 반환하면 이 셀의 물리 동작이 전부 끝난 것(다음 단계인 REPORT_RESULT로 넘어감).
  unsigned long elapsed = millis() - actionStepStartMs;
  if (elapsed < STEP_DURATION_MS) return false;  // 아직 이 단계 진행 중

  String target = cellLabel(currentCell);

  if (currentExecuteTask == TASK_SKIP) {
    // SKIP 상태머신: RECEIVED(0) -> SKIPPED(100)
    if (currentActionState == ST_RECEIVED) {
      currentActionState = ST_SKIPPED;
      sendProgressUpdate(target.c_str(), "SKIPPED", 100);
      actionStepStartMs = millis();
      return true;  // SKIP은 물리 동작이 없으므로 바로 완료
    }
  } else if (currentExecuteTask == TASK_OBSERVE) {
    // OBSERVE 상태머신 표 그대로: RECEIVED(0) -> MOVE_TO_CELL(20) -> POSITION_CAMERA(40)
    // -> INSPECTION(70) -> RETURN_HOME(90) -> COMPLETE(100)
    switch (currentActionState) {
      case ST_RECEIVED:
        currentActionState = ST_MOVE_TO_CELL;
        sendProgressUpdate(target.c_str(), "MOVE_TO_CELL", 20);
        break;
      case ST_MOVE_TO_CELL:
        positionCamera();
        currentActionState = ST_POSITION_CAMERA;
        sendProgressUpdate(target.c_str(), "POSITION_CAMERA", 40);
        break;
      case ST_POSITION_CAMERA:
        performInspection();
        currentActionState = ST_INSPECTION;
        sendProgressUpdate(target.c_str(), "INSPECTION", 70);
        break;
      case ST_INSPECTION:
        currentActionState = ST_RETURN_HOME_ACTION;
        sendProgressUpdate(target.c_str(), "RETURN_HOME", 90);
        break;
      case ST_RETURN_HOME_ACTION:
        currentActionState = ST_COMPLETE;
        sendProgressUpdate(target.c_str(), "COMPLETE", 100);
        actionStepStartMs = millis();
        return true;
      default:
        break;
    }
  } else if (currentExecuteTask == TASK_REPLACE) {
    // REPLACE 상태머신 표 그대로: RECEIVED(0) -> MOVE_TO_CELL(10) -> PICK_OLD_POT(25)
    // -> MOVE_TO_DISPOSAL(40) -> DROP_OLD_POT(50) -> MOVE_TO_NEW_POT(60)
    // -> PICK_NEW_POT(75) -> PLACE_NEW_POT(90) -> COMPLETE(100)
    switch (currentActionState) {
      case ST_RECEIVED:
        currentActionState = ST_MOVE_TO_CELL;
        sendProgressUpdate(target.c_str(), "MOVE_TO_CELL", 10);
        break;
      case ST_MOVE_TO_CELL:
        pickOldPot();
        currentActionState = ST_PICK_OLD_POT;
        sendProgressUpdate(target.c_str(), "PICK_OLD_POT", 25);
        break;
      case ST_PICK_OLD_POT:
        currentActionState = ST_MOVE_TO_DISPOSAL;
        sendProgressUpdate(target.c_str(), "MOVE_TO_DISPOSAL", 40);
        break;
      case ST_MOVE_TO_DISPOSAL:
        dropOldPot();
        currentActionState = ST_DROP_OLD_POT;
        sendProgressUpdate(target.c_str(), "DROP_OLD_POT", 50);
        break;
      case ST_DROP_OLD_POT:
        currentActionState = ST_MOVE_TO_NEW_POT;
        sendProgressUpdate(target.c_str(), "MOVE_TO_NEW_POT", 60);
        break;
      case ST_MOVE_TO_NEW_POT:
        pickNewPot();
        currentActionState = ST_PICK_NEW_POT;
        sendProgressUpdate(target.c_str(), "PICK_NEW_POT", 75);
        break;
      case ST_PICK_NEW_POT:
        placeNewPot();
        currentActionState = ST_PLACE_NEW_POT;
        // TODO: 실제 포토센서로 배치 확인 - 지금은 항상 성공으로 간주.
        sendProgressUpdate(target.c_str(), "PLACE_NEW_POT", 90);
        break;
      case ST_PLACE_NEW_POT:
        currentActionState = ST_COMPLETE;
        sendProgressUpdate(target.c_str(), "COMPLETE", 100);
        actionStepStartMs = millis();
        return true;
      default:
        break;
    }
  }

  actionStepStartMs = millis();
  return false;
}

// ============================================================================
// 순회(RUN) 상태머신 진행 - loop()에서 매번 호출된다.
// ============================================================================
void runCycleStep() {
  // ERROR 감지는 어느 단계에서든 즉시 우선 - 문서: "RUN/IDLE 무관하게 즉시 전환".
  if (checkForHardwareFault()) {
    megaMode = MODE_ERROR;
    sendError("hardware fault detected");
    return;
  }

  switch (cycleStep) {
    case STEP_MOVE_TO_CELL:
      moveToCell(currentCell);
      cycleStep = STEP_AWAIT_VISION;
      sendRequestVision();
      break;

    case STEP_AWAIT_VISION:
      // VISION_RESULT는 handleIncomingLine()에서 도착하는 즉시 처리되고 cycleStep을
      // STEP_EXECUTE_ACTION으로 바꿔준다 - 여기서는 그냥 "왔는지" 기다리기만 한다.
      // [핵심] 여기서 자체 타임아웃으로 ERROR 전환하지 않는다(위 상수 설명 참고) -
      // VISION_RESULT_SELF_TIMEOUT_MS가 0보다 크게 설정된 경우에만(권장하지 않음,
      // 반드시 30분 이상) 아주 예외적으로 타임아웃 처리한다.
      if (VISION_RESULT_SELF_TIMEOUT_MS > 0 &&
          millis() - visionRequestSentMs > VISION_RESULT_SELF_TIMEOUT_MS) {
        megaMode = MODE_ERROR;
        sendError("VISION_RESULT self-timeout exceeded (check VISION_RESULT_SELF_TIMEOUT_MS setting)");
      }
      break;

    case STEP_EXECUTE_ACTION:
      if (advanceActionStateMachine()) {
        cycleStep = STEP_REPORT_RESULT;
      }
      break;

    case STEP_REPORT_RESULT: {
      String target = cellLabel(currentCell);
      const char* completion = (currentExecuteTask == TASK_SKIP) ? "SKIPPED" : "COMPLETE";
      sendReportResult(target.c_str(), executeTaskToString(currentExecuteTask), completion, true);
      cycleStep = STEP_ADVANCE_OR_HOME;
      break;
    }

    case STEP_ADVANCE_OR_HOME:
      // [2026-07-16 6차 개정] 이 셀이 방금 STEP_REPORT_RESULT에서 REPORT_RESULT로
      // "정상 완료" 보고까지 끝난 직후이므로, 여기서 EEPROM에 다음 셀 번호를 갱신한다.
      // (설계 문서: "셀 하나의 작업이 정상적으로 완료된 직후에만 갱신" - 모터가 움직일
      // 때마다가 아니라 딱 이 시점 한 곳에서만 쓴다.)
      if (currentCell >= TOTAL_CELLS) {
        returnToHome();
        saveNextCellToEeprom(1);
        sendCycleComplete();
        megaMode = MODE_IDLE;
        currentCell = 1;
        cycleStep = STEP_MOVE_TO_CELL;
      } else {
        currentCell++;
        saveNextCellToEeprom((uint8_t)currentCell);
        currentActionState = ST_RECEIVED;
        cycleStep = STEP_MOVE_TO_CELL;
      }
      break;
  }
}

// ============================================================================
// 수신 메시지 처리
// ============================================================================
void handleIncomingLine(const String& line) {
  StaticJsonDocument<256> doc;
  DeserializationError err = deserializeJson(doc, line);

  if (err) {
    // [문서 "알려진 미해결 사항" 권장사항] 새 프로토콜 메시지 파싱 실패 시 그냥 무시하고
    // 다음 줄을 기다린다 - 레거시 명령({"command":...})과 달리 여기선 응답을 강제하지 않음.
    Serial.print(F("[WARN] JSON parse failed, ignoring line: "));
    Serial.println(line);
    return;
  }

  // 레거시 수동 점검용 명령 ({"command": "..."}) - 새 프로토콜({"type": "..."})과
  // 필드명으로 구분된다. 문서: "이번 개정과 무관하므로 그대로 유지".
  if (doc.containsKey("command")) {
    handleLegacyCommand(doc);
    return;
  }

  if (!doc.containsKey("type")) {
    return;  // 둘 다 아니면 무시
  }

  const char* type = doc["type"];

  if (strcmp(type, MSG_START_CYCLE) == 0) {
    if (megaMode == MODE_IDLE) {
      megaMode = MODE_RUN;
      // [2026-07-16 6차 개정] currentCell을 여기서 1로 강제 리셋하지 않는다 -
      // setup()에서 이미 EEPROM으로부터 "다음에 할 셀"을 로드해뒀다(정상 완료 후
      // 재부팅이면 1, ERROR 복구라면 마지막 완료 셀의 다음 번호). Jetson은 여전히
      // 셀 번호 없이 START_CYCLE만 보내면 되고, 어느 셀부터 시작할지는 전부
      // Mega가 EEPROM을 보고 스스로 판단한다.
      currentActionState = ST_RECEIVED;
      cycleStep = STEP_MOVE_TO_CELL;
      actionStepStartMs = millis();
    }
    // RUN/ERROR 중에 또 START_CYCLE이 오면 무시 - Jetson 쪽 cycle_active 플래그가
    // 이미 중복 전송을 막고 있지만, 방어적으로 여기서도 한 번 더 막는다.

  } else if (strcmp(type, MSG_VISION_RESULT) == 0) {
    if (megaMode == MODE_RUN && cycleStep == STEP_AWAIT_VISION) {
      currentVisionStatus = String((const char*)doc["status"]);
      currentExecuteTask = mapStatusToAction(currentVisionStatus);
      currentActionState = ST_RECEIVED;
      actionStepStartMs = millis();
      cycleStep = STEP_EXECUTE_ACTION;
    }
    // AWAIT_VISION 상태가 아닐 때 온 VISION_RESULT는 타이밍이 어긋난 것이라 무시.
  }
  // REQUEST_VISION/PROGRESS_UPDATE/REPORT_RESULT/CYCLE_COMPLETE/ERROR는 전부
  // Mega -> Jetson 방향이라 여기(Mega 수신 처리)에서 받을 일이 없다.
}

// ============================================================================
// 레거시 수동 점검용 명령 처리 (문서 "레거시 수동 점검용 명령" 표 그대로)
// ============================================================================
void handleLegacyCommand(JsonDocument& doc) {
  const char* command = doc["command"];

  if (strcmp(command, "PING") == 0) {
    sendLegacyResponse("PONG", command);
  } else if (strcmp(command, "STATUS") == 0) {
    sendLegacyResponse("READY", command);
  } else if (strcmp(command, "HOME") == 0) {
    returnToHome();
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "MOVE") == 0) {
    int target = doc["target"] | 0;
#if USE_LCD
    char buf[17];
    snprintf(buf, sizeof(buf), "TARGET:%d", target);
    showMessage(buf, "");
#endif
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "STOP") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "SERVO") == 0) {
    int angle = doc["angle"] | 0;
#if USE_LCD
    char buf[17];
    snprintf(buf, sizeof(buf), "ANGLE:%d", angle);
    showMessage(buf, "");
#endif
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "GRIP_OPEN") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "GRIP_CLOSE") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "WATER") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "NUTRITION") == 0) {
    sendLegacyResponse("DONE", command);  // 실제 펌프 하드웨어 없음(문서 비고 그대로)
  } else if (strcmp(command, "PUMP_ON") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "PUMP_OFF") == 0) {
    sendLegacyResponse("DONE", command);
  } else if (strcmp(command, "LED") == 0) {
    sendLegacyResponse("DONE", command);
  } else {
    sendLegacyResponse("UNKNOWN_COMMAND", command);
  }
}

// ============================================================================
// setup() / loop()
// ============================================================================
void setup() {
  Serial.begin(115200);  // config/settings.py의 ARDUINO_BAUDRATE 기본값과 반드시 일치해야 함

  pinMode(PIN_MOTOR_STEP, OUTPUT);
  pinMode(PIN_MOTOR_DIR, OUTPUT);

#if USE_LCD
  lcd.init();
  lcd.backlight();
  showMessage("STREW ROBOT", "READY");
#endif

  megaMode = MODE_IDLE;
  // [2026-07-16 6차 개정] 부팅 시 EEPROM에서 "다음에 시작할 셀"을 읽어온다 - 정상
  // 종료 후 재부팅이면 1(마지막에 저장해둔 값), ERROR로 리셋된 거라면 마지막으로
  // 완료된 셀의 다음 번호가 된다. START_CYCLE이 오면 이 값 그대로 이어서 쓴다
  // (아래 handleIncomingLine의 MSG_START_CYCLE 분기에서 currentCell을 따로
  // 1로 되돌리지 않는 이유).
  currentCell = loadNextCellFromEeprom();
  cycleStep = STEP_MOVE_TO_CELL;
}

void loop() {
  String line;
  if (readSerialLine(line)) {
    handleIncomingLine(line);
  }

  // ERROR 상태에서는 그 무엇도 하지 않는다 - 문서: "원격으로 소프트웨어만으로 재시작하는
  // 방법은 없다. 사람이 로봇을 직접 확인하고 전원을 재시작해야만 복구된다."
  if (megaMode == MODE_ERROR) {
    return;
  }

  if (megaMode == MODE_RUN) {
    runCycleStep();
  }
  // MODE_IDLE일 땐 START_CYCLE이 올 때까지 그냥 대기(위 handleIncomingLine에서 처리).
}
