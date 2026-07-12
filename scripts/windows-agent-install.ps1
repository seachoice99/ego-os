# Installs the Ego OS Windows Runner Agent as a Scheduled Task: starts
# automatically at your next login (or right away via
# Start-ScheduledTask), runs hidden (no visible console window), and
# restarts itself a bounded number of times if it crashes.
#
# Usage:
#   .\scripts\windows-agent-install.ps1 -AgentToken "<token from the VPS>"
#
# The token is shown ONCE by control_server.js when it first generates
# one (check its own console output / journalctl on the VPS). It is
# stored here in a local file readable only by your own Windows account
# -- never committed to Git, never printed back out by this script.

param(
    [Parameter(Mandatory = $true)]
    [string]$AgentToken,
    [string]$ServerUrl = "https://os.fiveseven.ru"
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path $PSScriptRoot -Parent
$taskName = "EgoOS-WindowsRunnerAgent"
$credDir = "$env:LOCALAPPDATA\EgoOS\claude-runner\control"
$credFile = "$credDir\agent_token.env"
$logDir = "$env:LOCALAPPDATA\EgoOS\claude-runner\logs"

New-Item -ItemType Directory -Force -Path $credDir | Out-Null
New-Item -ItemType Directory -Force -Path $logDir | Out-Null

"EGO_OS_AGENT_TOKEN=$AgentToken`nEGO_OS_AGENT_SERVER_URL=$ServerUrl`n" |
    Set-Content -Path $credFile -NoNewline -Encoding utf8

# Restrict the token file to the current user only -- remove inherited
# permissions, grant read/write to this account alone.
icacls $credFile /inheritance:r | Out-Null
icacls $credFile /grant:r "$($env:USERDOMAIN)\$($env:USERNAME):(R,W)" | Out-Null

$existing = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host "Task '$taskName' already exists -- removing it first so this reinstall is clean."
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
}

$wrapperPath = Join-Path $repoRoot "scripts\windows-agent-run-hidden.ps1"
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-WindowStyle Hidden -NoProfile -ExecutionPolicy Bypass -File `"$wrapperPath`"" `
    -WorkingDirectory $repoRoot
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet `
    -Hidden `
    -RestartCount 5 -RestartInterval (New-TimeSpan -Minutes 2) `
    -ExecutionTimeLimit (New-TimeSpan) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings -Principal $principal -Force | Out-Null

Write-Host ""
Write-Host "Installed. The agent will start automatically the next time you log in to Windows."
Write-Host "To start it right now without logging out:"
Write-Host "  Start-ScheduledTask -TaskName '$taskName'"
Write-Host "To check status: .\scripts\windows-agent-status.ps1"
