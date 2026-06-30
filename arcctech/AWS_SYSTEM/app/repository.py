import json
import os
from threading import Lock
from typing import Any, Dict, List, Optional

import boto3
from boto3.dynamodb.conditions import Key

from .schemas import RobotResponse, RobotTask, TaskStatus, VisionEvent, utc_now
from .settings import Settings


class Store:
    def put_task(self, task: RobotTask) -> RobotTask: raise NotImplementedError
    def next_task(self, robot_id: str) -> Optional[RobotTask]: raise NotImplementedError
    def update_task_status(self, task_id: str, status: TaskStatus) -> Optional[RobotTask]: raise NotImplementedError
    def put_response(self, response: RobotResponse) -> RobotResponse: raise NotImplementedError
    def put_vision_event(self, event: VisionEvent) -> VisionEvent: raise NotImplementedError
    def list_tasks(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]: raise NotImplementedError
    def list_responses(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]: raise NotImplementedError


class LocalJsonStore(Store):
    def __init__(self, path: str) -> None:
        self.path = path
        self.lock = Lock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        if not os.path.exists(path):
            self._write({"tasks": [], "responses": [], "vision_events": []})

    def _read(self) -> Dict[str, List[Dict[str, Any]]]:
        with open(self.path, "r", encoding="utf-8") as f:
            return json.load(f)

    def _write(self, data: Dict[str, List[Dict[str, Any]]]) -> None:
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def put_task(self, task: RobotTask) -> RobotTask:
        with self.lock:
            data = self._read()
            data["tasks"].append(task.model_dump())
            self._write(data)
        return task

    def next_task(self, robot_id: str) -> Optional[RobotTask]:
        with self.lock:
            data = self._read()
            for item in data["tasks"]:
                if item["robot_id"] == robot_id and item["status"] == "queued":
                    item["status"] = "sent"
                    item["updated_at"] = utc_now()
                    self._write(data)
                    return RobotTask(**item)
        return None

    def update_task_status(self, task_id: str, status: TaskStatus) -> Optional[RobotTask]:
        with self.lock:
            data = self._read()
            for item in data["tasks"]:
                if item["id"] == task_id:
                    item["status"] = status
                    item["updated_at"] = utc_now()
                    self._write(data)
                    return RobotTask(**item)
        return None

    def put_response(self, response: RobotResponse) -> RobotResponse:
        with self.lock:
            data = self._read()
            data["responses"].append(response.model_dump())
            self._write(data)
        return response

    def put_vision_event(self, event: VisionEvent) -> VisionEvent:
        with self.lock:
            data = self._read()
            data["vision_events"].append(event.model_dump())
            self._write(data)
        return event

    def list_tasks(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
        items = self._read()["tasks"]
        if robot_id:
            items = [x for x in items if x["robot_id"] == robot_id]
        return list(reversed(items))[:limit]

    def list_responses(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
        items = self._read()["responses"]
        if robot_id:
            items = [x for x in items if x["robot_id"] == robot_id]
        return list(reversed(items))[:limit]


class DynamoStore(Store):
    def __init__(self, settings: Settings) -> None:
        self.table = boto3.resource("dynamodb", region_name=settings.aws_region).Table(settings.dynamodb_table)

    @staticmethod
    def _pk(kind: str, robot_id: str) -> str:
        return f"{kind}#{robot_id}"

    def put_task(self, task: RobotTask) -> RobotTask:
        item = task.model_dump()
        item.update({"pk": self._pk("TASK", task.robot_id), "sk": f"{task.created_at}#{task.id}"})
        self.table.put_item(Item=item)
        return task

    def next_task(self, robot_id: str) -> Optional[RobotTask]:
        for item in reversed(self.list_tasks(robot_id, 50)):
            if item.get("status") == "queued":
                return self.update_task_status(item["id"], "sent")
        return None

    def update_task_status(self, task_id: str, status: TaskStatus) -> Optional[RobotTask]:
        for item in self.list_tasks(None, 200):
            if item.get("id") == task_id:
                item["status"] = status
                item["updated_at"] = utc_now()
                self.table.put_item(Item=item)
                return RobotTask(**{k: v for k, v in item.items() if k not in {"pk", "sk"}})
        return None

    def put_response(self, response: RobotResponse) -> RobotResponse:
        item = response.model_dump()
        item.update({"pk": self._pk("RESPONSE", response.robot_id), "sk": f"{response.created_at}#{response.id}"})
        self.table.put_item(Item=item)
        return response

    def put_vision_event(self, event: VisionEvent) -> VisionEvent:
        item = event.model_dump()
        item.update({"pk": self._pk("VISION", event.robot_id), "sk": f"{event.created_at}#{event.id}"})
        self.table.put_item(Item=item)
        return event

    def _query_kind(self, kind: str, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
        if robot_id:
            result = self.table.query(KeyConditionExpression=Key("pk").eq(self._pk(kind, robot_id)), ScanIndexForward=False, Limit=limit)
            return result.get("Items", [])
        result = self.table.scan(Limit=limit)
        return [x for x in result.get("Items", []) if x.get("pk", "").startswith(f"{kind}#")]

    def list_tasks(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
        return self._query_kind("TASK", robot_id, limit)

    def list_responses(self, robot_id: Optional[str], limit: int) -> List[Dict[str, Any]]:
        return self._query_kind("RESPONSE", robot_id, limit)


def create_store(settings: Settings) -> Store:
    if settings.storage_backend.lower() == "dynamodb":
        return DynamoStore(settings)
    return LocalJsonStore(settings.local_store_path)
