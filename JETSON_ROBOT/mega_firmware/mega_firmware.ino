/*
  mega_firmware.ino — Arduino Mega2560 펌웨어
  STREW_VISION UART Communication Protocol Specification v1.0 (2026-07-21) 구현.

  ============================================================================
  프로토콜 v1.0 요약 (구버전 type 기반에서 전면 교체)
  ============================================================================
  - 필드 분리: Jetson->Mega = "cmd", Mega->Jetson = "event"
  - 부팅 시 READY 전송 -> Jetson이 RUN(cycle_id)으로 응답
  - 모든 상태 완료는 STATE(seq) 보고 -> Jetson ACK(seq)를 받아야 다음 진행
  - VISION_READY STATE는 "완료 보고"가 아니라 "AI 요청 동기화 지점":
    Jetson이 AI 판독 후 TASK(OBSERVE/REPLACE/SKIP)를 내려줘야 물리 동작 시작
  - PING -> 즉시 PONG (하트비트, Jetson이 1초 주기로 확인)
  - Cell 작업 끝나면 COMPLETE, 내부 오류는 ERROR(code)
  - [2026-07-25 Phase B] RESUME(복구): EEPROM을 쓰지 않는다. 복구 기준은 Jetson SQLite.
    부팅 시 READY만 보내고, Jetson이 SQLite를 보고 RUN(새 Cycle, cell 1부터) 또는
    RESUME(cell 지정, 셀 단위 재개)을 결정해서 내려준다. Mega는 상태를 저장하지 않는다.

  ============================================================================
  *** 실제 하드웨어 배선 전 반드시 채워야 할 placeholder (변경 없음) ***
  ============================================================================
 // moveToCell/returnToHome/positionCamera/performInspection/pick*///drop/place 및
 //checkForHardwareFault()는 실제 배선 전까지 시간만 흉내내는 자리표시자다.
  //============================================================================


#include <ArduinoJson.h>
// [2026-07-25 Phase B] EEPROM 제거. 복구 상태는 Jetson SQLite가 관리한다(Source of Truth).

#define USE_LCD 1
#if USE_LCD
#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#define LCD_ADDR 0x27
LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);
#endif

// ---- 핀 배치 (TODO: 실제 배선에 맞게 수정) ----
const int PIN_MOTOR_STEP = 2;
const int PIN_MOTOR_DIR = 3;
const int PIN_GRIPPER_SERVO = 9;

// ============================================================================
// 프로토콜 v1.0 메시지 문자열 (robot/command.py와 정확히 일치)
// ============================================================================
// Jetson -> Mega (cmd)
const char* const CMD_RUN = "RUN";
const char* const CMD_RESUME = "RESUME";
const char* const CMD_ACK = "ACK";
const char* const CMD_TASK = "TASK";
const char* const CMD_PING = "PING";
// [Phase C 설계 결정] NEXT_VIEW 없음. Mega가 4 View(TOP/LEFT/RIGHT/FRONT)를 고정 순서로
// 자체 순회한다. 각 View마다 VISION_READY(view) 전송 후 ACK를 받으면 다음 View로 넘어가고,
// 마지막 View에서는 ACK와 함께 온 TASK로 이 셀의 물리 동작을 시작한다.
// Mega -> Jetson (event)
const char* const EV_READY = "READY";
const char* const EV_STATE = "STATE";
const char* const EV_COMPLETE = "COMPLETE";
const char* const EV_ERROR = "ERROR";
const char* const EV_PONG = "PONG";
// STATE의 state 값
const char* const STATE_MOVE_CELL = "MOVE_CELL";
const char* const STATE_VISION_READY = "VISION_READY";
const char* const STATE_TASK_DONE = "TASK_DONE";

// [Phase C] Multi-View Inspection: 모든 Cell에서 항상 이 View들을 순서대로 촬영한다.
// (robot/command.py의 INSPECTION_VIEWS와 일치해야 함.)
const char* const INSPECTION_VIEWS[] = {"TOP", "LEFT", "RIGHT", "FRONT"};
const int VIEW_COUNT = 4;

// ============================================================================
// 상위 동작 모드
// ============================================================================
enum MegaMode { MODE_IDLE, MODE_RUN, MODE_ERROR };
MegaMode megaMode = MODE_IDLE;

// Cell 하나를 처리하는 순회 단계.
enum CycleStep {
  CS_MOVE_TO_CELL,     // 셀로 이동 후 STATE(MOVE_CELL) 전송
  CS_WAIT_MOVE_ACK,    // MOVE_CELL ACK 대기
  CS_MOVE_TO_VIEW,     // [Phase C] 현재 View 위치로 카메라 이동 후 STATE(VISION_READY, view)
  CS_WAIT_VIEW_ACK,    // [Phase C] 이 View의 ACK 대기. 마지막 View면 TASK도 함께 기다림.
  CS_EXECUTE_ACTION,   // OBSERVE/REPLACE/SKIP 물리 동작 (내부 진행)
  CS_SEND_DONE,        // STATE(TASK_DONE) 전송
  CS_WAIT_DONE_ACK,    // TASK_DONE ACK 대기
  CS_ADVANCE,          // 다음 셀 or COMPLETE 후 순회 종료
};
CycleStep cycleStep = CS_MOVE_TO_CELL;

enum ExecuteTask { TASK_OBSERVE, TASK_REPLACE, TASK_SKIP };

int currentCell = 1;
const int TOTAL_CELLS = 4;
ExecuteTask currentExecuteTask = TASK_SKIP;

// [Phase C] 현재 셀에서 몇 번째 View를 촬영 중인지 (0-based).
int currentViewIndex = 0;

// ---- STATE/ACK 핸드셰이크 ----
long seqCounter = 0;      // STATE마다 증가
long pendingSeq = -1;     // 지금 ACK를 기다리는 seq (-1이면 대기 안 함)
bool taskReceived = false;

// ---- 물리 동작 내부 타이밍 ----
const unsigned long ACTION_TOTAL_MS = 2500;  // TODO: 실제 동작 시간
unsigned long actionStartMs = 0;

// [2026-07-25 Phase B] 지정한 셀부터 순회를 시작한다(RUN=1부터, RESUME=cell부터).
// 셀 단위 재개: 셀 중간 스텝은 복원하지 않고 그 셀을 처음(MOVE_CELL)부터 다시 한다.
// (위치/암커더 센서가 없어 셀 중간 물리 위치 복원이 불가하므로 셀 처음부터가 안전.)
void startCycleFromCell(int cell) {
  currentCell = (cell < 1 || cell > TOTAL_CELLS) ? 1 : cell;
  megaMode = MODE_RUN;
  cycleStep = CS_MOVE_TO_CELL;
  pendingSeq = -1;
  taskReceived = false;
}

// ============================================================================
// 시리얼 한 줄 읽기 (non-blocking)
// ============================================================================
const int SERIAL_BUF_SIZE = 256;
char serialBuf[SERIAL_BUF_SIZE];
int serialBufLen = 0;
bool readSerialLine(String& line) {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();
    if (c == '\n') {
      serialBuf[serialBufLen] = '\0';
      line = String(serialBuf);
      serialBufLen = 0;
      return true;
    }
    if (c != '\r' && serialBufLen < SERIAL_BUF_SIZE - 1) serialBuf[serialBufLen++] = c;
  }
  return false;
}

// ============================================================================
// 전송 헬퍼 (압축 JSON + '\n')
// ============================================================================
void sendDoc(JsonDocument& doc) {
  serializeJson(doc, Serial);
  Serial.print('\n');
}
void sendReady() {
  StaticJsonDocument<64> d; d["event"] = EV_READY; sendDoc(d);
}
void sendPong() {
  StaticJsonDocument<64> d; d["event"] = EV_PONG; sendDoc(d);
}
void sendComplete() {
  StaticJsonDocument<64> d; d["event"] = EV_COMPLETE; d["cell"] = currentCell; sendDoc(d);
}
void sendError(const char* code) {
  StaticJsonDocument<96> d; d["event"] = EV_ERROR; d["code"] = code; sendDoc(d);
}
// STATE 전송 + ACK 대기 시작. 반환한 seq를 pendingSeq로 세팅한다.
long sendState(int cell, const char* state) {
  long seq = ++seqCounter;
  StaticJsonDocument<128> d;
  d["event"] = EV_STATE;
  d["seq"] = seq;
  d["cell"] = cell;
  d["state"] = state;
  sendDoc(d);
  return seq;
}

// [Phase C] View 정보를 포함한 STATE 전송 (VISION_READY 전용).
long sendStateWithView(int cell, const char* state, const char* view) {
  long seq = ++seqCounter;
  StaticJsonDocument<160> d;
  d["event"] = EV_STATE;
  d["seq"] = seq;
  d["cell"] = cell;
  d["state"] = state;
  d["view"] = view;
  sendDoc(d);
  return seq;
}

#if USE_LCD
void showMessage(const char* l1, const char* l2) {
  lcd.clear(); lcd.setCursor(0, 0); lcd.print(l1); lcd.setCursor(0, 1); lcd.print(l2);
}
#else
void showMessage(const char* l1, const char* l2) {}   // LCD 미사용 시 no-op
#endif

// [2026-08-04] 현재 셀/상태를 LCD에 표시. 윗줄 "Cell X/N", 아랫줄 상태 문자열.
void lcdStatus(const char* state) {
  char l1[17];
  snprintf(l1, sizeof(l1), "Cell %d/%d", currentCell, TOTAL_CELLS);
  showMessage(l1, state);
}

// ============================================================================
// 물리 동작 placeholder (실제 배선 전까지 아무 동작 안 함)
// ============================================================================
void moveToCell(int cellIndex) { /* TODO */ }
void returnToHome() { /* TODO */ }
void positionCamera() { /* TODO */ }
// [Phase C] 카메라를 특정 View 자세로 이동 (TOP/LEFT/RIGHT/FRONT). 실제 서보/스텝 제어는 TODO.
void moveToView(const char* view) { /* TODO: view별 카메라 자세 이동 */ }
void executePhysicalTask(ExecuteTask t) { /* TODO: OBSERVE/REPLACE/SKIP별 실제 동작 */ }
bool checkForHardwareFault() { return false; }

ExecuteTask parseTask(const char* taskStr) {
  if (strcmp(taskStr, "OBSERVE") == 0) return TASK_OBSERVE;
  if (strcmp(taskStr, "REPLACE") == 0) return TASK_REPLACE;
  return TASK_SKIP;
}

// ============================================================================
// 순회 진행 (loop에서 호출) - non-blocking
// ============================================================================
void runCycleStep() {
  if (checkForHardwareFault()) {
    megaMode = MODE_ERROR;
    sendError("HARDWARE_FAULT");
    return;
  }

  switch (cycleStep) {
    case CS_MOVE_TO_CELL:
      moveToCell(currentCell);
      lcdStatus("MOVE");                 // LCD: Cell X/N / MOVE
      pendingSeq = sendState(currentCell, STATE_MOVE_CELL);
      cycleStep = CS_WAIT_MOVE_ACK;
      break;

    case CS_WAIT_MOVE_ACK:
      // ACK 도착은 handleIncomingLine에서 pendingSeq를 -1로 풀어준다.
      if (pendingSeq == -1) {
        currentViewIndex = 0;   // [Phase C] 첫 View부터 시작
        cycleStep = CS_MOVE_TO_VIEW;
      }
      break;

    case CS_MOVE_TO_VIEW: {
      // [Phase C] 현재 View 자세로 이동 후 VISION_READY(view) 전송.
      const char* view = INSPECTION_VIEWS[currentViewIndex];
      moveToView(view);
      positionCamera();
      char l2[17]; snprintf(l2, sizeof(l2), "VIEW:%s", view);
      lcdStatus(l2);                     // LCD: Cell X/N / VIEW:TOP
      taskReceived = false;
      pendingSeq = sendStateWithView(currentCell, STATE_VISION_READY, view);
      cycleStep = CS_WAIT_VIEW_ACK;
      break;
    }

    case CS_WAIT_VIEW_ACK:
      // ACK를 받으면 다음 View로 넘어간다. 마지막 View(FRONT)에서는 Jetson이 ACK와 함께
      // TASK도 보내므로, ACK로 View는 끝내되 TASK가 왔으면 물리 동작으로 진입한다.
      if (pendingSeq == -1) {
        if (currentViewIndex < VIEW_COUNT - 1) {
          // 아직 View 남음 -> 다음 View로.
          currentViewIndex++;
          cycleStep = CS_MOVE_TO_VIEW;
        } else if (taskReceived) {
          // 마지막 View + TASK 도착 -> 물리 동작.
          const char* tn = (currentExecuteTask == TASK_OBSERVE) ? "TASK:OBSERVE"
                         : (currentExecuteTask == TASK_REPLACE) ? "TASK:REPLACE" : "TASK:SKIP";
          lcdStatus(tn);                 // LCD: Cell X/N / TASK:REPLACE
          actionStartMs = millis();
          cycleStep = CS_EXECUTE_ACTION;
        }
        // 마지막 View인데 TASK가 아직이면 여기서 계속 대기(pendingSeq는 이미 -1).
      }
      break;

    case CS_EXECUTE_ACTION:
      executePhysicalTask(currentExecuteTask);
      if (millis() - actionStartMs >= ACTION_TOTAL_MS) cycleStep = CS_SEND_DONE;
      break;

    case CS_SEND_DONE:
      pendingSeq = sendState(currentCell, STATE_TASK_DONE);
      cycleStep = CS_WAIT_DONE_ACK;
      break;

    case CS_WAIT_DONE_ACK:
      if (pendingSeq == -1) cycleStep = CS_ADVANCE;
      break;

    case CS_ADVANCE:
      lcdStatus("DONE");                 // LCD: Cell X/N / DONE
      sendComplete();  // 이 셀 완료 통보 (COMPLETE는 ACK 불필요)
      // [2026-07-25 Phase B] EEPROM 저장 제거. 진행 상태는 Jetson SQLite가 관리한다.
      if (currentCell >= TOTAL_CELLS) {
        returnToHome();
        megaMode = MODE_IDLE;
        currentCell = 1;
        cycleStep = CS_MOVE_TO_CELL;
        showMessage("STREW   IDLE", "wait RUN");   // 사이클 끝 -> RUN 대기
      } else {
        currentCell++;
        cycleStep = CS_MOVE_TO_CELL;
      }
      break;
  }
}

// ============================================================================
// 수신 처리
// ============================================================================
void handleIncomingLine(const String& line) {
  StaticJsonDocument<256> doc;
  if (deserializeJson(doc, line)) return;  // 파싱 실패는 조용히 무시

  // 하트비트는 최우선 - 어떤 상태에서든 즉시 PONG.
  const char* cmd = doc["cmd"];
  if (cmd == nullptr) return;

  if (strcmp(cmd, CMD_PING) == 0) {
    sendPong();
    return;
  }

  if (strcmp(cmd, CMD_RUN) == 0) {
    // 새 Cycle: 항상 Cell 1부터. cycle_id는 Jetson이 관리하므로 Mega는 저장 안 함.
    if (megaMode == MODE_IDLE) startCycleFromCell(1);
    return;
  }

  if (strcmp(cmd, CMD_RESUME) == 0) {
    // [2026-07-25 Phase B] 복구 재개: Jetson이 SQLite에서 읽은 cell부터 셀 단위로 재개.
    // 셀 중간 스텝(state)은 복원하지 않는다 - 그 셀을 처음부터 다시 한다(안전).
    if (megaMode == MODE_IDLE) {
      int cell = doc["cell"] | 1;
      startCycleFromCell(cell);
    }
    return;
  }

  if (strcmp(cmd, CMD_ACK) == 0) {
    long seq = doc["seq"] | -1;
    if (seq == pendingSeq) pendingSeq = -1;  // 기다리던 ACK 도착 -> 다음 진행 허용
    return;
  }

  if (strcmp(cmd, CMD_TASK) == 0) {
    // [Phase C] 마지막 View 판정 완료 - 이 셀의 물리 동작을 시작하라는 최종 결정.
    if (megaMode == MODE_RUN && cycleStep == CS_WAIT_VIEW_ACK) {
      const char* taskStr = doc["task"] | "SKIP";
      currentExecuteTask = parseTask(taskStr);
      taskReceived = true;
    }
    return;
  }
}

// ============================================================================
// setup / loop
// ============================================================================
void setup() {
  Serial.begin(115200);  // config/settings.py ARDUINO_BAUDRATE와 일치
  pinMode(PIN_MOTOR_STEP, OUTPUT);
  pinMode(PIN_MOTOR_DIR, OUTPUT);
#if USE_LCD
  lcd.init(); lcd.backlight(); showMessage("STREW ROBOT", "READY");
#endif
  // [2026-07-25 Phase B] 부팅 시 상태를 스스로 복원하지 않는다(EEPROM 없음).
  // 항상 IDLE + Cell 1로 시작하고, 실제 시작 셀은 Jetson의 RUN/RESUME이 결정한다.
  megaMode = MODE_IDLE;
  currentCell = 1;
  cycleStep = CS_MOVE_TO_CELL;

  // 부팅 완료 알림 - Jetson은 이걸 받고 RUN(새 Cycle) 또는 RESUME(복구)을 보낸다.
  delay(200);
  sendReady();
}

void loop() {
  String line;
  if (readSerialLine(line)) handleIncomingLine(line);

  if (megaMode == MODE_ERROR) return;  // 사람이 전원 재시작해야 복구
  if (megaMode == MODE_RUN) runCycleStep();
  // MODE_IDLE: RUN 대기
}
