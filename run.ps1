# Local dev launcher. Starts the API, waits for it, then the UI.
# Usage:  .\run.ps1          (in-process backends)
#         .\run.ps1 -Neo4j   (also starts Neo4j via docker compose)

param([switch]$Neo4j)

$ErrorActionPreference = "Stop"
$py = ".\.venv\Scripts\python.exe"

if (-not (Test-Path $py)) {
    Write-Host "No venv found. Creating one with Python 3.12..." -ForegroundColor Yellow
    py -3.12 -m venv .venv
    & $py -m pip install --upgrade pip
    & $py -m pip install -r requirements.txt
}

if ($Neo4j) {
    Write-Host "Starting Neo4j..." -ForegroundColor Cyan
    docker compose up -d neo4j
    $env:GRAPH_BACKEND = "neo4j"
    Write-Host "Neo4j Browser: http://localhost:7474 (neo4j / helios-dev-password)" -ForegroundColor Green
}

Write-Host "Starting API on http://127.0.0.1:8000 ..." -ForegroundColor Cyan
$api = Start-Process -FilePath $py -ArgumentList "-m","uvicorn","app.main:app","--host","127.0.0.1","--port","8000","--reload" -PassThru -NoNewWindow

# Streamlit rendering before the API is up produces a confusing connection error on
# first paint, so wait for /health rather than sleeping a fixed amount.
$ready = $false
foreach ($i in 1..40) {
    try {
        Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 2 | Out-Null
        $ready = $true; break
    } catch { Start-Sleep -Milliseconds 700 }
}
if (-not $ready) { Write-Host "API did not become healthy in time." -ForegroundColor Red; exit 1 }

Write-Host "API healthy. Docs: http://127.0.0.1:8000/docs" -ForegroundColor Green
Write-Host "Starting UI on http://localhost:8501 ..." -ForegroundColor Cyan
try {
    & $py -m streamlit run ui/streamlit_app.py --server.port 8501 --browser.gatherUsageStats false
} finally {
    Write-Host "Stopping API..." -ForegroundColor Yellow
    if ($api -and -not $api.HasExited) { Stop-Process -Id $api.Id -Force -ErrorAction SilentlyContinue }
}
