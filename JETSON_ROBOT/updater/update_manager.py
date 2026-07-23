"""[2026-07-23] STREW_VISION 원격 자동 업데이트(OTA) v2.0 - Jetson Update Manager.

v2.0 운영 설계 반영:
  - 날짜 기반 버전(예: 20260723164200). Jetson은 마지막 적용 버전을 로컬 상태파일에
    보관하고, 수신 version과 같으면 git fetch도 없이 즉시 종료(ALREADY_LATEST).
  - 업데이트 락(isUpdating): 진행 중 새 UPDATE는 ALREADY_UPDATING으로 무시.
  - 시작 시 UPDATING 상태 보고.
  - 롤백: pip/compile/upload 실패 시 git reset --hard <이전커밋>으로 복원.
  - 펌웨어 업로드 전 UART 해제(release_uart_fn) - main.py가 포트를 쥐고 있으면
    arduino-cli가 업로드 못 하므로, 업로드 직전에 시리얼을 닫는다.
  - 헬스체크(health_check_fn): 업데이트 후 Mega ping/UART/실행 확인 -> 실패면 UPDATE_FAILED.
  - UPDATE_COMPLETE에 update_time 포함.

테스트 가능성: 모든 쉘 명령은 CommandRunner, 재시작/UART해제/헬스체크는 콜백 주입.
"""

import os
import subprocess
import sys
import time
from typing import Callable, List, Optional


class CommandRunner:
    def __init__(self, cwd: str):
        self.cwd = cwd

    def run(self, args: List[str], check: bool = False) -> "subprocess.CompletedProcess":
        # Python 3.6(젯슨 나노) 호환: capture_output/text(3.7+) 대신 PIPE + universal_newlines.
        return subprocess.run(args, cwd=self.cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                              universal_newlines=True, check=check)


FIRMWARE_MARKER = "mega_firmware"
REQUIREMENTS_MARKER = "requirements.txt"
STATE_FILENAME = ".ota_state"   # 마지막 적용 버전 저장 (gitignore 대상)


class UpdateManager:
    def __init__(
        self,
        repo_dir: str,
        runner: Optional[CommandRunner] = None,
        publish_status: Optional[Callable[[dict], None]] = None,
        restart_fn: Optional[Callable[[], None]] = None,
        release_uart_fn: Optional[Callable[[], None]] = None,
        health_check_fn: Optional[Callable[[], bool]] = None,
        arduino_fqbn: str = "arduino:avr:mega",
        arduino_port: str = "/dev/ttyACM0",
        firmware_sketch_dir: str = "mega_firmware",
        do_pip: bool = True,
        do_arduino: bool = True,
        now_fn: Callable[[], str] = None,
    ):
        self.repo_dir = repo_dir
        self.runner = runner or CommandRunner(repo_dir)
        self.publish_status = publish_status or (lambda p: print(f"[OTA status] {p}"))
        self.restart_fn = restart_fn or self._default_restart
        self.release_uart_fn = release_uart_fn or (lambda: None)
        self.health_check_fn = health_check_fn
        self.arduino_fqbn = arduino_fqbn
        self.arduino_port = arduino_port
        self.firmware_sketch_dir = firmware_sketch_dir
        self.do_pip = do_pip
        self.do_arduino = do_arduino
        self.now_fn = now_fn or (lambda: time.strftime("%Y-%m-%d %H:%M:%S"))
        self.is_updating = False

    # ------------------------------------------------------------------
    def handle_update_command(self, payload: dict) -> dict:
        if payload.get("command") != "UPDATE":
            return {"status": "IGNORED", "reason": "not an UPDATE command"}

        # 업데이트 락 - 중복 실행 방지.
        if self.is_updating:
            status = {"status": "ALREADY_UPDATING"}
            self.publish_status(status)
            return status

        target_version = payload.get("version")

        # 버전 비교 - 같으면 git fetch도 없이 즉시 종료.
        if target_version and target_version == self.current_version():
            status = {"status": "ALREADY_LATEST", "version": target_version}
            self.publish_status(status)
            return status

        self.is_updating = True
        try:
            self.publish_status({"status": "UPDATING", "version": target_version})
            return self._do_update(target_version)
        finally:
            self.is_updating = False

    def _do_update(self, target_version: Optional[str]) -> dict:
        # fetch
        if self.runner.run(["git", "fetch", "origin"]).returncode != 0:
            return self._fail("Git Fetch Error", target_version)

        # 브랜치는 하드코딩하지 않고 현재 체크아웃된 브랜치를 따른다
        # (이 저장소는 master, 다른 환경은 main일 수 있음 - 둘 다 자동 대응).
        branch = self._current_branch()

        old = self._rev("HEAD")
        remote = self._rev(f"origin/{branch}")
        if old is None or remote is None:
            return self._fail("Git Rev Error", target_version)
        if old == remote:
            # 코드는 최신인데 버전만 다를 수 있음 - 버전 상태만 갱신하고 종료.
            if target_version:
                self._write_version(target_version)
            status = {"status": "ALREADY_LATEST", "commit": old[:7], "version": target_version or self.current_version()}
            self.publish_status(status)
            return status

        # pull
        if self.runner.run(["git", "pull", "origin", branch]).returncode != 0:
            return self._fail("Git Pull Error", target_version)

        changed = self._changed_files(old, remote)

        # requirements 변경 시에만 pip install (실패 시 롤백)
        if self.do_pip and any(REQUIREMENTS_MARKER in f for f in changed):
            if self.runner.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"]).returncode != 0:
                self._rollback(old)
                return self._fail("Pip Install Error", target_version)

        # 펌웨어 변경 시 UART 해제 -> compile -> upload (각 단계 실패 시 롤백)
        firmware_changed = any(FIRMWARE_MARKER in f and f.endswith(".ino") for f in changed)
        if firmware_changed and self.do_arduino:
            # arduino-cli가 포트를 쓰려면 main.py가 시리얼을 놓아줘야 한다.
            self.release_uart_fn()
            if self.runner.run(["arduino-cli", "compile", "--fqbn", self.arduino_fqbn, self.firmware_sketch_dir]).returncode != 0:
                self._rollback(old)
                return self._fail("Compile Error", target_version)
            if self.runner.run(["arduino-cli", "upload", "-p", self.arduino_port, "--fqbn", self.arduino_fqbn, self.firmware_sketch_dir]).returncode != 0:
                self._rollback(old)
                return self._fail("Arduino Upload Error", target_version)

        # 헬스체크 (Mega ping / UART / 실행 확인) - 실패 시 롤백.
        if self.health_check_fn is not None and not self.health_check_fn():
            self._rollback(old)
            return self._fail("Health Check Failed", target_version)

        # 버전 상태 저장 후 완료 보고.
        applied = target_version or remote[:7]
        self._write_version(applied)
        status = {
            "status": "UPDATE_COMPLETE",
            "version": applied,
            "commit": remote[:7],
            "firmware_updated": firmware_changed,
            "changed_files": changed,
            "update_time": self.now_fn(),
        }
        self.publish_status(status)

        # 자기 재시작 (python 프로세스 교체). 실기기에서는 이 아래로 안 내려옴.
        self.restart_fn()
        return status

    # ------------------------------------------------------------------
    def _rev(self, ref: str) -> Optional[str]:
        r = self.runner.run(["git", "rev-parse", ref])
        return r.stdout.strip() if r.returncode == 0 else None

    def _current_branch(self) -> str:
        # 현재 체크아웃된 브랜치명. detached HEAD면 안전하게 main으로 폴백.
        r = self.runner.run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
        b = r.stdout.strip() if r.returncode == 0 else ""
        return b if b and b != "HEAD" else "main"

    def _changed_files(self, old: str, new: str) -> List[str]:
        r = self.runner.run(["git", "diff", "--name-only", old, new])
        return [ln.strip() for ln in r.stdout.splitlines() if ln.strip()] if r.returncode == 0 else []

    def _rollback(self, old_commit: str) -> None:
        # 이전 정상 커밋으로 하드 리셋해서 깨진 상태를 남기지 않는다.
        print(f"[OTA] 롤백: git reset --hard {old_commit[:7]}")
        self.runner.run(["git", "reset", "--hard", old_commit])

    def current_version(self) -> str:
        try:
            with open(os.path.join(self.repo_dir, STATE_FILENAME), "r", encoding="utf-8") as f:
                return f.read().strip()
        except OSError:
            return "none"

    def _write_version(self, version: str) -> None:
        try:
            with open(os.path.join(self.repo_dir, STATE_FILENAME), "w", encoding="utf-8") as f:
                f.write(version)
        except OSError as e:
            print(f"[OTA] 버전 상태 저장 실패(무시): {e}")

    def _fail(self, reason: str, version: Optional[str]) -> dict:
        status = {"status": "UPDATE_FAILED", "reason": reason, "version": version}
        self.publish_status(status)
        return status

    def _default_restart(self) -> None:
        os.execv(sys.executable, [sys.executable] + sys.argv)
