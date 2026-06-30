from cloud.api_client import CloudClient


class TaskQueue:
    def __init__(self) -> None:
        self._items: list[dict] = []

    def push(self, task: dict) -> None:
        self._items.append(task)

    def pop(self) -> dict | None:
        return self._items.pop(0) if self._items else None


def should_poll(now_sec: float, last_poll_sec: float, interval_sec: float) -> bool:
    return now_sec - last_poll_sec >= interval_sec


__all__ = ["CloudClient", "TaskQueue", "should_poll"]
