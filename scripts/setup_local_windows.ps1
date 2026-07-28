<#
.SYNOPSIS
    Set up the Chronos-2 Forecasting Tool on Windows with all artefacts on D: drive.
.DESCRIPTION
    Creates D:\Forecasting-Tool-Local with venv, caches, temp, and installs all
    dependencies.  Requires Python 3.12.
.PARAMETER LocalRoot
    Root directory for all local artefacts. Default: D:\Forecasting-Tool-Local
.PARAMETER PythonPath
    Full path to the Python 3.12 executable. If omitted, uses the Python launcher (py -3.12).
#>

param(
    [string]$LocalRoot = "D:\Forecasting-Tool-Local",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonCmd = ""

# ---- Step 1: Check D: drive -------------------------------------------------
if (-not (Test-Path ($LocalRoot -replace "\\[^\\]+$", ""))) {
    Write-Error "Drive for $LocalRoot not found. Cannot create local environment."
    exit 1
}

# ---- Step 2: Find Python 3.12 -----------------------------------------------
if ($PythonPath -and (Test-Path $PythonPath)) {
    $pythonCmd = $PythonPath
}
else {
    # Try the Python launcher first
    $pyExe = (Get-Command "py" -ErrorAction SilentlyContinue).Source
    if ($pyExe) {
        $verOutput = & $pyExe -3.12 --version 2>&1
        if ($LASTEXITCODE -eq 0 -and $verOutput -match "3\.12") {
            $pythonCmd = $pyExe
        }
    }
    # Fall back to searching PATH
    if (-not $pythonCmd) {
        $pathPython = (Get-Command "python" -ErrorAction SilentlyContinue).Source
        if ($pathPython) {
            $ver = & $pathPython --version 2>&1
            if ($ver -match "3\.12") {
                $pythonCmd = $pathPython
            }
        }
    }
}

if (-not $pythonCmd) {
    Write-Error @"
Python 3.12 is required but not found.
Install Python 3.12 from https://www.python.org/downloads/
Make sure to check "Add Python to PATH" during installation.
"@
    exit 1
}

# If using the launcher, build the full command
if ($pythonCmd -match "py(\.exe)?$") {
    $fullPython = "py -3.12"
}
else {
    $fullPython = $pythonCmd
}

Write-Host "Using Python: $fullPython"
$pyVer = & $fullPython --version 2>&1
Write-Host "Version: $pyVer"

# ---- Step 3: Create directory structure -------------------------------------
$dirs = @(
    "$LocalRoot\venv",
    "$LocalRoot\cache\pip",
    "$LocalRoot\cache\huggingface",
    "$LocalRoot\cache\transformers",
    "$LocalRoot\cache\torch",
    "$LocalRoot\temp",
    "$LocalRoot\test-output",
    "$LocalRoot\benchmarks"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Host "Directories created under $LocalRoot"

# ---- Step 4: Set environment variables --------------------------------------
$env:PIP_CACHE_DIR = "$LocalRoot\cache\pip"
$env:HF_HOME = "$LocalRoot\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "$LocalRoot\cache\huggingface"
$env:TRANSFORMERS_CACHE = "$LocalRoot\cache\transformers"
$env:TORCH_HOME = "$LocalRoot\cache\torch"
$env:TMP = "$LocalRoot\temp"
$env:TEMP = "$LocalRoot\temp"

Write-Host "Environment variables set (all point to D: drive)"

# ---- Step 5: Create virtual environment -------------------------------------
if (-not (Test-Path "$LocalRoot\venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    if ($pythonCmd -match "py(\.exe)?$") {
        & $pythonCmd -3.12 -m venv "$LocalRoot\venv"
    }
    else {
        & $pythonCmd -m venv "$LocalRoot\venv"
    }
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "Virtual environment already exists."
}

$venvPython = "$LocalRoot\venv\Scripts\python.exe"

# ---- Step 6: Upgrade pip ----------------------------------------------------
Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 7: Install PyTorch (CPU) ------------------------------------------
Write-Host "Installing PyTorch (CPU)..."
& $venvPython -m pip install "torch==2.13.0" --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 8: Install runtime dependencies -----------------------------------
Write-Host "Installing runtime dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 9: Install dev dependencies ---------------------------------------
Write-Host "Installing development dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements-dev.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 10: Verify environment --------------------------------------------
Write-Host "`nVerifying environment..."
& $venvPython "$repoRoot\scripts\verify_environment.py"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Environment verification failed."
    exit 1
}

# ---- Done -------------------------------------------------------------------
Write-Host @"

✅ Local environment ready!

  Virtual env : $venvPython
  Test runner : $venvPython -m pytest tests -v
  Smoke test  : $venvPython scripts\chronos2_smoke_test.py
  Benchmark   : $venvPython scripts\run_stage0_benchmark.py
  Streamlit   : $venvPython -m streamlit run app.py

  Cache dirs  : $LocalRoot\cache
  Benchmarks  : $LocalRoot\benchmarks

Run the verification script at any time:
  $venvPython scripts\verify_environment.py
"@
