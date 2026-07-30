<#
.SYNOPSIS
    Activate the D: drive local environment for the Chronos-2 Forecasting Tool.
.DESCRIPTION
    Sets all required D: drive cache and environment variables, then activates
    the virtual environment. Run this before any smoke-test, benchmark, or
    Streamlit command to ensure all caches use D: drive.
.PARAMETER LocalRoot
    Root directory for all local artefacts. Default: D:\Forecasting-Tool-Local
#>

param(
    [string]$LocalRoot = "D:\Forecasting-Tool-Local"
)

$ErrorActionPreference = "Stop"

# ---- WP12: Validate D-drive policy before changing environment -----------
$resolvedRoot = [System.IO.Path]::GetFullPath($LocalRoot)
$driveLetter = [System.IO.Path]::GetPathRoot($resolvedRoot).TrimEnd('\')
if ($driveLetter -ne 'D:') {
    Write-Error "LocalRoot must be on drive D:. Got '$driveLetter' from '$LocalRoot'. See docs/development/storage_policy.md"
    exit 1
}
if ($resolvedRoot -ne 'D:\Forecasting-Tool-Local' -and $resolvedRoot -notlike 'D:\Forecasting-Tool-Local\*') {
    Write-Error "LocalRoot must be under D:\Forecasting-Tool-Local. Got '$resolvedRoot'. See docs/development/storage_policy.md"
    exit 1
}

# ---- Set D: drive environment variables ------------------------------------
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

Write-Host "✅ Environment variables set to D: drive:"
Write-Host "   FORECASTING_LOCAL_ROOT = $LocalRoot"
Write-Host "   PIP_CACHE_DIR          = $env:PIP_CACHE_DIR"
Write-Host "   HF_HOME                = $env:HF_HOME"
Write-Host "   HF_HUB_CACHE           = $env:HF_HUB_CACHE"
Write-Host "   HF_XET_CACHE           = $env:HF_XET_CACHE"
Write-Host "   TRANSFORMERS_CACHE     = $env:TRANSFORMERS_CACHE"
Write-Host "   TORCH_HOME             = $env:TORCH_HOME"
Write-Host "   TMP / TEMP             = $env:TMP"

# ---- Activate virtual environment ------------------------------------------
$venvPath = "$LocalRoot\venv\Scripts\Activate.ps1"
if (Test-Path $venvPath) {
    . $venvPath
    Write-Host "✅ Virtual environment activated: $((Get-Command python).Source)"
}
else {
    Write-Error "Virtual environment not found at $venvPath. Run setup_local_windows.ps1 first."
    exit 1
}

Write-Host ""
Write-Host "Available commands:"
Write-Host "   Run tests : python -m pytest tests -v"
Write-Host "   Smoke test: python scripts/chronos2_smoke_test.py"
Write-Host "   Benchmark : python scripts/run_stage0_benchmark.py"
Write-Host "   Streamlit : python -m streamlit run app.py"
