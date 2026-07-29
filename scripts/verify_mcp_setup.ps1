<#
.SYNOPSIS
    Verify local MCP (Model Context Protocol) developer-tooling setup for this repository.
.DESCRIPTION
    Checks structural preconditions for the MCP servers documented in
    docs/development/mcp_setup.md (GitHub, Context7, Playwright, Hugging Face):
    D-drive layout, Node/Docker availability, D-drive-scoped env vars, JSON
    validity of committed templates, .gitignore coverage for local MCP secret
    and state files, absence of obvious secret literals in tracked MCP files,
    and absence of MCP packages in requirements.txt.

    This script never reads or prints secret values. It cannot verify live
    OAuth sessions or authenticated server connectivity -- those must be
    confirmed interactively inside your MCP client (e.g. `/mcp` in Claude Code).
.PARAMETER LocalRoot
    Root directory for local MCP tooling/caches. Default: D:\Forecasting-Tool-Local
#>

param(
    [string]$LocalRoot = "D:\Forecasting-Tool-Local"
)

$repoRoot = Split-Path -Parent $PSScriptRoot
$results = @()

function Add-Result {
    param([string]$Check, [string]$Status, [string]$Detail = "")
    $script:results += [pscustomobject]@{ Check = $Check; Status = $Status; Detail = $Detail }
}

# ---- D: drive and required directories ---------------------------------------
$driveRoot = [System.IO.Path]::GetPathRoot($LocalRoot)
if (Test-Path $driveRoot) {
    Add-Result "D-drive present ($driveRoot)" "PASS"
}
else {
    Add-Result "D-drive present ($driveRoot)" "FAIL" "Do not install local MCP tooling until this drive exists."
}

$requiredDirs = @(
    "cache\npm", "cache\npx", "cache\playwright", "cache\mcp",
    "mcp", "mcp\logs", "mcp\state", "temp"
)
foreach ($rel in $requiredDirs) {
    $full = Join-Path $LocalRoot $rel
    if (Test-Path $full) {
        Add-Result "Directory exists: $rel" "PASS"
    }
    else {
        Add-Result "Directory exists: $rel" "FAIL" "Expected at $full"
    }
}

# ---- Node.js (required for Playwright MCP, Context7 local fallback) ----------
$node = Get-Command node -ErrorAction SilentlyContinue
if ($node) {
    $nodeVersion = (& node --version) -replace '^v', ''
    $major = [int]($nodeVersion -split '\.')[0]
    if ($major -ge 18) {
        Add-Result "Node.js >= 18" "PASS" "Found v$nodeVersion"
    }
    else {
        Add-Result "Node.js >= 18" "FAIL" "Found v$nodeVersion, need 18+"
    }
}
else {
    Add-Result "Node.js >= 18" "WARN" "node not found on PATH; required only if using Playwright MCP or local Context7 MCP"
}

# ---- Docker (only required for the local GitHub MCP Docker fallback) ---------
$docker = Get-Command docker -ErrorAction SilentlyContinue
if ($docker) {
    Add-Result "Docker available" "PASS" "Only needed for the local GitHub MCP fallback; remote HTTP + OAuth is preferred"
}
else {
    Add-Result "Docker available" "WARN" "Not found; use the remote HTTP GitHub MCP server instead of the Docker fallback"
}

# ---- D-drive-scoped environment variables (session-scoped, informational) ----
if ($env:npm_config_cache) {
    if ($env:npm_config_cache -like "$LocalRoot*") {
        Add-Result "npm_config_cache points to D:" "PASS" $env:npm_config_cache
    }
    else {
        Add-Result "npm_config_cache points to D:" "FAIL" "Currently: $env:npm_config_cache"
    }
}
else {
    Add-Result "npm_config_cache points to D:" "WARN" "Not set in this session; set it before installing/running Node-based MCP servers"
}

if ($env:PLAYWRIGHT_BROWSERS_PATH) {
    if ($env:PLAYWRIGHT_BROWSERS_PATH -like "$LocalRoot*") {
        Add-Result "PLAYWRIGHT_BROWSERS_PATH points to D:" "PASS" $env:PLAYWRIGHT_BROWSERS_PATH
    }
    else {
        Add-Result "PLAYWRIGHT_BROWSERS_PATH points to D:" "FAIL" "Currently: $env:PLAYWRIGHT_BROWSERS_PATH"
    }
}
else {
    Add-Result "PLAYWRIGHT_BROWSERS_PATH points to D:" "WARN" "Not set in this session; set it before running Playwright MCP"
}

# ---- Committed template JSON validity ------------------------------------------
$exampleConfig = Join-Path $repoRoot "tools\mcp\mcp.example.json"
if (Test-Path $exampleConfig) {
    try {
        Get-Content $exampleConfig -Raw | ConvertFrom-Json | Out-Null
        Add-Result "tools/mcp/mcp.example.json parses as JSON" "PASS"
    }
    catch {
        Add-Result "tools/mcp/mcp.example.json parses as JSON" "FAIL" $_.Exception.Message
    }
}
else {
    Add-Result "tools/mcp/mcp.example.json parses as JSON" "FAIL" "File not found"
}

$versionsConfig = Join-Path $repoRoot "tools\mcp\mcp-versions.json"
if (Test-Path $versionsConfig) {
    try {
        Get-Content $versionsConfig -Raw | ConvertFrom-Json | Out-Null
        Add-Result "tools/mcp/mcp-versions.json parses as JSON" "PASS"
    }
    catch {
        Add-Result "tools/mcp/mcp-versions.json parses as JSON" "FAIL" $_.Exception.Message
    }
}
else {
    Add-Result "tools/mcp/mcp-versions.json parses as JSON" "FAIL" "File not found"
}

# ---- .gitignore coverage for local MCP secret/state files --------------------
$gitignorePath = Join-Path $repoRoot ".gitignore"
$requiredPatterns = @(
    ".env.mcp", ".mcp.local.json", ".mcp-auth/", ".mcp-state/", ".mcp-logs/", ".playwright-mcp/",
    ".mcp.json"
)
if (Test-Path $gitignorePath) {
    $gitignoreContent = Get-Content $gitignorePath -Raw
    $missing = @()
    foreach ($pattern in $requiredPatterns) {
        if ($gitignoreContent -notmatch [regex]::Escape($pattern)) {
            $missing += $pattern
        }
    }
    if ($missing.Count -eq 0) {
        Add-Result ".gitignore covers local MCP secret/state patterns" "PASS"
    }
    else {
        Add-Result ".gitignore covers local MCP secret/state patterns" "FAIL" "Missing: $($missing -join ', ')"
    }
}
else {
    Add-Result ".gitignore covers local MCP secret/state patterns" "FAIL" ".gitignore not found"
}

# If any local (untracked) MCP config files actually exist, confirm git ignores them.
Push-Location $repoRoot
try {
    $localCandidates = @(".env.mcp", ".mcp.local.json", ".mcp.local.toml")
    foreach ($candidate in $localCandidates) {
        if (Test-Path (Join-Path $repoRoot $candidate)) {
            git check-ignore -q -- $candidate 2>$null
            if ($LASTEXITCODE -eq 0) {
                Add-Result "Local file '$candidate' is git-ignored" "PASS"
            }
            else {
                Add-Result "Local file '$candidate' is git-ignored" "FAIL" "Exists locally but is NOT ignored -- do not commit it"
            }
        }
    }
}
finally {
    Pop-Location
}

# ---- Stricter D-drive LocalRoot enforcement (WP6) ----------------------------
$resolvedRoot = [System.IO.Path]::GetFullPath($LocalRoot)
$driveLetter = [System.IO.Path]::GetPathRoot($resolvedRoot).TrimEnd('\')
if ($driveLetter -ne 'D:') {
    Add-Result "LocalRoot drive is D:" "FAIL" "LocalRoot '$resolvedRoot' is on drive '$driveLetter'. Requirement: D:\Forecasting-Tool-Local"
}
else {
    $expectedPrefix = 'D:\Forecasting-Tool-Local'
    if ($resolvedRoot -eq $expectedPrefix -or $resolvedRoot -like "$expectedPrefix\*") {
        Add-Result "LocalRoot under D:\Forecasting-Tool-Local" "PASS" $resolvedRoot
    }
    else {
        Add-Result "LocalRoot under D:\Forecasting-Tool-Local" "FAIL" "LocalRoot '$resolvedRoot' is not under $expectedPrefix"
    }
}

# ---- Root .mcp.json safety policy ---------------------------------------------
# Policy A: .mcp.json must be git-ignored. Only the example template in
# tools/mcp/ should be tracked. This prevents accidental credential commits.
$rootMcpJson = Join-Path $repoRoot ".mcp.json"
if (Test-Path $rootMcpJson) {
    Push-Location $repoRoot
    try {
        git check-ignore -q -- ".mcp.json" 2>$null
        if ($LASTEXITCODE -eq 0) {
            Add-Result "Root .mcp.json is git-ignored" "PASS"
        }
        else {
            Add-Result "Root .mcp.json is git-ignored" "FAIL" ".mcp.json exists at repo root but is NOT ignored. Move credentials to a git-ignored file or user-scoped config."
        }
    }
    finally {
        Pop-Location
    }
}
else {
    Add-Result "Root .mcp.json is absent (safe)" "PASS" "No .mcp.json at repo root — only example template in tools/mcp/"
}

# ---- No obvious secret literals in tracked MCP files --------------------------
# Flags likely token/key literals by pattern; never prints the matched value.
# Uses `git ls-files` to discover tracked MCP-related files dynamically rather
# than a hardcoded list, so new MCP files cannot bypass the scan silently.
$secretPatterns = @(
    'gh[pousr]_[A-Za-z0-9]{20,}',
    'github_pat_[A-Za-z0-9_]{20,}',
    'hf_[A-Za-z0-9]{20,}',
    'sk-[A-Za-z0-9]{20,}',
    '"[A-Za-z0-9+/]{40,}={0,2}"'
)
$mcpFileExtensions = @('.json', '.md', '.toml', '.yaml', '.yml', '.env.example', '.ps1')
$trackedMcpFiles = @()
Push-Location $repoRoot
try {
    $allTracked = git ls-files 2>$null
    foreach ($f in $allTracked) {
        $ext = [System.IO.Path]::GetExtension($f).ToLower()
        $dirName = [System.IO.Path]::GetDirectoryName($f)
        if ($mcpFileExtensions -contains $ext -and ($f -like '*mcp*' -or $f -like '*context7*' -or $f -like '*playwright*' -or $f -like '*huggingface*')) {
            $trackedMcpFiles += (Join-Path $repoRoot $f)
        }
    }
    # Also add the root .mcp.json if it exists and is tracked (shouldn't be, but check anyway)
    if (Test-Path $rootMcpJson) {
        $ignored = (& git check-ignore -q ".mcp.json" 2>$null; $LASTEXITCODE -eq 0)
        if (-not $ignored) {
            $trackedMcpFiles += $rootMcpJson
        }
    }
}
finally {
    Pop-Location
}
$secretHits = @()
foreach ($file in $trackedMcpFiles) {
    if (-not (Test-Path $file)) { continue }
    $lineNum = 0
    foreach ($line in Get-Content $file) {
        $lineNum++
        foreach ($pattern in $secretPatterns) {
            if ($line -match $pattern) {
                $secretHits += "$($file | Split-Path -Leaf):$lineNum"
            }
        }
    }
}
if ($secretHits.Count -eq 0) {
    Add-Result "No obvious secret literals in tracked MCP files" "PASS"
}
else {
    Add-Result "No obvious secret literals in tracked MCP files" "FAIL" "Suspicious pattern at: $($secretHits -join ', ') (value not printed)"
}

# ---- requirements.txt has no MCP packages --------------------------------------
$requirementsPath = Join-Path $repoRoot "requirements.txt"
$mcpPackageNames = @('mcp-server', '@playwright/mcp', 'playwright-mcp', 'context7-mcp', 'github-mcp', 'modelcontextprotocol')
if (Test-Path $requirementsPath) {
    $reqContent = Get-Content $requirementsPath -Raw
    $found = @()
    foreach ($name in $mcpPackageNames) {
        if ($reqContent -match [regex]::Escape($name)) {
            $found += $name
        }
    }
    if ($found.Count -eq 0) {
        Add-Result "requirements.txt has no MCP packages" "PASS"
    }
    else {
        Add-Result "requirements.txt has no MCP packages" "FAIL" "Found reference(s): $($found -join ', ')"
    }
}
else {
    Add-Result "requirements.txt has no MCP packages" "WARN" "requirements.txt not found"
}

# ---- Report ---------------------------------------------------------------------
Write-Output ""
Write-Output "MCP setup verification -- $repoRoot"
Write-Output "=================================================="
$results | Format-Table -AutoSize | Out-String | Write-Output

$failCount = @($results | Where-Object { $_.Status -eq "FAIL" }).Count
$warnCount = @($results | Where-Object { $_.Status -eq "WARN" }).Count

Write-Output "Summary: $($results.Count) checks, $failCount FAIL, $warnCount WARN"
Write-Output ""
Write-Output "Note: this script cannot verify live OAuth sessions or authenticated"
Write-Output "server connectivity for GitHub, Context7, or Hugging Face MCP. Confirm"
Write-Output "those interactively inside your MCP client, then record verified"
Write-Output "versions in tools/mcp/mcp-versions.json."

if ($failCount -gt 0) {
    exit 1
}
else {
    exit 0
}
