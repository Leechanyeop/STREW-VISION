#include <Wire.h>
#include <LiquidCrystal_I2C.h>
#include <ArduinoJson.h>

#define LCD_ADDR 0x27

LiquidCrystal_I2C lcd(LCD_ADDR, 16, 2);


// ================================
// LCD
// ================================

void showMessage(const char* line1, const char* line2)
{
    lcd.clear();

    lcd.setCursor(0,0);
    lcd.print(line1);

    lcd.setCursor(0,1);
    lcd.print(line2);
}


// ================================
// Runtime State
// ================================

bool cycleRunning = false;

int currentCell = 1;

const int MAX_CELL = 4;


// Vision Result 저장

String visionStatus = "";

bool waitingVision = false;



// ================================
// UART Send
// ================================

void sendJson(JsonDocument& doc)
{
    serializeJson(doc, Serial);
    Serial.println();
}



// ================================
// REQUEST_VISION
// Mega → Jetson
// ================================

void sendRequestVision(int cell)
{
    StaticJsonDocument<128> doc;


    doc["command"] = "REQUEST_VISION";
    doc["cell"] = cell;


    sendJson(doc);


    showMessage(
        "REQUEST VISION",
        String(cell).c_str()
    );
}



// ================================
// REPORT_RESULT
// Mega → Jetson
// ================================

void sendReportResult(
    int cell,
    const char* task
)
{
    StaticJsonDocument<256> doc;


    doc["command"] = "REPORT_RESULT";

    doc["target"] = "cell_";

    String target =
        "cell_" + String(cell);

    doc["target"] = target;


    doc["execute_task"] = task;

    doc["completion"] = "COMPLETE";

    doc["success"] = true;


    sendJson(doc);
}



// ================================
// CYCLE_COMPLETE
// Mega → Jetson
// ================================

void sendCycleComplete()
{
    StaticJsonDocument<128> doc;


    doc["command"] =
        "CYCLE_COMPLETE";


    sendJson(doc);
}



// ================================
// Error
// ================================

void sendError(const char* msg)
{
    StaticJsonDocument<128> doc;


    doc["command"] = "ERROR";

    doc["message"] = msg;


    sendJson(doc);
}
// ================================
// Setup
// ================================

void setup()
{
    Serial.begin(115200);


    lcd.init();
    lcd.backlight();


    showMessage(
        "STREW ROBOT",
        "READY"
    );


    delay(1000);
}



// ================================
// Vision Result 처리
// Jetson → Mega
// ================================

void handleVisionResult(JsonDocument& doc)
{
    const char* status =
        doc["status"] | "unknown";


    visionStatus = status;


    waitingVision = false;


    showMessage(
        "VISION RESULT",
        status
    );


    delay(500);



    // 결과에 따른 Task 결정

    const char* task;


    if(strcmp(status,"healthy") == 0)
    {
        task = "OBSERVE";
    }
    else if(
        strcmp(status,"missing_plant") == 0 ||
        strcmp(status,"powdery_mildew") == 0
    )
    {
        task = "REPLACE";
    }
    else
    {
        task = "SKIP";
    }



    sendReportResult(
        currentCell,
        task
    );



    delay(1000);



    currentCell++;



    if(currentCell > MAX_CELL)
    {
        sendCycleComplete();


        cycleRunning = false;


        showMessage(
            "CYCLE",
            "COMPLETE"
        );

        return;
    }



    // 다음 Cell 검사

    sendRequestVision(currentCell);

    waitingVision = true;
}



// ================================
// START CYCLE
// Jetson → Mega
// ================================

void startCycle()
{
    cycleRunning = true;


    currentCell = 1;


    showMessage(
        "CYCLE",
        "START"
    );


    delay(1000);



    // 첫 Cell 이동

    showMessage(
        "MOVE",
        "CELL 1"
    );


    delay(1000);



    sendRequestVision(
        currentCell
    );


    waitingVision = true;
}



// ================================
// JSON Command 처리
// ================================

void processCommand(JsonDocument& doc)
{

    const char* command =
        doc["command"];



    if(command == nullptr)
    {
        sendError(
            "NO_COMMAND"
        );

        return;
    }



    // START_CYCLE

    if(strcmp(command,"START_CYCLE")==0)
    {
        startCycle();
    }



    // VISION_RESULT

    else if(
        strcmp(command,"VISION_RESULT")==0
    )
    {
        handleVisionResult(doc);
    }

    // PING
    else if(
        strcmp(command,"PING")==0
    )
    {
        StaticJsonDocument<128> response;

        response["status"] = "PONG";
        response["command"] = "PING";

        sendJson(response);


        showMessage(
            "PING",
            "PONG"
        );
    }

    // STOP

    else if(
        strcmp(command,"STOP")==0
    )
    {
        cycleRunning=false;


        showMessage(
            "STOP",
            "SYSTEM"
        );
    }



    else
    {
        sendError(
            "UNKNOWN_COMMAND"
        );
    }
}
// ================================
// Main Loop
// ================================

void loop()
{

    // UART 데이터 확인

    if(Serial.available())
    {

        String line =
            Serial.readStringUntil('\n');


        StaticJsonDocument<256> doc;


        DeserializationError error =
            deserializeJson(
                doc,
                line
            );



        if(error)
        {
            sendError(
                "JSON_PARSE_FAIL"
            );

            return;
        }



        processCommand(doc);
    }



    // ============================
    // Cycle Running 상태
    // ============================

    if(cycleRunning)
    {

        // 현재는 Simulator 모드
        // 실제 구현에서는:
        //
        // Motion Controller
        // EEPROM 위치 조회
        // Servo / Stepper 제어
        //
        // 가 이 위치에 들어감.


        // 현재는 이벤트 기반이므로
        // Serial 명령 대기


    }


}