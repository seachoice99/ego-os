# Completely removes the Ego OS Windows Runner Agent's scheduled task.
# Leaves the credential file and repository untouched -- delete
# %LOCALAPPDATA%\EgoOS\claude-runner\control\agent_token.env yourself if
# you no longer need it, and remember this agent's registration still
# exists server-side (control_server.js's agents.json) until it naturally
# ages out or you clean it up there too.

$taskName = "EgoOS-WindowsRunnerAgent"
$lockFile = "$env:LOCALAPPDATA\EgoOS\claude-runner\ego-os-windows-agent.lock"
$legacyLockFile = "$env:LOCALAPPDATA\ego-os-windows-agent.lock"
if (-not (Test-Path $lockFile) -and (Test-Path $legacyLockFile)) { $lockFile = $legacyLockFile }

$task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($task) {
    Write-Host "Stopping and removing scheduled task '$taskName'..."
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
} else {
    Write-Host "Scheduled task '$taskName' was not registered."
}

if (Test-Path $lockFile) {
    $lock = Get-Content $lockFile | ConvertFrom-Json
    Stop-Process -Id $lock.pid -Force -ErrorAction SilentlyContinue
    Remove-Item $lockFile -Force -ErrorAction SilentlyContinue
}

Write-Host ""
Write-Host "Scheduled task removed. Left in place (delete manually if no longer needed):"
Write-Host "  $env:LOCALAPPDATA\EgoOS\claude-runner\control\agent_token.env"
Write-Host "  $env:LOCALAPPDATA\EgoOS\claude-runner\logs\ (past logs)"
