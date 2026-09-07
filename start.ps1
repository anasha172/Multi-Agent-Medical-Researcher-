# Starts MedResearch AI (Streamlit) in the background and records its PID
# in medresearch.pid so stop.ps1 can find and stop it later.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pidFile = Join-Path $PSScriptRoot "medresearch.pid"
$venvStreamlit = Join-Path $PSScriptRoot ".venv\Scripts\streamlit.exe"

if (-not (Test-Path $venvStreamlit)) {
    Write-Error "Virtual environment not found at .venv\Scripts\streamlit.exe. Run:`n  python -m venv .venv`n  .venv\Scripts\pip install -r requirements.txt"
    exit 1
}

if (Test-Path $pidFile) {
    $existingId = Get-Content $pidFile -ErrorAction SilentlyContinue
    $existingProcess = if ($existingId) { Get-Process -Id $existingId -ErrorAction SilentlyContinue } else { $null }
    if ($existingProcess) {
        Write-Host "MedResearch AI already appears to be running (PID $existingId)."
        Write-Host "Run stop.ps1 first if you want to restart it."
        exit 0
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path (Join-Path $PSScriptRoot ".env"))) {
    Write-Warning ".env not found -- copy .env.example to .env and fill in your API keys first."
}

# Logged to medresearch.log so a hung/crashed run can actually be diagnosed
# (a prior run of this app got stuck with no output captured anywhere).
$logFile = Join-Path $PSScriptRoot "medresearch.log"
$process = Start-Process -FilePath $venvStreamlit -ArgumentList "run", "app.py" `
    -WindowStyle Minimized -PassThru `
    -RedirectStandardOutput $logFile -RedirectStandardError "$logFile.err"
$process.Id | Out-File -FilePath $pidFile -Encoding ascii -NoNewline

Write-Host "MedResearch AI starting (PID $($process.Id))..."
Write-Host "Open http://localhost:8501 once it finishes loading."
Write-Host "Logs: $logFile / $logFile.err"
Write-Host "Run stop.ps1 (or stop.bat) to stop it."
