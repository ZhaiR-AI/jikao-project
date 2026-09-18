[CmdletBinding()]
param(
    [string]$ListenAddress = "",
    [int]$Port = 0
)
$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Write-Host "This script installs dependencies and restarts the local app. It does not download new code."
& (Join-Path $scriptRoot 'install.ps1')
& (Join-Path $scriptRoot 'start.ps1') -Restart -ListenAddress $ListenAddress -Port $Port
