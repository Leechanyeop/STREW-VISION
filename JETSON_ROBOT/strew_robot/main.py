from .agent import RobotAgent
from .config import Config

def main() -> int:
    agent = RobotAgent(Config())
    agent.run_forever()
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
