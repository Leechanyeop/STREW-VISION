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

// 새 인터페이스(Jetson stream_progress()가 읽는 형식) 전용 응답.
// 한 명령 처리 중에 여러 번 호출해서 RECEIVED -> ... -> COMPLETE 진행상황을 스트리밍한다.
// Jetson 쪽은 message.get("state") == "COMPLETE" 를 볼 때까지 계속 읽으므로,
// 이 함수를 부르는 쪽이 마지막에 반드시 "COMPLETE"를 보내야 한다.
void sendProgress(const char* state, int progress, const char* command, const char* target)
{
    StaticJsonDocument<192> response;
    response["state"] = state;
    response["progress"] = progress;
    response["command"] = command;
    response["target"] = target;
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
    // PING
    //--------------------------------------------------------
    if (strcmp(command, "PING") == 0)
    {
        showMessage("COMMAND", "PING");
        sendResponse("PONG", "PING");
    }
    //--------------------------------------------------------
    // STATUS
    //--------------------------------------------------------
    else if (strcmp(command, "STATUS") == 0)
    {
        showMessage("COMMAND", "STATUS");
        sendResponse("READY", "STATUS");
    }
    //--------------------------------------------------------
    // HOME
    //--------------------------------------------------------
    else if (strcmp(command, "HOME") == 0)
    {
        showMessage("COMMAND", "HOME");
        sendResponse("DONE", "HOME");
    }
    //--------------------------------------------------------
    // MOVE  (수동 점검용 레거시 명령 — target은 숫자 좌표 그대로 유지)
    //--------------------------------------------------------
    else if (strcmp(command, "MOVE") == 0)
    {
        int target = doc["target"] | 0;
        char line2[17];
        snprintf(line2, sizeof(line2), "TARGET:%d", target);
        showMessage("COMMAND", line2);
        sendResponse("DONE", "MOVE");
    }
    //--------------------------------------------------------
    // STOP
    //--------------------------------------------------------
    else if (strcmp(command, "STOP") == 0)
    {
        showMessage("COMMAND", "STOP");
        sendResponse("DONE", "STOP");
    }
    //--------------------------------------------------------
    // SERVO
    //--------------------------------------------------------
    else if (strcmp(command, "SERVO") == 0)
    {
        int angle = doc["angle"] | 0;
        char line2[17];
        snprintf(line2, sizeof(line2), "ANGLE:%d", angle);
        showMessage("SERVO", line2);
        sendResponse("DONE", "SERVO");
    }
    //--------------------------------------------------------
    // GRIP_OPEN
    //--------------------------------------------------------
    else if (strcmp(command, "GRIP_OPEN") == 0)
    {
        showMessage("GRIPPER", "OPEN");
        sendResponse("DONE", "GRIP_OPEN");
    }
    //--------------------------------------------------------
    // GRIP_CLOSE
    //--------------------------------------------------------
    else if (strcmp(command, "GRIP_CLOSE") == 0)
    {
        showMessage("GRIPPER", "CLOSE");
        sendResponse("DONE", "GRIP_CLOSE");
    }
    //--------------------------------------------------------
    // WATER
    //--------------------------------------------------------
    else if (strcmp(command, "WATER") == 0)
    {
        showMessage("PUMP", "WATER");
        sendResponse("DONE", "WATER");
    }
    //--------------------------------------------------------
    // NUTRITION
    //--------------------------------------------------------
    else if (strcmp(command, "NUTRITION") == 0)
    {
        showMessage("PUMP", "NUTRITION");
        sendResponse("DONE", "NUTRITION");
    }
    //--------------------------------------------------------
    // PUMP_ON
    //--------------------------------------------------------
    else if (strcmp(command, "PUMP_ON") == 0)
    {
        showMessage("PUMP", "ON");
        sendResponse("DONE", "PUMP_ON");
    }
    //--------------------------------------------------------
    // PUMP_OFF
    //--------------------------------------------------------
    else if (strcmp(command, "PUMP_OFF") == 0)
    {
        showMessage("PUMP", "OFF");
        sendResponse("DONE", "PUMP_OFF");
    }
    //--------------------------------------------------------
    // LED
    //--------------------------------------------------------
    else if (strcmp(command, "LED") == 0)
    {
        const char* state = doc["state"] | "UNKNOWN";
        showMessage("LED", state);
        sendResponse("DONE", "LED");
    }
    //--------------------------------------------------------
    // OBSERVE  (신규 — Jetson Decision Engine이 실제로 보내는 명령)
    // 이동 없이 그 자리에서 처리하는 작업. Mega 쪽 물리 동작은 없으므로
    // RECEIVED -> COMPLETE 2단계로 짧게 스트리밍한다.
    //--------------------------------------------------------
    else if (strcmp(command, "OBSERVE") == 0)
    {
        const char* target = doc["target"] | "";
        showMessage("OBSERVE", target);

        sendProgress("RECEIVED", 0, "OBSERVE", target);
        sendProgress("COMPLETE", 100, "OBSERVE", target);
    }
    //--------------------------------------------------------
    // SKIP  (신규 — 비전 재확인 없이 다음 셀로 넘어감을 의미)
    // Mega 쪽에서 실제로 수행할 물리 동작이 없으므로 OBSERVE와 동일하게
    // RECEIVED -> COMPLETE 2단계로 짧게 스트리밍한다.
    //--------------------------------------------------------
    else if (strcmp(command, "SKIP") == 0)
    {
        const char* target = doc["target"] | "";
        showMessage("SKIP", target);

        sendProgress("RECEIVED", 0, "SKIP", target);
        sendProgress("COMPLETE", 100, "SKIP", target);
    }
    //--------------------------------------------------------
    // REPLACE  (신규 인터페이스 — target은 셀 라벨 문자열, 다단계 스트리밍)
    // TODO: 아래 각 단계의 delay()는 실제 모터/그리퍼 제어 코드가 들어갈 자리를
    // 표시하기 위한 자리표시자(placeholder)임. 실제 픽/디스카드/배치 시퀀스는
    // 하드웨어 배선이 끝난 뒤 채워야 함 (오케스트레이션 설계는 별도 작업).
    //--------------------------------------------------------
    else if (strcmp(command, "REPLACE") == 0)
    {
        const char* target = doc["target"] | "";
        char line2[17];
        snprintf(line2, sizeof(line2), "POT:%s", target);
        showMessage("REPLACE", line2);

        sendProgress("RECEIVED", 0, "REPLACE", target);

        // TODO: 기존 화분 집기(pick) 실제 모터 제어
        showMessage("REPLACE", "PICKING");
        delay(500);
        sendProgress("PICKING", 25, "REPLACE", target);

        // TODO: 기존 화분 버리기(discard) 실제 모터 제어
        showMessage("REPLACE", "DISCARDING");
        delay(500);
        sendProgress("DISCARDING", 50, "REPLACE", target);

        // TODO: 새 화분 배치(place) 실제 모터 제어
        showMessage("REPLACE", "PLACING");
        delay(500);
        sendProgress("PLACING", 75, "REPLACE", target);

        sendProgress("COMPLETE", 100, "REPLACE", target);
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
