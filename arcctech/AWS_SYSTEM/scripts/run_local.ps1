$ErrorActionPreference = "Stop"
if (!(Test-Path ".env")) { Copy-Item ".env.example" ".env" }
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
