$ErrorActionPreference = "Stop"

$uvCommand = Get-Command uv -ErrorAction SilentlyContinue
if (-not $uvCommand) {
    throw "uv was not found. Install uv, then run this script again."
}

Push-Location $PSScriptRoot
try {
    $venvPath = Join-Path $PSScriptRoot ".venv"
    $pythonPath = Join-Path $venvPath "Scripts\python.exe"
    if (-not (Test-Path $pythonPath)) {
        & uv venv $venvPath
        if ($LASTEXITCODE -ne 0) {
            throw "Could not create the project Python environment."
        }
    }

    & uv pip install --python $pythonPath --requirements (Join-Path $PSScriptRoot "requirements.txt")
    if ($LASTEXITCODE -ne 0) {
        throw "Could not install the project Python dependencies."
    }

    Write-Host "Starting RCM Media at http://127.0.0.1:5000"
    Write-Host "On first run, open /setup to create the first editor account."
    try {
        & $pythonPath app.py
        exit $LASTEXITCODE
    }
    catch {
        if ($_.Exception.Message -notlike "*Application Control policy has blocked this file*") {
            throw
        }

        $venvConfig = Get-Content (Join-Path $venvPath "pyvenv.cfg")
        $homeSetting = $venvConfig | Where-Object { $_ -match '^home\s*=\s*(.+)$' } | Select-Object -First 1
        if (-not $homeSetting -or $homeSetting -notmatch '^home\s*=\s*(.+)$') {
            throw "Could not find the base Python interpreter for the project environment."
        }

        $basePythonDirectory = $Matches[1].Trim()
        $basePythonPath = Join-Path $basePythonDirectory "python.exe"
        if (-not (Test-Path $basePythonPath)) {
            throw "The base Python interpreter for the project environment was not found: $basePythonPath"
        }

        Write-Warning "Windows blocked the virtual environment executable. Starting with its base Python interpreter instead."
        $previousPythonPath = $env:PYTHONPATH
        $sitePackagesPath = Join-Path $venvPath "Lib\site-packages"
        if ($previousPythonPath) {
            $env:PYTHONPATH = "$sitePackagesPath;$previousPythonPath"
        }
        else {
            $env:PYTHONPATH = $sitePackagesPath
        }

        try {
            & $basePythonPath app.py
            exit $LASTEXITCODE
        }
        finally {
            $env:PYTHONPATH = $previousPythonPath
        }
    }
}
finally {
    Pop-Location
}
