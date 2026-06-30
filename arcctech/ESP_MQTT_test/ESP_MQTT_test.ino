#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include "DHT.h"

#define DHTTYPE DHT11

#define DHTPIN1 18
#define DHTPIN2 22
#define DHTPIN3 23

#define RED_LED 19
#define GREEN_LED 12

DHT dht1(DHTPIN1, DHTTYPE);
DHT dht2(DHTPIN2, DHTTYPE);
DHT dht3(DHTPIN3, DHTTYPE);

float tempLimit = 30.0;
float humiLimit = 70.0;

// MQTT 서버
const char* mqtt_server = "13.58.164.61";
const int mqtt_port = 1883;

// 저장된 WiFi 목록
const char* ssidList[] = {
  "Strew_vision",
  "HexaNet",
  "BlackHood29"
};

const char* passList[] = {
  "qqQ@0984",
  "blackhood@29",
  "qqQ@0984a"
};

const int wifiCount = 3;// WiFi 목록 개수

WiFiClient espClient;// MQTT Client 생성
PubSubClient client(espClient); // MQTT Client 생성 정확히는 
//PubSubClient 객체를 생성하고, 
//WiFiClient 객체를 인자로 전달하여 MQTT 통신을 위한 클라이언트를 초기화합니다.

//////////////////////////////////////////////////////
// MQTT 수신 callback
//////////////////////////////////////////////////////
void callback(char* topic, byte* payload, unsigned int length) {

  payload[length] = '\0';

  StaticJsonDocument<128> doc;

  DeserializationError error =
      deserializeJson(doc, (char*)payload);

  if (!error) {

    if (doc.containsKey("tempLimit"))
      tempLimit = doc["tempLimit"];

    if (doc.containsKey("humiLimit"))
      humiLimit = doc["humiLimit"];

    Serial.println("새 임계값 수신");
    Serial.print("온도 : ");
    Serial.println(tempLimit);

    Serial.print("습도 : ");
    Serial.println(humiLimit);
  }

}

//////////////////////////////////////////////////////
// 가장 강한 WiFi 선택
//////////////////////////////////////////////////////
void connectBestWifi() {

  WiFi.mode(WIFI_STA);
  WiFi.disconnect(true, true);
  delay(1000);

  int n = WiFi.scanNetworks();

  Serial.println("Scan Result");

  for (int i = 0; i < n; i++) {
    Serial.print(WiFi.SSID(i));
    Serial.print("  RSSI=");
    Serial.println(WiFi.RSSI(i));
  }

  int bestIndex = -1;
  int bestRSSI = -1000;

  for (int i = 0; i < n; i++) {

    String foundSSID = WiFi.SSID(i);

    for (int j = 0; j < wifiCount; j++) {

      if (foundSSID == ssidList[j]) {

        if (WiFi.RSSI(i) > bestRSSI) {
          bestRSSI = WiFi.RSSI(i);
          bestIndex = j;
        }
      }
    }
  }

  if (bestIndex == -1) {
    Serial.println("등록된 WiFi 없음");
    while (1) delay(1000);
  }

  Serial.print("Connecting : ");
  Serial.println(ssidList[bestIndex]);

  Serial.print("PASS : ");
  Serial.println(passList[bestIndex]);

  WiFi.begin(
      ssidList[bestIndex],
      passList[bestIndex]);

  while (WiFi.status() != WL_CONNECTED) {
    Serial.print(".");
    Serial.println(WiFi.status());
    delay(500);
  }

  Serial.println();
  Serial.println("WiFi Connected!");
  Serial.print("IP : ");
  Serial.println(WiFi.localIP());

  WiFi.onEvent([](WiFiEvent_t event, WiFiEventInfo_t info) {
    if (event == ARDUINO_EVENT_WIFI_STA_DISCONNECTED) {
      Serial.print("Disconnect reason = ");
      Serial.println(info.wifi_sta_disconnected.reason);
    }
  });
}

//////////////////////////////////////////////////////
// MQTT 재접속
//////////////////////////////////////////////////////
void reconnect() {

  while (!client.connected()) {

    Serial.print("MQTT connecting...");

    if (client.connect("ESP32_Client")) {

      Serial.println("connected");

      client.subscribe("esp32/threshold");

    } else {

      Serial.print("failed rc=");
      Serial.println(client.state());

      delay(2000);
    }
  }
}

//////////////////////////////////////////////////////
// setup
//////////////////////////////////////////////////////
void setup() {

  Serial.begin(115200);

  pinMode(RED_LED, OUTPUT);
  pinMode(GREEN_LED, OUTPUT);

  dht1.begin();
  dht2.begin();
  dht3.begin();

  connectBestWifi();

  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(callback);
}

//////////////////////////////////////////////////////
// loop
//////////////////////////////////////////////////////
void loop() {

  if (!client.connected())
    reconnect();

  client.loop();

  float t1 = dht1.readTemperature();
  float h1 = dht1.readHumidity();

  float t2 = dht2.readTemperature();
  float h2 = dht2.readHumidity();

  float t3 = dht3.readTemperature();
  float h3 = dht3.readHumidity();

  if (isnan(t1) || isnan(h1) ||
      isnan(t2) || isnan(h2) ||
      isnan(t3) || isnan(h3)) {

    Serial.println("센서 읽기 실패");
    delay(2000);
    return;
  }

  // LED 상태
  bool alarm =
      (t1 > tempLimit || t2 > tempLimit || t3 > tempLimit ||
       h1 > humiLimit || h2 > humiLimit || h3 > humiLimit);

  digitalWrite(RED_LED, alarm);
  digitalWrite(GREEN_LED, !alarm);

  // JSON 생성
  StaticJsonDocument<256> doc;

  doc["sensor1"]["temp"] = t1;
  doc["sensor1"]["humi"] = h1;

  doc["sensor2"]["temp"] = t2;
  doc["sensor2"]["humi"] = h2;

  doc["sensor3"]["temp"] = t3;
  doc["sensor3"]["humi"] = h3;

  char buffer[256];

  serializeJson(doc, buffer);

  client.publish("esp32/sensor", buffer);

  Serial.println(buffer);

  delay(3000);
}