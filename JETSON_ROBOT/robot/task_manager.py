from cloud.api_client import CloudClient
from typing import List,Optional



class TaskQueue:
    
    def __init__(self) -> None:
        self._items: List[dict] = [] #딕셔너리가 들어있는 리스트

    def push(self, task: dict) -> None:
        self._items.append(task) # item 리스트 안에 task 딕셔너리 추가 
        # 즉task1 = {
        #"command": "MOVE",
        #"target": "cell_1"
        #} 를 1개 식 item 리스트 안에 넣는 것임.

    def pop(self) -> Optional[dict]:
        return self._items.pop(0) if self._items else None


def should_poll(now_sec: float, last_poll_sec: float, interval_sec: float) -> bool:
    return now_sec - last_poll_sec >= interval_sec


__all__ = ["CloudClient", "TaskQueue", "should_poll"]
