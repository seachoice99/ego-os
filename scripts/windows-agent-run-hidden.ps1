# Ego OS Windows Runner Agent -- launched by the Scheduled Task
# "EgoOS-WindowsRunnerAgent" (see windows-agent-install.ps1). Not meant to
# be run directly by a human -- the task itself is what supplies the
# hidden window (-WindowStyle Hidden on the powershell.exe action); this
# script just loads the protected token file, sets env vars, and runs
# the agent, redirecting its own output to a timestamped log file.

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $repoRoot

$credFile = "$env:LOCALAPPDATA\EgoOS\claude-runner\control\agent_token.env"
if (-not (Test-Path $credFile)) {
    Write-Error "Agent token file not found at $credFile -- run windows-agent-install.ps1 first."
    exit 1
}
Get-Content $credFile | ForEach-Object {
    if ($_ -match '^([^=]+)=(.*)$') {
        [System.Environment]::SetEnvironmentVariable($matches[1], $matches[2], "Process")
    }
}

$logDir = "$env:LOCALAPPDATA\EgoOS\claude-runner\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyy-MM-ddTHH-mm-ss"
$logFile = Join-Path $logDir "windows-agent-$stamp.log"

# `&` blocks until node exits -- the scheduled task's own restart policy
# (RestartCount/RestartInterval in windows-agent-install.ps1) takes over
# from there if it exits unexpectedly.
& node "automation\windows_agent.js" *> $logFile
exit $LASTEXITCODE
