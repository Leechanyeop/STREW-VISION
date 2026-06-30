from robot.task_manager import TaskQueue


def test_task_queue_fifo():
    queue = TaskQueue()
    queue.push({"id": "1"})
    assert queue.pop() == {"id": "1"}
