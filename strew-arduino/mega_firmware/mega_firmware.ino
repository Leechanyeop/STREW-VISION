#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

#define LCD_ADDR 0x27
LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);

void showMessage(const char* line1, const char* line2)
{
    lcd.clear();
    lcd.setCursor(0, 0);
    lcd.print(line1);
    lcd.setCursor(0, 1);
    lcd.print(line2);
}

// 예전(단발) 응답 형식. PING/STATUS/HOME 같은 수동 점검용 명령이 계속 쓰는 포맷이라
// 형식을 그대로 유지함 — {"status": "...", "command": "..."}
void sendResponse(const char* status,
                  const char* command)
{
    StaticJsonDocument<128> response;
    response["status"] = status;
    response["command"] = command;
    serializeJson(response, Serial);
    Serial.println();
}

// 공식 인터페이스 명세(Jetson and Arduino Mega Interface.pdf) 6절 기준 응답.
// {"task": "...", "target": "...", "state": "...", "progress": N}
// 필드명이 "command"가 아니라 "task"인 점 주의 — 요청(Jetson->Mega)은 "command",
// 응답(Mega->Jetson)은 "task"로 문서에 명확히 다르게 정의되어 있음.
void sendProgress(const char* task, const char* target, const char* state, int progress)
{
    StaticJsonDocument<192> response;
    response["task"] = task;
    response["target"] = target;
    response["state"] = state;
    response["progress"] = progress;
    serializeJson(response, Serial);
    Serial.println();
}

void setup()
{
    Serial.begin(115200);
    lcd.init();
    lcd.backlight();
    showMessage("STREW ROBOT", "READY");
}

void loop()
{
    if (!Serial.available())
        return;
    String line = Serial.readStringUntil('\n');
    StaticJsonDocument<256> doc;
    DeserializationError err = deserializeJson(doc, line);
    if (err)
    {
        showMessage("JSON ERROR", "");
        StaticJsonDocument<128> res;
        res["status"] = "ERROR";
        serializeJson(res, Serial);
        Serial.println();
        return;
    }

    const char* command = doc["command"];
    if (command == nullptr)
    {
        showMessage("NO COMMAND", "");
        sendResponse("ERROR", "NONE");
        return;
    }

    //--------------------------------------------------------
    // PING / STATUS / HOME / MOVE / STOP / SERVO / GRIP_OPEN / GRIP_CLOSE /
    // WATER / NUTRITION / PUMP_ON / PUMP_OFF / LED
    // (수동 점검용 레거시 명령, 예전 단발 응답 형식 그대로 유지)
    //--------------------------------------------------------
    if (strcmp(command, "PING") == 0)
    {
        showMessage("COMMAND", "PING");
        sendResponse("PONG", "PING");
    }
    else if (strcmp(command, "STATUS") == 0)
    {
        showMessage("COMMAND", "STATUS");
        sendResponse("READY", "STATUS");
    }
    else if (strcmp(command, "HOME") == 0)
    {
        showMessage("COMMAND", "HOME");
        sendResponse("DONE", "HOME");
    }
    else if (strcmp(command, "MOVE") == 0)
    {
        int target = doc["target"] | 0;
        char line2[17];
        snprintf(line2, sizeof(line2), "TARGET:%d", target);
        showMessage("COMMAND", line2);
        sendResponse("DONE", "MOVE");
    }
    else if (strcmp(command, "STOP") == 0)
    {
        showMessage("COMMAND", "STOP");
        sendResponse("DONE", "STOP");
    }
    else if (strcmp(command, "SERVO") == 0)
    {
        int angle = doc["angle"] | 0;
        char line2[17];
        snprintf(line2, sizeof(line2), "ANGLE:%d", angle);
        showMessage("SERVO", line2);
        sendResponse("DONE", "SERVO");
    }
    else if (strcmp(command, "GRIP_OPEN") == 0)
    {
        showMessage("GRIPPER", "OPEN");
        sendResponse("DONE", "GRIP_OPEN");
    }
    else if (strcmp(command, "GRIP_CLOSE") == 0)
    {
        showMessage("GRIPPER", "CLOSE");
        sendResponse("DONE", "GRIP_CLOSE");
    }
    else if (strcmp(command, "WATER") == 0)
    {
        showMessage("PUMP", "WATER");
        sendResponse("DONE", "WATER");
    }
    else if (strcmp(command, "NUTRITION") == 0)
    {
        showMessage("PUMP", "NUTRITION");
        sendResponse("DONE", "NUTRITION");
    }
    else if (strcmp(command, "PUMP_ON") == 0)
    {
        showMessage("PUMP", "ON");
        sendResponse("DONE", "PUMP_ON");
    }
    else if (strcmp(command, "PUMP_OFF") == 0)
    {
        showMessage("PUMP", "OFF");
        sendResponse("DONE", "PUMP_OFF");
    }
    else if (strcmp(command, "LED") == 0)
    {
        const char* state = doc["state"] | "UNKNOWN";
        showMessage("LED", state);
        sendResponse("DONE", "LED");
    }
    //--------------------------------------------------------
    // OBSERVE — 공식 명세 5-1절 상태머신 그대로.
    // 문서 기준으로는 OBSERVE도 "그 자리에서 아무것도 안 함"이 아니라
    // 실제로 셀까지 이동 -> 카메라 자세 정렬 -> 6축 정밀 검사 -> 대기위치 복귀까지
    // 물리 동작이 있는 작업임. TODO는 실제 모터/6축 제어가 들어갈 자리.
    //--------------------------------------------------------
    else if (strcmp(command, "OBSERVE") == 0)
    {
        const char* target = doc["target"] | "";
        showMessage("OBSERVE", target);

        sendProgress("OBSERVE", target, "RECEIVED", 0);

        // TODO: 대상 셀로 실제 이동 (EEPROM 조회 + 모터 제어)
        showMessage("OBSERVE", "MOVE_TO_CELL");
        delay(300);
        sendProgress("OBSERVE", target, "MOVE_TO_CELL", 20);

        // TODO: 검사 위치로 카메라 자세 정렬 (6축 제어)
        showMessage("OBSERVE", "POSITION_CAM");
        delay(300);
        sendProgress("OBSERVE", target, "POSITION_CAMERA", 40);

        // TODO: 6축을 이용한 정밀 검사 수행
        showMessage("OBSERVE", "INSPECTION");
        delay(300);
        sendProgress("OBSERVE", target, "INSPECTION", 70);

        // TODO: 대기 위치 복귀
        showMessage("OBSERVE", "RETURN_HOME");
        delay(300);
        sendProgress("OBSERVE", target, "RETURN_HOME", 90);

        sendProgress("OBSERVE", target, "COMPLETE", 100);
    }
    //--------------------------------------------------------
    // SKIP — 공식 명세 5-3절 상태머신 그대로.
    // 종료 상태가 "COMPLETE"가 아니라 "SKIPPED"인 점 주의.
    //--------------------------------------------------------
    else if (strcmp(command, "SKIP") == 0)
    {
        const char* target = doc["target"] | "";
        showMessage("SKIP", target);

        sendProgress("SKIP", target, "RECEIVED", 0);
        sendProgress("SKIP", target, "SKIPPED", 100);
    }
    //--------------------------------------------------------
    // REPLACE — 공식 명세 5-2절 상태머신 그대로.
    // TODO: 각 단계의 delay()는 실제 모터/그리퍼 제어 코드가 들어갈 자리표시자.
    //--------------------------------------------------------
    else if (strcmp(command, "REPLACE") == 0)
    {
        const char* target = doc["target"] | "";
        char line2[17];
        snprintf(line2, sizeof(line2), "POT:%s", target);
        showMessage("REPLACE", line2);

        sendProgress("REPLACE", target, "RECEIVED", 0);

        // TODO: EEPROM에서 target 위치 조회 + 대상 셀로 이동
        showMessage("REPLACE", "MOVE_TO_CELL");
        delay(300);
        sendProgress("REPLACE", target, "MOVE_TO_CELL", 10);

        // TODO: 기존 화분 집기 (그리퍼 제어)
        showMessage("REPLACE", "PICK_OLD_POT");
        delay(300);
        sendProgress("REPLACE", target, "PICK_OLD_POT", 25);

        // TODO: 폐기 위치로 이동
        showMessage("REPLACE", "MOVE_DISPOSAL");
        delay(300);
        sendProgress("REPLACE", target, "MOVE_TO_DISPOSAL", 40);

        // TODO: 기존 화분 내려놓기
        showMessage("REPLACE", "DROP_OLD_POT");
        delay(300);
        sendProgress("REPLACE", target, "DROP_OLD_POT", 50);

        // TODO: 새 화분 위치로 이동
        showMessage("REPLACE", "MOVE_NEW_POT");
        delay(300);
        sendProgress("REPLACE", target, "MOVE_TO_NEW_POT", 60);

        // TODO: 새 화분 집기
        showMessage("REPLACE", "PICK_NEW_POT");
        delay(300);
        sendProgress("REPLACE", target, "PICK_NEW_POT", 75);

        // TODO: 대상 셀에 새 화분 배치 + 포토센서로 위치 확인
        showMessage("REPLACE", "PLACE_NEW_POT");
        delay(300);
        sendProgress("REPLACE", target, "PLACE_NEW_POT", 90);

        sendProgress("REPLACE", target, "COMPLETE", 100);
    }
    //--------------------------------------------------------
    // UNKNOWN
    //--------------------------------------------------------
    else
    {
        showMessage("UNKNOWN", command);
        sendResponse("UNKNOWN_COMMAND", command);
    }
}
