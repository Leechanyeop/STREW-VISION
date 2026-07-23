"""[2026-07-23] OTA Update Manager v2.0 검증 - git/pip/arduino-cli/시리얼 없이 로직만.

v2.0 신규: 날짜 버전 비교, 업데이트 락, 롤백(git reset --hard), UART 해제 순서, 헬스체크.
"""

from types import SimpleNamespace

from updater.update_manager import UpdateManager


class FakeRunner:
    def __init__(self, script):
        self.script = script
        self.calls = []

    def run(self, args, check=False):
        self.calls.append(args)
        joined = " ".join(args)
        for subs, rc, out in self.script:
            if all(s in joined for s in subs):
                return SimpleNamespace(returncode=rc, stdout=out, stderr="" if rc == 0 else "err")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    def called(self, *subs):
        return any(all(s in " ".join(c) for s in subs) for c in self.calls)


def make(script, tmp_path, **kw):
    published, restarted, uart, health = [], [], [], []
    mgr = UpdateManager(
        repo_dir=str(tmp_path),
        runner=FakeRunner(script),
        publish_status=published.append,
        restart_fn=lambda: restarted.append(True),
        release_uart_fn=lambda: uart.append(True),
        health_check_fn=(lambda: health.append(True) or True) if kw.pop("with_health", False) else None,
        now_fn=lambda: "2026-07-23 16:42:31",
        **kw,
    )
    return mgr, published, restarted, uart


PULL_FW = [
    (["fetch"], 0, ""),
    (["rev-parse", "HEAD"], 0, "old"),
    (["rev-parse", "origin/main"], 0, "new"),
    (["pull"], 0, ""),
    (["diff", "--name-only"], 0, "jetson_robot/mega_firmware/mega_firmware.ino\n"),
    (["arduino-cli", "compile"], 0, "ok"),
    (["arduino-cli", "upload"], 0, "ok"),
]


def test_version_match_skips_fetch(tmp_path):
    (tmp_path / ".ota_state").write_text("20260723164200")
    mgr, published, restarted, uart = make([], tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "20260723164200"})
    assert result["status"] == "ALREADY_LATEST"
    assert mgr.runner.calls == []           # git fetch조차 안 함
    assert restarted == []


def test_update_lock_blocks_concurrent(tmp_path):
    mgr, published, restarted, uart = make([], tmp_path)
    mgr.is_updating = True
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "ALREADY_UPDATING"


def test_firmware_update_releases_uart_before_upload(tmp_path):
    mgr, published, restarted, uart = make(PULL_FW, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "20260723164200"})
    assert result["status"] == "UPDATE_COMPLETE"
    assert result["firmware_updated"] is True
    assert result["update_time"] == "2026-07-23 16:42:31"
    assert uart == [True]                    # UART 해제 호출됨
    # 버전 상태 파일이 갱신됨
    assert (tmp_path / ".ota_state").read_text() == "20260723164200"
    # UPDATING -> UPDATE_COMPLETE 순서로 보고
    assert published[0]["status"] == "UPDATING"
    assert published[-1]["status"] == "UPDATE_COMPLETE"


def test_compile_failure_rolls_back(tmp_path):
    script = PULL_FW[:5] + [(["arduino-cli", "compile"], 1, "")]
    mgr, published, restarted, uart = make(script, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "UPDATE_FAILED"
    assert result["reason"] == "Compile Error"
    assert mgr.runner.called("reset", "--hard", "old")   # 롤백 수행
    assert restarted == []


def test_upload_failure_rolls_back(tmp_path):
    script = PULL_FW[:6] + [(["arduino-cli", "upload"], 1, "")]
    mgr, published, restarted, uart = make(script, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "UPDATE_FAILED"
    assert result["reason"] == "Arduino Upload Error"
    assert mgr.runner.called("reset", "--hard", "old")


def test_python_only_change_no_uart_no_arduino(tmp_path):
    script = [
        (["fetch"], 0, ""),
        (["rev-parse", "HEAD"], 0, "old"),
        (["rev-parse", "origin/main"], 0, "new"),
        (["pull"], 0, ""),
        (["diff", "--name-only"], 0, "jetson_robot/main.py\n"),
    ]
    mgr, published, restarted, uart = make(script, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "UPDATE_COMPLETE"
    assert result["firmware_updated"] is False
    assert uart == []                        # 펌웨어 변경 없으니 UART 해제 안 함
    assert not mgr.runner.called("arduino-cli")
    assert restarted == [True]


def test_requirements_change_pip_failure_rolls_back(tmp_path):
    script = [
        (["fetch"], 0, ""),
        (["rev-parse", "HEAD"], 0, "old"),
        (["rev-parse", "origin/main"], 0, "new"),
        (["pull"], 0, ""),
        (["diff", "--name-only"], 0, "requirements.txt\n"),
        (["pip", "install"], 1, ""),
    ]
    mgr, published, restarted, uart = make(script, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "UPDATE_FAILED"
    assert result["reason"] == "Pip Install Error"
    assert mgr.runner.called("reset", "--hard", "old")


def test_health_check_failure_rolls_back(tmp_path):
    published, restarted = [], []
    mgr = UpdateManager(
        repo_dir=str(tmp_path),
        runner=FakeRunner(PULL_FW),
        publish_status=published.append,
        restart_fn=lambda: restarted.append(True),
        release_uart_fn=lambda: None,
        health_check_fn=lambda: False,       # 헬스체크 실패
        now_fn=lambda: "t",
    )
    result = mgr.handle_update_command({"command": "UPDATE", "version": "v2"})
    assert result["status"] == "UPDATE_FAILED"
    assert result["reason"] == "Health Check Failed"
    assert restarted == []


def test_same_commit_but_new_version_updates_state(tmp_path):
    script = [
        (["fetch"], 0, ""),
        (["rev-parse", "HEAD"], 0, "same"),
        (["rev-parse", "origin/main"], 0, "same"),   # 코드 동일
    ]
    mgr, published, restarted, uart = make(script, tmp_path)
    result = mgr.handle_update_command({"command": "UPDATE", "version": "20260723164200"})
    assert result["status"] == "ALREADY_LATEST"
    assert (tmp_path / ".ota_state").read_text() == "20260723164200"


def test_non_update_command_ignored(tmp_path):
    mgr, published, restarted, uart = make([], tmp_path)
    assert mgr.handle_update_command({"command": "NOPE"})["status"] == "IGNORED"
