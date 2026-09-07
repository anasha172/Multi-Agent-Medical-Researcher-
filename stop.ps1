# Stops MedResearch AI (Streamlit) using the PID recorded by start.ps1.
# Also sweeps for any stray "streamlit run app.py" process from this
# folder, in case the PID file is missing or stale.

$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$pidFile = Join-Path $PSScriptRoot "medresearch.pid"
$stopped = $false

# Stop-Process on a parent doesn't reliably take its children with it, and
# streamlit.exe launches a chain of python.exe children that do the actual
# serving -- kill the whole tree explicitly rather than relying on that.
function Stop-ProcessTree {
    param([int]$RootId)
    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$RootId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -RootId $child.ProcessId
    }
    Stop-Process -Id $RootId -Force -ErrorAction SilentlyContinue
}

if (Test-Path $pidFile) {
    $processId = Get-Content $pidFile -ErrorAction SilentlyContinue
    if ($processId) {
        $process = Get-Process -Id $processId -ErrorAction SilentlyContinue
        if ($process) {
            Stop-ProcessTree -RootId $processId
            Write-Host "Stopped MedResearch AI (PID $processId) and its child processes."
            $stopped = $true
        }
    }
    Remove-Item $pidFile -Force -ErrorAction SilentlyContinue
}

# Safety net: catch a stray process even if medresearch.pid was missing,
# stale, or pointed at an already-dead PID.
$escapedRoot = [Regex]::Escape($PSScriptRoot)
Get-CimInstance Win32_Process -Filter "Name='streamlit.exe' OR Name='python.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -match "app\.py" -and $_.CommandLine -match $escapedRoot } |
    ForEach-Object {
        Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
        Write-Host "Stopped stray process (PID $($_.ProcessId))."
        $stopped = $true
    }

if (-not $stopped) {
    Write-Host "MedResearch AI does not appear to be running."
}
