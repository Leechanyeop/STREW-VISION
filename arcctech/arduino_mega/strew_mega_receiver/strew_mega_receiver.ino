#include <ArduinoJson.h>

const int LED_PIN = 13;

void setup() {
  pinMode(LED_PIN, OUTPUT);
  Serial.begin(115200);
}

void loop() {
  if (!Serial.available()) return;

  String line = Serial.readStringUntil('\n');
  StaticJsonDocument<384> doc;
  DeserializationError err = deserializeJson(doc, line);
  StaticJsonDocument<192> res;

  if (err) {
    res["completion_sign"] = "FAILED";
    res["message"] = "json parse error";
    serializeJson(res, Serial);
    Serial.println();
    return;
  }

  const char* moveSign = doc["move_sign"] | "STOP";
  const char* task = doc["execute_task"] | "UNKNOWN";

  if (strcmp(moveSign, "LEFT") == 0) {
    digitalWrite(LED_PIN, HIGH);
  } else if (strcmp(moveSign, "RIGHT") == 0) {
    digitalWrite(LED_PIN, LOW);
  } else {
    digitalWrite(LED_PIN, !digitalRead(LED_PIN));
  }

  res["completion_sign"] = "DONE";
  res["message"] = "task accepted";
  res["task"] = task;
  res["move_sign"] = moveSign;
  serializeJson(res, Serial);
  Serial.println();
}
