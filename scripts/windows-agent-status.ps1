# Reports whether the Ego OS Windows Runner Agent's scheduled task exists
# and its current state, whether the agent process is actually running,
# and tails its most recent log file.

$taskName = "EgoOS-WindowsRunnerAgent"
$lockFile = "$env:LOCALAPPDATA\EgoOS\claude-runner\ego-os-windows-agent.lock"
$legacyLockFile = "$env:LOCALAPPDATA\ego-os-windows-agent.lock"
$logDir = "$env:LOCALAPPDATA\EgoOS\claude-runner\logs"

# Builds before RUNNER-FIX stored the lock one directory too high. Keep a
# read-only fallback so status remains truthful until the currently-running
# legacy process is restarted onto the canonical path.
if (-not (Test-Path $lockFile) -and (Test-Path $legacyLockFile)) {
    $lockFile = $legacyLockFile
}

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Scheduled task '$taskName': $($task.State)"
} else {
    Write-Host "Scheduled task '$taskName' is not registered -- run windows-agent-install.ps1."
}

if (Test-Path $lockFile) {
    $lock = Get-Content $lockFile | ConvertFrom-Json
    $proc = Get-Process -Id $lock.pid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Agent process: RUNNING (pid $($lock.pid), started $($lock.created_at))"
    } else {
        Write-Host "Agent process: NOT running (stale lock file references pid $($lock.pid), which is gone)"
    }
} else {
    Write-Host "Agent process: NOT running (no lock file present)"
}

if (Test-Path $logDir) {
    $latest = Get-ChildItem $logDir -Filter "windows-agent-*.log" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
    if ($latest) {
        Write-Host ""
        Write-Host "Latest log: $($latest.FullName)"
        Write-Host "--- last 15 lines ---"
        Get-Content $latest.FullName -Tail 15
    } else {
        Write-Host "No log files found yet in $logDir"
    }
}
