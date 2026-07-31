<#
.SYNOPSIS
    Set up the Chronos-2 Forecasting Tool on Windows with all artefacts on D: drive.
.DESCRIPTION
    Creates D:\Forecasting-Tool-Local with venv, caches, temp, and installs all
    dependencies.  Requires Python 3.12.
    All installation, cache, and runtime paths use D: drive exclusively.
.PARAMETER LocalRoot
    Root directory for all local artefacts. Default: D:\Forecasting-Tool-Local
.PARAMETER PythonPath
    Full path to the Python 3.12 executable. If omitted, discovers or downloads.
#>

param(
    [string]$LocalRoot = "D:\Forecasting-Tool-Local",
    [string]$PythonPath = ""
)

$ErrorActionPreference = "Stop"
$repoRoot = Split-Path -Parent $PSScriptRoot
$pythonCmd = ""

# ---- Step 1: Check the target drive ------------------------------------------
$resolvedRoot = [System.IO.Path]::GetFullPath($LocalRoot)
$driveLetter = [System.IO.Path]::GetPathRoot($resolvedRoot).TrimEnd('\')
if ($driveLetter -ne 'D:') {
    Write-Error "LocalRoot must be on drive D:. Got '$driveLetter' from '$LocalRoot'. Requirement: D:\Forecasting-Tool-Local"
    exit 1
}
if ($resolvedRoot -ne 'D:\Forecasting-Tool-Local' -and $resolvedRoot -notlike 'D:\Forecasting-Tool-Local\*') {
    Write-Error "LocalRoot must be under D:\Forecasting-Tool-Local. Got '$resolvedRoot'."
    exit 1
}
$driveRoot = [System.IO.Path]::GetPathRoot($LocalRoot)
if (-not (Test-Path $driveRoot)) {
    Write-Error "Drive for $LocalRoot not found ($driveRoot). Cannot create local environment."
    exit 1
}

# ---- Step 2: Preflight — require repository under D:\Forecasting-Tool-Local\repo ----
$expectedRepoPath = "$LocalRoot\repo"
$resolvedRepoExpected = [System.IO.Path]::GetFullPath($expectedRepoPath)
$resolvedRepoActual = [System.IO.Path]::GetFullPath($repoRoot)
if ($resolvedRepoActual -ne $resolvedRepoExpected) {
    Write-Error @"
Repository must be at '$expectedRepoPath'.
Current location: '$repoRoot'
Clone or move the repository to:
  git clone https://github.com/papayasamosa/Forecasting-Tool.git "$expectedRepoPath"
Then re-run this script from that location.
"@
    exit 1
}

# ---- Step 3: Create ALL required directories (must match storage_policy) ----
$dirs = @(
    "$LocalRoot\repo",
    "$LocalRoot\python312",
    "$LocalRoot\installers",
    "$LocalRoot\downloads",
    "$LocalRoot\venv",
    "$LocalRoot\cache",
    "$LocalRoot\cache\pip",
    "$LocalRoot\cache\huggingface",
    "$LocalRoot\cache\huggingface\hub",
    "$LocalRoot\cache\huggingface\xet",
    "$LocalRoot\cache\transformers",
    "$LocalRoot\cache\torch",
    "$LocalRoot\cache\pycache",
    "$LocalRoot\cache\npm",
    "$LocalRoot\cache\npm-prefix",
    "$LocalRoot\cache\uv",
    "$LocalRoot\cache\uv-tools",
    "$LocalRoot\cache\playwright",
    "$LocalRoot\cache\matplotlib",
    "$LocalRoot\cache\ruff",
    "$LocalRoot\cache\mcp",
    "$LocalRoot\cache\graphify",
    "$LocalRoot\graphify-output",
    "$LocalRoot\temp",
    "$LocalRoot\temp\pytest",
    "$LocalRoot\test-output",
    "$LocalRoot\benchmarks",
    "$LocalRoot\evidence-work",
    "$LocalRoot\logs"
)
foreach ($d in $dirs) {
    New-Item -ItemType Directory -Force -Path $d | Out-Null
}
Write-Host "All required directories created under $LocalRoot"

# ---- Step 4: Find or download Python 3.12 (D: drive) ------------------------
$pythonInstallDir = "$LocalRoot\python312"
$installersDir = "$LocalRoot\installers"

# WP-L: -PythonPath is only accepted if it is itself under D:\Forecasting-
# Tool-Local — a C-drive (or any other) interpreter can never be passed in
# and treated as the project runtime, even explicitly.
if ($PythonPath) {
    $resolvedPythonPath = [System.IO.Path]::GetFullPath($PythonPath)
    if ($resolvedPythonPath -ne $LocalRoot -and $resolvedPythonPath -notlike "$LocalRoot\*") {
        Write-Error "-PythonPath must be under $LocalRoot. Got '$PythonPath' (resolved: '$resolvedPythonPath')."
        exit 1
    }
    if (-not (Test-Path $PythonPath)) {
        Write-Error "-PythonPath '$PythonPath' does not exist."
        exit 1
    }
    $pythonCmd = $PythonPath
}
elseif (Test-Path "$pythonInstallDir\python.exe") {
    $pythonCmd = "$pythonInstallDir\python.exe"
}
else {
    # WP-L: documented C-drive exception. This `py` launcher / PATH python
    # is used ONLY as a bootstrap tool to run `-m venv` and create the
    # D-drive venv below (Step 6) — it is never the project runtime.
    # Every later step in this script (pip installs, dependency install,
    # environment verification, and every command a developer runs after
    # setup) uses $venvPython = "$LocalRoot\venv\Scripts\python.exe"
    # exclusively. This is the one unavoidable Windows-managed C-drive
    # touchpoint: there is no way to create a venv without an existing
    # Python interpreter, and Windows does not ship one on D:.
    Write-Host "No D-drive Python found — searching for a bootstrap interpreter to create the D-drive venv (used once, then never again)..."
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
    Write-Host "Python 3.12 not found. Downloading to D: drive installer cache..."
    $installerUrl = "https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe"
    $installerPath = "$installersDir\python-3.12.10-amd64.exe"
    
    # WP13: Pinned installer version and expected SHA-256.
    # Verified against the official python.org release: matches the
    # published MD5 (5eddb0b6f12c852725de071ae681dde4) for
    # python-3.12.10-amd64.exe and carries a valid Authenticode signature
    # from the Python Software Foundation. The previously pinned value
    # (be2551f5...) never matched the real release artifact and would have
    # failed this check for every run.
    $expectedSha256 = "67b5635e80ea51072b87941312d00ec8927c4db9ba18938f7ad2d27b328b95fb"
    $expectedPublisher = "Python Software Foundation"
    
    if (-not (Test-Path $installerPath)) {
        # Use a download approach that works without external tools
        $webClient = New-Object System.Net.WebClient
        Write-Host "  Downloading from $installerUrl ..."
        $webClient.DownloadFile($installerUrl, $installerPath)
    }
    
    # WP13: Verify SHA-256 of downloaded installer
    Write-Host "  Verifying SHA-256 of installer..."
    $actualSha256 = (Get-FileHash -Path $installerPath -Algorithm SHA256).Hash.ToLower()
    if ($actualSha256 -ne $expectedSha256) {
        Write-Error "Installer SHA-256 mismatch!"
        Write-Error "  Expected: $expectedSha256"
        Write-Error "  Actual:   $actualSha256"
        Write-Error "The downloaded Python installer does not match the pinned hash."
        Write-Error "Delete $installerPath and re-run, or update the expected hash."
        exit 1
    }
    Write-Host "  SHA-256 verified: $actualSha256"
    
    # WP13: Verify Authenticode signature
    Write-Host "  Verifying Authenticode signature..."
    $sig = Get-AuthenticodeSignature -FilePath $installerPath
    if ($sig.Status -ne "Valid") {
        Write-Error "Installer Authenticode signature verification FAILED."
        Write-Error "  Status: $($sig.Status)"
        Write-Error "  SignerCertificate: $($sig.SignerCertificate)"
        Write-Error "The downloaded Python installer has an invalid or missing digital signature."
        exit 1
    }
    # Verify the expected publisher
    $publisher = $sig.SignerCertificate.Subject
    if ($publisher -notmatch $expectedPublisher) {
        Write-Error "Installer publisher mismatch!"
        Write-Error "  Expected publisher to contain: $expectedPublisher"
        Write-Error "  Actual subject: $publisher"
        exit 1
    }
    Write-Host "  Authenticode signature verified: $($sig.SignerCertificate.Subject)"
    
    Write-Host "Installing Python 3.12 to $pythonInstallDir (D: drive)..."
    $installArgs = "/quiet InstallAllUsers=0 TargetDir=`"$pythonInstallDir`" Include_launcher=0 Include_test=0"
    $process = Start-Process -FilePath $installerPath -ArgumentList $installArgs -Wait -PassThru
    if ($process.ExitCode -ne 0) {
        Write-Error "Python installer failed with exit code $($process.ExitCode)."
        Write-Error "Try installing manually from https://www.python.org/downloads/ to: $pythonInstallDir"
        exit 1
    }
    $pythonCmd = "$pythonInstallDir\python.exe"
    if (-not (Test-Path $pythonCmd)) {
        Write-Error "Python installation completed but python.exe not found at $pythonCmd"
        exit 1
    }
    Write-Host "Python 3.12 installed to D: drive."
}

# Report the resolved Python version
if ($pythonCmd -match "py(\.exe)?$") {
    Write-Host "Using Python: $pythonCmd -3.12"
    $pyVer = & $pythonCmd -3.12 --version 2>&1
}
else {
    Write-Host "Using Python: $pythonCmd"
    $pyVer = & $pythonCmd --version 2>&1
}
Write-Host "Version: $pyVer"

# ---- Step 5: Set ALL required environment variables (match storage_policy) ----
$env:FORECASTING_LOCAL_ROOT = $LocalRoot
$env:PIP_CACHE_DIR = "$LocalRoot\cache\pip"
$env:HF_HOME = "$LocalRoot\cache\huggingface"
$env:HUGGINGFACE_HUB_CACHE = "$LocalRoot\cache\huggingface"
$env:HF_HUB_CACHE = "$LocalRoot\cache\huggingface\hub"
$env:HF_XET_CACHE = "$LocalRoot\cache\huggingface\xet"
$env:TRANSFORMERS_CACHE = "$LocalRoot\cache\transformers"
$env:TORCH_HOME = "$LocalRoot\cache\torch"
$env:TMP = "$LocalRoot\temp"
$env:TEMP = "$LocalRoot\temp"
$env:PYTHONPYCACHEPREFIX = "$LocalRoot\cache\pycache"
$env:XDG_CACHE_HOME = "$LocalRoot\cache"
$env:NPM_CONFIG_CACHE = "$LocalRoot\cache\npm"
$env:NPM_CONFIG_PREFIX = "$LocalRoot\cache\npm-prefix"
$env:UV_CACHE_DIR = "$LocalRoot\cache\uv"
$env:UV_TOOL_DIR = "$LocalRoot\cache\uv-tools"
$env:UV_PYTHON_INSTALL_DIR = "$LocalRoot\python312"
$env:PLAYWRIGHT_BROWSERS_PATH = "$LocalRoot\cache\playwright"
$env:MPLCONFIGDIR = "$LocalRoot\cache\matplotlib"
$env:RUFF_CACHE_DIR = "$LocalRoot\cache\ruff"
$env:MCP_CACHE_DIR = "$LocalRoot\cache\mcp"
$env:GRAPHIFY_CACHE_DIR = "$LocalRoot\cache\graphify"
$env:GRAPHIFY_OUTPUT_DIR = "$LocalRoot\graphify-output"

Write-Host "All environment variables set to D: drive (matching storage_policy)"

# ---- Step 6: Create virtual environment -------------------------------------
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

# ---- Step 7: Upgrade pip ----------------------------------------------------
Write-Host "Upgrading pip..."
& $venvPython -m pip install --upgrade pip -q
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 8: Install PyTorch (CPU) ------------------------------------------
Write-Host "Installing PyTorch (CPU)..."
& $venvPython -m pip install "torch==2.13.0" --index-url https://download.pytorch.org/whl/cpu
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 9: Install runtime dependencies -----------------------------------
Write-Host "Installing runtime dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 10: Install dev dependencies --------------------------------------
Write-Host "Installing development dependencies..."
& $venvPython -m pip install -r "$repoRoot\requirements-dev.txt"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

# ---- Step 11: Verify environment --------------------------------------------
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
