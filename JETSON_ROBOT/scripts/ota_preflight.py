"""[2026-07-23] 젯슨 OTA 준비상태 점검 (preflight).

실제 업데이트를 하지 않고, OTA가 성공하려면 갖춰져야 할 조건들을 검사만 한다.
Jetson에 처음 배포할 때 "git/arduino-cli/시리얼/설정이 제대로 됐는지"를 한 번에 확인.

사용법 (Jetson에서):
    python3 scripts/ota_preflight.py
"""

import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

OK, WARN, FAIL = "  [OK ]", "  [WARN]", "  [FAIL]"


def run(args, cwd=None):
    try:
        r = subprocess.run(args, cwd=cwd, capture_output=True, text=True, timeout=15)
        return r.returncode, (r.stdout + r.stderr).strip()
    except Exception as e:
        return 1, str(e)


def main() -> int:
    from config.settings import settings as cfg

    repo = cfg.ota_repo_dir
    print(f"=== STREW_VISION OTA 프리플라이트 ===")
    print(f"repo_dir      : {repo}")
    print(f"update_topic  : {cfg.ota_update_topic}")
    print(f"arduino fqbn  : {cfg.ota_arduino_fqbn}  port: {cfg.ota_arduino_port}")
    print(f"firmware      : {cfg.ota_firmware_sketch}")
    print()

    problems = 0

    # 1) git 저장소 + origin
    rc, out = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo)
    if rc == 0 and out == "true":
        print(f"{OK} git 저장소 인식")
        rc2, remote = run(["git", "remote", "get-url", "origin"], cwd=repo)
        print(f"{OK if rc2 == 0 else FAIL} origin: {remote if rc2 == 0 else '없음'}")
        if rc2 != 0:
            problems += 1
        rc3, _ = run(["git", "fetch", "--dry-run", "origin"], cwd=repo)
        if rc3 == 0:
            print(f"{OK} origin fetch 가능(네트워크/권한 OK)")
        else:
            print(f"{WARN} origin fetch 실패 - 네트워크/인증 확인 필요")
    else:
        print(f"{FAIL} git 저장소가 아님: {repo}")
        problems += 1

    # 2) arduino-cli + core
    if shutil.which("arduino-cli"):
        print(f"{OK} arduino-cli 설치됨")
        rc, out = run(["arduino-cli", "core", "list"])
        if "arduino:avr" in out:
            print(f"{OK} arduino:avr 코어 설치됨")
        else:
            print(f"{WARN} arduino:avr 코어 없음 -> arduino-cli core install arduino:avr")
    else:
        print(f"{WARN} arduino-cli 없음 -> 펌웨어 자동 업로드 불가 (python 업데이트는 가능)")

    # 3) 시리얼 포트
    try:
        import serial.tools.list_ports
        ports = [p.device for p in serial.tools.list_ports.comports()]
        if cfg.ota_arduino_port in ports:
            print(f"{OK} 시리얼 포트 존재: {cfg.ota_arduino_port}")
        elif ports:
            print(f"{WARN} 설정 포트({cfg.ota_arduino_port}) 없음. 감지된 포트: {ports}")
        else:
            print(f"{WARN} 시리얼 포트 감지 안 됨 (Mega 미연결?)")
    except Exception as e:
        print(f"{WARN} 시리얼 점검 불가: {e}")

    # 4) paho-mqtt
    try:
        import paho.mqtt.client  # noqa: F401
        print(f"{OK} paho-mqtt 사용 가능")
    except Exception:
        print(f"{FAIL} paho-mqtt 없음 -> pip install paho-mqtt")
        problems += 1

    # 5) 펌웨어 스케치 경로
    sketch = Path(repo) / cfg.ota_firmware_sketch
    if (sketch / "mega_firmware.ino").exists():
        print(f"{OK} 펌웨어 스케치 확인: {sketch}")
    else:
        print(f"{WARN} 펌웨어 스케치 없음: {sketch}")

    print()
    if problems == 0:
        print("=> 준비 완료. UPDATE 명령을 받으면 정상 동작할 조건을 갖췄습니다.")
    else:
        print(f"=> FAIL {problems}건 - 위 항목을 먼저 해결하세요.")
    return 0 if problems == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
