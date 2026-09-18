[CmdletBinding()]
param(
    [string]$ListenAddress = "",
    [int]$Port = 0,
    [switch]$Restart
)

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Split-Path -Parent $scriptRoot
$python = Join-Path $scriptRoot ".venv\Scripts\python.exe"
# Preserve compatibility with the original developer checkout.
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    $python = Join-Path $projectRoot ".venv\Scripts\python.exe"
}
$pidFile = Join-Path $scriptRoot ".paper-server.pid"

if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    throw "Python environment not found. Run install.bat first (see README.md)."
}

if (-not $ListenAddress) {
    $ListenAddress = if ($env:PAPER_HOST) { $env:PAPER_HOST } else { "127.0.0.1" }
}

if ($Port -eq 0) {
    $Port = if ($env:PAPER_PORT) { [int]$env:PAPER_PORT } else { 8020 }
}
if ($Port -lt 1 -or $Port -gt 65535) {
    throw "Port must be between 1 and 65535."
}

function Get-ProcessInfo {
    param([int]$ProcessId)

    return Get-CimInstance Win32_Process -Filter "ProcessId = $ProcessId" -ErrorAction SilentlyContinue
}

function Test-ProjectServerProcess {
    param($ProcessInfo)

    if (-not $ProcessInfo) {
        return $false
    }
    $commandLine = ([string]$ProcessInfo.CommandLine).ToLowerInvariant()
    $executable = ([string]$ProcessInfo.ExecutablePath).ToLowerInvariant()
    $expectedPython = ([IO.Path]::GetFullPath($python)).ToLowerInvariant()
    return $commandLine.Contains("paper_server.py") -and (
        $executable -eq $expectedPython -or $commandLine.Contains($expectedPython)
    )
}

function Find-ProjectServerRoot {
    param([int]$ProcessId)

    $currentId = $ProcessId
    $matchedId = 0
    for ($depth = 0; $depth -lt 8 -and $currentId -gt 0; $depth++) {
        $processInfo = Get-ProcessInfo -ProcessId $currentId
        if (-not $processInfo) {
            break
        }
        if (Test-ProjectServerProcess -ProcessInfo $processInfo) {
            $matchedId = [int]$processInfo.ProcessId
        }
        $parentId = [int]$processInfo.ParentProcessId
        if ($parentId -le 0 -or $parentId -eq $currentId) {
            break
        }
        $currentId = $parentId
    }
    return $matchedId
}

function Stop-ProcessTree {
    param([int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId = $ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }
    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Get-PortListeners {
    return @(Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

function Stop-ExistingService {
    $stopped = @{}

    if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
        $storedText = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        $storedId = 0
        if ([int]::TryParse($storedText, [ref]$storedId) -and $storedId -gt 0) {
            $processInfo = Get-ProcessInfo -ProcessId $storedId
            if (Test-ProjectServerProcess -ProcessInfo $processInfo) {
                Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
                Stop-ProcessTree -ProcessId $storedId
                $stopped[$storedId] = $true
            }
        }
        Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
    }

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ((Get-PortListeners).Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 100
    }

    $listenerRoots = @{}
    $listenerProcessIds = @(Get-PortListeners | Select-Object -ExpandProperty OwningProcess -Unique)
    foreach ($listenerProcessId in $listenerProcessIds) {
        $rootId = Find-ProjectServerRoot -ProcessId ([int]$listenerProcessId)
        if ($rootId -le 0) {
            $processInfo = Get-ProcessInfo -ProcessId ([int]$listenerProcessId)
            if ($stopped.Count -gt 0 -and ([string]$processInfo.CommandLine).ToLowerInvariant().Contains("paper_server.py")) {
                $listenerRoots[[int]$listenerProcessId] = $true
                continue
            }
            throw "Port $Port is used by another process (PID $listenerProcessId): $($processInfo.CommandLine)"
        }
        $listenerRoots[$rootId] = $true
    }
    foreach ($rootId in $listenerRoots.Keys) {
        if (-not $stopped.ContainsKey([int]$rootId)) {
            Stop-ProcessTree -ProcessId $rootId
            $stopped[[int]$rootId] = $true
        }
    }

    for ($attempt = 0; $attempt -lt 20; $attempt++) {
        if ((Get-PortListeners).Count -eq 0) {
            break
        }
        Start-Sleep -Milliseconds 250
    }
    if ((Get-PortListeners).Count -gt 0) {
        throw "Timed out waiting for port $Port to be released."
    }

    if ($stopped.Count -gt 0) {
        Write-Host "Stopped previous paper_generation service." -ForegroundColor Yellow
    }
    else {
        Write-Host "No running paper_generation service was found." -ForegroundColor DarkGray
    }
}

$existingListeners = @(Get-PortListeners)
if ($Restart) {
    Write-Host "Restarting paper_generation ..." -ForegroundColor Cyan
    Stop-ExistingService
}
elseif ($existingListeners.Count -gt 0) {
    $listener = $existingListeners[0]
    $rootId = Find-ProjectServerRoot -ProcessId ([int]$listener.OwningProcess)
    if ($rootId -gt 0) {
        throw "paper_generation is already running on port $Port. Use -Restart to restart it."
    }
    throw "Port $Port is already in use by another process."
}

$env:PAPER_HOST = $ListenAddress
$env:PAPER_PORT = $Port.ToString()
$browserHost = if ($ListenAddress -in @("0.0.0.0", "::")) { "127.0.0.1" } else { $ListenAddress }

Write-Host "Starting paper_generation ..." -ForegroundColor Cyan
Write-Host "Exam:  http://${browserHost}:$Port/exam"
Write-Host "Study: http://${browserHost}:$Port/study"
Write-Host "Press Ctrl+C to stop."

$serverProcess = $null
try {
    $startInfo = [Diagnostics.ProcessStartInfo]::new()
    $startInfo.FileName = $python
    $startInfo.Arguments = "paper_server.py"
    $startInfo.WorkingDirectory = $scriptRoot
    $startInfo.UseShellExecute = $false
    $serverProcess = [Diagnostics.Process]::new()
    $serverProcess.StartInfo = $startInfo
    if (-not $serverProcess.Start()) {
        throw "Failed to start paper_generation."
    }
    Set-Content -LiteralPath $pidFile -Value $serverProcess.Id -Encoding ASCII
    while (-not $serverProcess.HasExited) {
        Wait-Process -Id $serverProcess.Id -Timeout 1 -ErrorAction SilentlyContinue
        $serverProcess.Refresh()
    }
    $serverProcess.WaitForExit()

    $isRegistered = $false
    if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
        $isRegistered = (Get-Content -LiteralPath $pidFile -Raw).Trim() -eq $serverProcess.Id.ToString()
    }
    if ($serverProcess.ExitCode -ne 0 -and $isRegistered) {
        throw "paper_generation exited with code $($serverProcess.ExitCode)."
    }
}
finally {
    if ($serverProcess -and -not $serverProcess.HasExited) {
        Stop-ProcessTree -ProcessId $serverProcess.Id
    }
    if (Test-Path -LiteralPath $pidFile -PathType Leaf) {
        $registeredId = (Get-Content -LiteralPath $pidFile -Raw).Trim()
        if ($serverProcess -and $registeredId -eq $serverProcess.Id.ToString()) {
            Remove-Item -LiteralPath $pidFile -Force -ErrorAction SilentlyContinue
        }
    }
}
