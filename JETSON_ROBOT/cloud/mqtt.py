import paho.mqtt.client as mqtt


class MqttClient:
    def __init__(self):
        self.client = mqtt.Client()
        self.emergency_stop_flag = False  # 긴급정지 상태를 나타내는 플래그
        self.topic = None  # connect()에서 실제 구독 토픽으로 채워짐
        self.client.on_message = self.on_message  # 메시지 수신 시 호출될 콜백 함수 등록

    def on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        print(f"Received message on topic {topic}: {payload}")

        # 긴급정지 메시지를 수신하면 플래그를 True로 설정
        if topic == self.topic and payload.lower() == "stop":
            self.emergency_stop_flag = True
            print("Emergency stop activated!")

    def connect(self, broker_address: str, topic: str, port: int = 1883) -> None:

        self.topic = topic  # 구독할 토픽을 저장
        try:
            self.client.connect(broker_address, port)
            self.client.subscribe(topic)
            self.client.loop_start()  # 비동기적으로 메시지 수신 시작
            print(f"Connected to MQTT broker at {broker_address}:{port} and subscribed to topic '{topic}'")
        except Exception as e:
            print(f"Failed to connect to MQTT broker: {e}")
