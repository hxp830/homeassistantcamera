$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
  python -m venv .venv
}

.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
}

Write-Host '请确认 models 目录下存在模型文件（默认 best.pt）'
uvicorn app.main:app --host 0.0.0.0 --port 8000
