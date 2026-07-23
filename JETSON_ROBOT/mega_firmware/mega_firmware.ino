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
  - RESUME(복구)은 이번 범위 미구현 - 다음 단계 예정

  ============================================================================
  *** 실제 하드웨어 배선 전 반드시 채워야 할 placeholder (변경 없음) ***
  ============================================================================
  moveToCell/returnToHome/positionCamera/performInspection/pick*/drop*/place* 및
  checkForHardwareFault()는 실제 배선 전까지 시간만 흉내내는 자리표시자다.
  ============================================================================
*/

#include <ArduinoJson.h>
#include <EEPROM.h>

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
const char* const CMD_ACK = "ACK";
const char* const CMD_TASK = "TASK";
const char* const CMD_PING = "PING";
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

// ============================================================================
// 상위 동작 모드
// ============================================================================
enum MegaMode { MODE_IDLE, MODE_RUN, MODE_ERROR };
MegaMode megaMode = MODE_IDLE;

// Cell 하나를 처리하는 순회 단계.
enum CycleStep {
  CS_MOVE_TO_CELL,     // 셀로 이동 후 STATE(MOVE_CELL) 전송
  CS_WAIT_MOVE_ACK,    // MOVE_CELL ACK 대기
  CS_VISION_READY,     // 카메라 준비 후 STATE(VISION_READY) 전송
  CS_WAIT_TASK,        // TASK 대기 (AI/관리자 결정)
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

// ---- STATE/ACK 핸드셰이크 ----
long seqCounter = 0;      // STATE마다 증가
long pendingSeq = -1;     // 지금 ACK를 기다리는 seq (-1이면 대기 안 함)
bool taskReceived = false;

// ---- 물리 동작 내부 타이밍 ----
const unsigned long ACTION_TOTAL_MS = 2500;  // TODO: 실제 동작 시간
unsigned long actionStartMs = 0;

// ---- EEPROM: 다음 시작 셀 (복구용 잔존 - RESUME 미구현이라 지금은 참고 정보) ----
const int EEPROM_ADDR_NEXT_CELL = 0;
uint8_t loadNextCellFromEeprom() {
  uint8_t v = EEPROM.read(EEPROM_ADDR_NEXT_CELL);
  return (v < 1 || v > TOTAL_CELLS) ? 1 : v;
}
void saveNextCellToEeprom(uint8_t nextCell) { EEPROM.update(EEPROM_ADDR_NEXT_CELL, nextCell); }

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

#if USE_LCD
void showMessage(const char* l1, const char* l2) {
  lcd.clear(); lcd.setCursor(0, 0); lcd.print(l1); lcd.setCursor(0, 1); lcd.print(l2);
}
#endif

// ============================================================================
// 물리 동작 placeholder (실제 배선 전까지 아무 동작 안 함)
// ============================================================================
void moveToCell(int cellIndex) { /* TODO */ }
void returnToHome() { /* TODO */ }
void positionCamera() { /* TODO */ }
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
      pendingSeq = sendState(currentCell, STATE_MOVE_CELL);
      cycleStep = CS_WAIT_MOVE_ACK;
      break;

    case CS_WAIT_MOVE_ACK:
      // ACK 도착은 handleIncomingLine에서 pendingSeq를 -1로 풀어준다.
      if (pendingSeq == -1) cycleStep = CS_VISION_READY;
      break;

    case CS_VISION_READY:
      positionCamera();
      // VISION_READY는 ACK가 아니라 TASK를 기다린다(AI 동기화 지점).
      taskReceived = false;
      pendingSeq = sendState(currentCell, STATE_VISION_READY);
      cycleStep = CS_WAIT_TASK;
      break;

    case CS_WAIT_TASK:
      // Jetson은 VISION_READY에 ACK도 보내고(pendingSeq 풀림) TASK도 보낸다.
      // 우리는 TASK가 올 때까지 기다린다.
      if (taskReceived) {
        actionStartMs = millis();
        cycleStep = CS_EXECUTE_ACTION;
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
      sendComplete();  // 이 셀 완료 통보 (COMPLETE는 ACK 불필요)
      if (currentCell >= TOTAL_CELLS) {
        returnToHome();
        saveNextCellToEeprom(1);
        megaMode = MODE_IDLE;
        currentCell = 1;
        cycleStep = CS_MOVE_TO_CELL;
      } else {
        currentCell++;
        saveNextCellToEeprom((uint8_t)currentCell);
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
    if (megaMode == MODE_IDLE) {
      megaMode = MODE_RUN;
      // cycle_id는 Jetson이 관리(AWS task id). Mega는 참고만 하고 별도 저장 안 함.
      cycleStep = CS_MOVE_TO_CELL;
      pendingSeq = -1;
      taskReceived = false;
    }
    return;
  }

  if (strcmp(cmd, CMD_ACK) == 0) {
    long seq = doc["seq"] | -1;
    if (seq == pendingSeq) pendingSeq = -1;  // 기다리던 ACK 도착 -> 다음 진행 허용
    return;
  }

  if (strcmp(cmd, CMD_TASK) == 0) {
    if (megaMode == MODE_RUN && cycleStep == CS_WAIT_TASK) {
      const char* taskStr = doc["task"] | "SKIP";
      currentExecuteTask = parseTask(taskStr);
      taskReceived = true;
    }
    return;
  }
  // RESUME은 미구현 - 무시.
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
  megaMode = MODE_IDLE;
  currentCell = loadNextCellFromEeprom();
  cycleStep = CS_MOVE_TO_CELL;

  // 부팅 완료 알림 - Jetson은 이걸 받고 RUN을 보낸다.
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
