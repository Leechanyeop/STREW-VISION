# Jetson↔Mega 2필드 인터페이스 전환 및 Decision Engine 최초 연결

## 요약

Jetson↔Mega 통신을 7필드 방식에서 `{"command", "target"}` 2필드 방식으로 전환하고,
프로젝트 시작부터 한 번도 실행 흐름에 연결되지 않았던 `planner.plan_task()`(Decision
Engine)를 `state_machine.py`에 최초로 연결함. Mega의 다단계 진행상황 응답
(`RECEIVED`~`COMPLETE`)을 스트리밍으로 처리하는 구조로 `uart.py`/`state_machine.py`를
재설계함.

## 변경 사항

### robot/command.py
- `ArduinoCommand`를 7개 필드(`task_id`, `execute_task`, `move_sign`, `target_label`,
  `detected_label`, `x_center`, `y_center`) → 2개 필드(`command`, `target`)로 축소.
- `asdict()`가 필드명을 그대로 JSON 키로 사용하므로 필드명 자체를 신규 인터페이스
  명세(`{"command": "...", "target": "cell_x"}`)에 맞춤.

### robot/planner.py
- `ACTION_MAP`에서 `nutrition_needed` → `NUTRITION` 매핑 제거 (실제 펌프 하드웨어
  부재로 이번 인터페이스에서 완전히 제외 확정).
- `empty_cell` 매핑도 이미 제거된 상태 유지 (빈 셀은 설계상 존재해서는 안 되는
  상태로 간주, 모르는/미매핑 상태는 전부 `SKIP` 기본값으로 안전 처리).

### robot/uart.py
- `send_json_line()`을 "쓰기 전용"(`bool` 반환)으로 변경. 기존엔 쓰기+읽기를 한
  호출에서 처리했으나, 신규 프로토콜은 명령 1회 전송에 응답이 여러 번(최대 9회)
  오므로 책임을 분리함.
- `_read_json_line()` 헬퍼 추가 — 시리얼 한 줄 읽기 → `decode()` → `json.loads()`
  파싱을 전담.
- `stream_progress(payload, timeout_sec=30.0)` 제너레이터 신규 추가 — 명령을 1회
  전송 후 Mega가 보내는 진행상황 메시지를 `state == "COMPLETE"`까지 하나씩 `yield`.
  마지막 메시지 이후 `timeout_sec` 초과 시 타임아웃으로 종료 (단계별 정밀 타임아웃
  대신 공통 기준 채택 — 하드웨어 실측 데이터 부재로 인한 실용적 선택).
- `packet.py`의 `encode_packet()`을 재사용하도록 인코딩 로직 통합 (중복 제거).

### robot/packet.py
- 파일 상단에 설계 의도 문서화 (인코딩 규칙은 `packet.py`, 시리얼 I/O는 `uart.py`
  로 역할 분리).

### robot/protocol.py
- 삭제. 프로젝트 전체에서 미사용이었고, 값(`COMPLETION_FAILED`, `COMPLETION_RUNNING`)
  도 실제 Mega 프로토콜과 불일치.

### robot/state_machine.py
- `MOCK_TASK`(고정 딕셔너리) → `build_mock_task()`(호출마다 랜덤 `id`/`target_label`
  생성) 함수로 전환. AWS/실카메라 없이도 파이프라인 전체를 검증하기 위함.
- `run_once()`에 `planner.plan_task(task, vision)` 호출 최초 추가 — Decision
  Engine이 프로젝트 최초로 실제 실행 흐름에 연결됨.
- 예전 `build_command()`/`ArduinoCommand` 7필드 호출 제거, 2필드 명령
  (`{"command": decision["execute_task"], "target": task.get("target_label")}`)
  직접 조립으로 교체.
- `send_json_line()` 단발 호출을 `stream_progress()` 반복 처리로 교체, 마지막
  진행상황 메시지의 `state`를 최종 완료 상태로 사용.
- `build_command()` 메서드는 이제 미사용 상태로 남음 (삭제 여부 보류).

### ai/detector/result.py
- `VisionResult`에 `status: Optional[str] = None` 필드 추가.

### ai/detector/camera.py
- `MockVisionSource.read()`가 `status`를 `random.choice(["healthy",
  "powdery_mildew", "missing_plant"])`로 랜덤 생성하도록 수정.

### tests/test_uart.py
- 7개 케이스로 전면 재작성: 쓰기 성공/실패, `stream_progress`의 순차 상태 처리,
  COMPLETE 이후 읽기 중단, JSON 파싱 실패 시 `{"raw": ...}` 처리, 무응답 타임아웃,
  전송 실패 시 빈 결과.

### tests/test_decision.py
- `nutrition_needed` 관련 테스트 제거, `empty_cell` 관련 테스트 정리.

## 검증

```
pytest tests/ -q --ignore=tests/manual
16 passed
```

핵심 로직 스모크 테스트로 파이프라인 전체 연결 확인:
```
build_mock_task(): {'id': '838', 'target_label': 'cell_2'}
decision: {'execute_task': 'OBSERVE', ...}   # status: healthy 입력에 대해 정상 계산
command: {'command': 'OBSERVE', 'target': 'cell_2'}
```

## 알려진 이슈 / 다음 작업

- `cloud/api_client.py`에 진행상황(중간 보고) 전송용 함수가 아직 없음 — 다음
  작업에서 추가 예정.
- `robot/task_manager.py`의 `TaskQueue`는 현재 미사용이지만, 추후 `cloud/mqtt.py`
  (push 방식) 도입 시 필요해질 예정으로 보류.
- `ai/detector` 내 8개 미사용 스텁 파일(`detector.py`, `engine.py`, `inference.py`,
  `json_builder.py`, `parser.py`, `preprocess.py`, `calibration.py`, `capture.py`)
  정리 필요.
