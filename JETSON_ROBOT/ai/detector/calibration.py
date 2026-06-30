def load_calibration(path: str = "") -> dict:
    return {"path": path, "enabled": bool(path)}
