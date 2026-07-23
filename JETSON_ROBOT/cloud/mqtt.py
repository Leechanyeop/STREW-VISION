import paho.mqtt.client as mqtt


def _make_client():
    # [2026-07-23] paho-mqtt 1.x/2.x 양쪽 호환. 2.0부터 생성자에 CallbackAPIVersion이
    # 필요해졌다(안 주면 DeprecationWarning). VERSION1 콜백 시그니처
    # (on_connect(client,userdata,flags,rc) / on_message(client,userdata,msg))를
    # 그대로 쓰므로 VERSION1로 명시 생성한다. 1.x에는 이 enum이 없으니 예외로 폴백.
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
    except (AttributeError, TypeError):
        return mqtt.Client()


class MqttClient:
    def __init__(self):
        self.client = _make_client()
        self.emergency_stop_flag = False  # 긴급정지 상태를 나타내는 플래그
        self.topic = None  # connect()에서 실제 구독 토픽으로 채워짐
        # [2026-07-18] ESP32 센서 브리지: 센서 토픽과 수신 콜백. connect()에서
        # sensor_topic을 주면 같이 구독하고, 메시지가 오면 on_sensor(payload_str)를 부른다.
        # 콜백 방식으로 둔 이유: mqtt.py는 "받는 것"만 담당하고, 파싱/전달(비즈니스 로직)은
        # main.py 쪽 브리지 함수가 담당하게 역할을 분리하기 위해서.
        self.sensor_topic = None
        self.on_sensor = None
        # [2026-07-23] OTA: 원격 업데이트 명령 토픽/콜백. update_topic을 주면 같이 구독하고,
        # 메시지가 오면 on_update(payload_str)를 부른다(파싱/실행은 UpdateManager가 담당).
        self.update_topic = None
        self.on_update = None

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        print(f"Received message on topic {topic}: {payload}")

        # 긴급정지 메시지를 수신하면 플래그를 True로 설정
        if topic == self.topic and payload.lower() == "stop":
            self.emergency_stop_flag = True
            print("Emergency stop activated!")
            return

        # 센서 메시지는 등록된 콜백에 넘긴다. 콜백 안에서 무슨 일이 나도
        # MQTT 수신 루프(긴급정지 포함)는 절대 죽으면 안 되므로 예외를 삼킨다.
        if topic == self.sensor_topic and self.on_sensor is not None:
            try:
                self.on_sensor(payload)
            except Exception as e:
                print(f"sensor bridge callback error (ignored): {e}")

        # OTA 업데이트 명령.
        if topic == self.update_topic and self.on_update is not None:
            try:
                self.on_update(payload)
            except Exception as e:
                print(f"OTA update callback error (ignored): {e}")

    def connect(self, broker_address: str, topic: str, port: int = 1883,
                sensor_topic: str = None, update_topic: str = None) -> None:

        self.topic = topic  # 구독할 토픽을 저장
        self.sensor_topic = sensor_topic
        self.update_topic = update_topic
        try:
            self.client.on_message = self.on_message  # 콜백 등록 (누락되어 있던 것 - 명시)
            self.client.connect(broker_address, port)
            self.client.subscribe(topic)
            for extra in (sensor_topic, update_topic):
                if extra:
                    self.client.subscribe(extra)
            self.client.loop_start()  # 비동기적으로 메시지 수신 시작
            subs = [topic] + [t for t in (sensor_topic, update_topic) if t]
            print(f"Connected to MQTT broker at {broker_address}:{port}, subscribed: {subs}")
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")

    # OTA/상태 보고용 publish 헬퍼.
    def publish(self, topic: str, payload: str) -> None:
        try:
            self.client.publish(topic, payload)
        except Exception as e:
            print(f"MQTT publish 실패(무시): {e}")
