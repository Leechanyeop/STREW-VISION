from config.settings import Config
from robot.state_machine import RobotAgent


def main() -> int:
    agent = RobotAgent(Config())
    agent.run_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
