# Run this once after cloning the repo, from PowerShell:
#   .\setup.ps1
# Requires Python 3.12 to already be installed (python.org or `winget install Python.Python.3.12`).

$ErrorActionPreference = "Stop"

Write-Host "=== Checking Python ===" -ForegroundColor Cyan
python --version

Write-Host "=== Creating virtual environment (venv) ===" -ForegroundColor Cyan
if (-not (Test-Path "venv")) {
    python -m venv venv
} else {
    Write-Host "venv already exists, skipping"
}

Write-Host "=== Installing Python packages ===" -ForegroundColor Cyan
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\pip.exe install -r requirements.txt

Write-Host "=== Setting up .env ===" -ForegroundColor Cyan
if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example — edit it now and fill in KITE_API_KEY / KITE_API_SECRET" -ForegroundColor Yellow
} else {
    Write-Host ".env already exists, skipping"
}

Write-Host ""
Write-Host "=== Setup complete ===" -ForegroundColor Green
Write-Host ""
Write-Host "Next steps:"
Write-Host "  1. Edit .env and fill in KITE_API_KEY / KITE_API_SECRET (leave TRADING_MODE=paper)"
Write-Host "  2. Authenticate:   .\venv\Scripts\python.exe refresh_token.py"
Write-Host "  3. Run the bot:    .\venv\Scripts\python.exe main.py"
