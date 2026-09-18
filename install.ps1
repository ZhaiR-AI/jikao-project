[CmdletBinding()]
param()

$ErrorActionPreference = "Stop"
$scriptRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
$python = Join-Path $scriptRoot ".venv\Scripts\python.exe"

Push-Location $scriptRoot
try {
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        Write-Host "Creating a local Python 3.12 environment ..."
        $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
        if ($launcher) {
            & $launcher.Source -3.12 -m venv (Join-Path $scriptRoot '.venv')
        }
        else {
            $systemPython = Get-Command python.exe -ErrorAction SilentlyContinue
            if (-not $systemPython) {
                throw "Install Python 3.12 from https://www.python.org/downloads/windows/ and enable Add python.exe to PATH. Then run install.bat again."
            }
            & $systemPython.Source -c "import sys; sys.exit(0 if sys.version_info[:2] == (3, 12) else 1)"
            if ($LASTEXITCODE -ne 0) { throw "Python 3.12 is required. Install it, then run install.bat again." }
            & $systemPython.Source -m venv (Join-Path $scriptRoot '.venv')
        }
        if ($LASTEXITCODE -ne 0) { throw "Could not create the environment. Install Python 3.12, then retry install.bat." }
    }
    Write-Host "Installing dependencies (Internet connection required) ..."
    & $python -m pip install -r (Join-Path $scriptRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw "Dependency installation failed. Check the error above and your connection, then run install.bat again." }
    foreach ($name in @('models', '.env')) {
        $template = if ($name -eq 'models') { 'models.example.json' } else { '.env.example' }
        $destination = if ($name -eq 'models') { 'models.json' } else { '.env' }
        if (-not (Test-Path -LiteralPath $destination)) {
            Copy-Item -LiteralPath $template -Destination $destination
        }
    }
    Write-Host "Installation complete. Edit models.json using README.md, then double-click start.bat." -ForegroundColor Green
    Write-Host "Existing configuration and study data have been preserved."
}
finally {
    Pop-Location
}
