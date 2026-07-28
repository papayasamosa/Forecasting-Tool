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
