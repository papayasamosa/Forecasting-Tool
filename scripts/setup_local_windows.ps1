<#
.SYNOPSIS
    Set up the Chronos-2 Forecasting Tool on Windows with all artefacts on D: drive.
.DESCRIPTION
    Creates D:\Forecasting-Tool-Local with venv, caches, temp, and installs all
    dependencies.  Requires Python 3.12.
#>

$ErrorActionPreference = "Stop"
$localRoot = "D:\Forecasting-Tool-Local"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonCmd = ""

# ---- Step 1: Check D: drive -----------------------------------------------
if (-not (Test-Path "D:\")) {
    Write-Error "D: drive not found. Cannot create local environment."
    exit 1
}

# ---- Step 2: Find Python 3.12 ---------------------------------------------
$candidates = @(
    "C:\Users\moham\AppData\Local\Programs\Python\Python312\python.exe",
    "C:\Program Files\Python312\python.exe",
    "C:\Python312\python.exe"
)
foreach ($c in $candidates) {
    if (Test-Path $c) {
        $pythonCmd = $c
        break
    }
}
# Also try PATH
if (-not $pythonCmd) {
    $pathPython = (Get-Command "python" -ErrorAction SilentlyContinue).Source
    if ($pathPython) {
        $ver = & $pathPython --version 2>&1
        if ($ver -match "3\.12") {
            $pythonCmd = $pathPython
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

Write-Host "Using Python: $pythonCmd"
$pyVer = & $pythonCmd --version 2>&1
Write-Host "Version: $pyVer"

# ---- Step 3: Create directory structure ------------------------------------
$dirs = @(
    "$localRoot\venv",
    "$localRoot\cache\pip",
    "$localRoot\cache\huggingface",
    "$localRoot\cache\transformers",
    "$localRoot\cache\torch",
    "$localRoot\temp",
    "$localRoot\test-output",
    "$localRoot\benchmarks"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Host "Directories created under $localRoot"

# ---- Step 4: Set environment variables -------------------------------------
$env:PIP_CACHE_DIR = "$localRoot\cache\pip"
$env:HF_HOME = "$localRoot\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "$localRoot\cache\huggingface"
$env:TRANSFORMERS_CACHE = "$localRoot\cache\transformers"
$env:TORCH_HOME = "$localRoot\cache\torch"
$env:TMP = "$localRoot\temp"
$env:TEMP = "$localRoot\temp"

Write-Host "Environment variables set (all point to D: drive)"

# ---- Step 5: Create virtual environment ------------------------------------
if (-not (Test-Path "$localRoot\venv\Scripts\python.exe")) {
    Write-Host "Creating virtual environment..."
    & $pythonCmd -m venv "$localRoot\venv"
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
} else {
    Write-Host "Virtual environment already exists."
}

$venvPython = "$localRoot\venv\Scripts\python.exe"

# ---- Step 6: Upgrade pip ---------------------------------------------------
Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 7: Install PyTorch (CPU) -----------------------------------------
Write-Host "Installing PyTorch (CPU)..."
& $venvPython -m pip install torch --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 8: Install runtime dependencies ----------------------------------
Write-Host "Installing runtime dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 9: Install dev dependencies --------------------------------------
Write-Host "Installing development dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements-dev.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 10: Verify environment -------------------------------------------
Write-Host "`nVerifying environment..."
& $venvPython "$repoRoot\scripts\verify_environment.py"
if ($LASTEXITCODE -ne 0) {
    Write-Error "Environment verification failed."
    exit 1
}

# ---- Done ------------------------------------------------------------------
Write-Host @"

✅ Local environment ready!

  Virtual env : $venvPython
  Test runner : $venvPython -m pytest tests -v
  Smoke test  : $venvPython scripts\chronos2_smoke_test.py
  Benchmark   : $venvPython scripts\run_stage0_benchmark.py
  Streamlit   : $venvPython -m streamlit run app.py

  Cache dirs  : $localRoot\cache
  Benchmarks  : $localRoot\benchmarks

Run the verification script at any time:
  $venvPython scripts\verify_environment.py
"@
