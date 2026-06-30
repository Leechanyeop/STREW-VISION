from typing import Optional
from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .repository import Store, create_store
from .schemas import RobotResponse, RobotResponseCreate, RobotTask, RobotTaskCreate, VisionEvent, VisionEventCreate
from .settings import Settings, get_settings

settings = get_settings()
store = create_store(settings)
app = FastAPI(title=settings.app_name)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"] if settings.cors_origins == "*" else settings.cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")


def require_api_key(x_api_key: str = Header(default=""), cfg: Settings = Depends(get_settings)) -> None:
    if cfg.api_key != "change-me" and x_api_key != cfg.api_key:
        raise HTTPException(status_code=401, detail="invalid api key")


def get_store() -> Store:
    return store


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse("app/static/index.html")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "app": settings.app_name, "env": settings.env, "storage": settings.storage_backend}


@app.post("/robot/request", response_model=RobotTask, dependencies=[Depends(require_api_key)])
def create_robot_request(payload: RobotTaskCreate, repo: Store = Depends(get_store)) -> RobotTask:
    return repo.put_task(RobotTask(**payload.model_dump()))


@app.get("/robot/next", response_model=Optional[RobotTask], dependencies=[Depends(require_api_key)])
def get_next_robot_task(robot_id: str = Query(default="robot-01"), repo: Store = Depends(get_store)) -> Optional[RobotTask]:
    return repo.next_task(robot_id)


@app.post("/robot/response", response_model=RobotResponse, dependencies=[Depends(require_api_key)])
def create_robot_response(payload: RobotResponseCreate, repo: Store = Depends(get_store)) -> RobotResponse:
    response = repo.put_response(RobotResponse(**payload.model_dump()))
    sign = payload.completion_sign.upper()
    status = "done" if sign == "DONE" else "failed" if sign == "FAILED" else "running"
    repo.update_task_status(payload.task_id, status)
    return response


@app.post("/vision/event", response_model=VisionEvent, dependencies=[Depends(require_api_key)])
def create_vision_event(payload: VisionEventCreate, repo: Store = Depends(get_store)) -> VisionEvent:
    return repo.put_vision_event(VisionEvent(**payload.model_dump()))


@app.get("/robot/tasks", dependencies=[Depends(require_api_key)])
def list_robot_tasks(robot_id: Optional[str] = None, limit: int = 50, repo: Store = Depends(get_store)) -> dict:
    return {"items": repo.list_tasks(robot_id, limit)}


@app.get("/robot/responses", dependencies=[Depends(require_api_key)])
def list_robot_responses(robot_id: Optional[str] = None, limit: int = 50, repo: Store = Depends(get_store)) -> dict:
    return {"items": repo.list_responses(robot_id, limit)}
