$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

if (-not (Test-Path .venv)) {
  python -m venv .venv
  $freshVenv = $true
}

. .\.venv\Scripts\Activate.ps1

# Reinstall only when requirements changed, so restarts stay fast.
$stamp = '.venv\.requirements.sha256'
$currentHash = (Get-FileHash requirements.txt -Algorithm SHA256).Hash
$previousHash = if (Test-Path $stamp) { Get-Content $stamp -Raw } else { '' }
if ($freshVenv -or $currentHash -ne $previousHash.Trim()) {
  pip install -r requirements.txt
  Set-Content -Path $stamp -Value $currentHash
}

if (-not (Test-Path .env)) {
  Copy-Item .env.example .env
  Write-Host '已从 .env.example 创建 .env，请按需修改后重新运行。' -ForegroundColor Yellow
}

if (-not (Get-ChildItem -Path models -Filter *.pt -ErrorAction SilentlyContinue)) {
  Write-Host 'models 目录下没有 .pt 模型，将使用内置的 mediapipe_hands 引擎。' -ForegroundColor Yellow
}

$env:PYTHONPATH = $PSScriptRoot
$listenHost = if ($env:HOST) { $env:HOST } else { '0.0.0.0' }
$port = if ($env:PORT) { $env:PORT } else { '8000' }
uvicorn app.main:app --host $listenHost --port $port
