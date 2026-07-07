from config.settings import Config 
#프로그램에서 사용할 모든 설정값을 불러오는 역할
#config/settings.py 파일에 있는 Config 클래스를 가져온다는 뜻입니다.
from robot.state_machine import RobotAgent 
# robot/state_machine.py 안에 있는 RobotAgent 클래스를 가져온다는 뜻입니다.

#RobotAgent는 보통

#로봇 상태(State)
#동작 제어
#이벤트 처리
#전체 프로그램 흐름을 관리하는 핵심 클래스입니다.


# 프로그램 시작점
def main() -> int: # main 함수는 프로그램의 시작점으로, 프로그램이 실행될 때 가장 먼저 호출되는 함수입니다.
    agent = RobotAgent(Config()) #Config()설정을 생성하고 RobotAgent에 전달합니다.
    #즉 Config 생성 -> RobotAgent 생성 -> RobotAgent 안에서 설정을 사용
    agent.run_forever() #run_forever() 메서드는 RobotAgent가 무한 루프를 돌면서 계속해서 상태를 확인하고, 이벤트를 처리하며, 로봇의 동작을 제어하도록 합니다.
    return 0 #프로그램 정상 종료


if __name__ == "__main__": # 이 파일을 직접 실행했을 때만 아래 코드를 실행하라 입니다. import될 때는 실행되지 않습니다.
    raise SystemExit(main()) # main()실행 -> 0 반환 -> SystemExit(0) -> 프로그램 종료

'''프로그램 실행
        │
        ▼
if __name__ == "__main__"
        │
        ▼
main() 실행
        │
        ▼
Config 생성 설정값 불러오기
        │
        ▼
RobotAgent 생성 로봇 상태(State) 초기화후 메인 제어루프 실행
        │
        ▼
run_forever() 무한 반복
        │
        ▼
──────────────────────────────
while True
    센서 확인
    MQTT 수신
    카메라 처리
    AI 추론
    QR 인식
    모터 제어
    상태 변경
──────────────────────────────
        │
        ▼
프로그램 종료 시 return 0
        │
        ▼
SystemExit(0)

즉, 이 코드는 설정(Config)을 생성하고, 이를 기반으로 로봇 제어 객체(RobotAgent)를 초기화한 뒤, run_forever()를 통해 로봇의 메인 제어 루프를 계속 실행하는 프로그램의 진입점(Entry Point) 역할을 합

'''