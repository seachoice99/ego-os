# Stops the Ego OS Windows Runner Agent and disables its scheduled task
# so it will NOT start again at your next login, until you re-enable it
# (Enable-ScheduledTask -TaskName 'EgoOS-WindowsRunnerAgent') or reinstall
# with windows-agent-install.ps1. Does not remove the task registration,
# the credential file, or any repository files -- use
# windows-agent-uninstall.ps1 to remove the task entirely.

$taskName = "EgoOS-WindowsRunnerAgent"
$lockFile = "$env:LOCALAPPDATA\EgoOS\claude-runner\ego-os-windows-agent.lock"
$legacyLockFile = "$env:LOCALAPPDATA\ego-os-windows-agent.lock"
if (-not (Test-Path $lockFile) -and (Test-Path $legacyLockFile)) { $lockFile = $legacyLockFile }

Write-Host "Disabling scheduled task '$taskName' (prevents auto-restart at next login)..."
Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
Disable-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue | Out-Null

if (Test-Path $lockFile) {
    $lock = Get-Content $lockFile | ConvertFrom-Json
    $proc = Get-Process -Id $lock.pid -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "Stopping agent process (pid $($lock.pid))..."
        Stop-Process -Id $lock.pid -Force
    }
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

Write-Host "Stopped. Re-enable with: Enable-ScheduledTask -TaskName '$taskName'"
