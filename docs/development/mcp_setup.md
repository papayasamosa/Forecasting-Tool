# MCP Development Support Setup

## What this is

This document configures **Model Context Protocol (MCP)** servers as *developer
tooling* for coding assistants working on this repository. MCP servers give a
coding LLM standardized access to external context — repository state,
library documentation, a live browser, and Hugging Face Hub metadata — while
it edits code.

MCP servers are **not** part of the Streamlit application. They are not
Python dependencies, they are not deployed to Streamlit Community Cloud, and
they must never be required to run `app.py`. They exist purely to make the
coding assistant more effective while developing this repository.

## Detected coding-agent host

This setup was authored and verified against **Claude Code running as a
VS Code native extension** (the active host for this repository as of this
writing). Claude Code's MCP support:

- Supports remote HTTP MCP servers (`"type": "http"` / `"url"`) and local
  `stdio` servers (`"command"` / `"args"`).
- Supports OAuth for remote servers that offer it (GitHub, Context7,
  Hugging Face all support OAuth-based remote MCP).
- Supports `${VAR}` environment-variable interpolation inside `.mcp.json`.
- Supports both **project-scoped** configuration (`.mcp.json` at the repo
  root, shared via Git) and **user-scoped** configuration (registered per
  machine via `claude mcp add --scope user`, stored outside the repo).

The templates in [`tools/mcp/`](../../tools/mcp/) use the `mcpServers` schema
Claude Code expects. If you are using a different MCP client (Codex, Cursor,
VS Code + GitHub Copilot, Windsurf, etc.), adapt the template to that
client's documented schema — do not assume the schema is universal. Consult
that client's official MCP documentation for the exact top-level key
(`mcpServers`, `servers`, `mcp`, or a TOML table) and transport syntax.

## Guiding rule: authenticated config never lives in the repo

Only **unauthenticated templates** are committed
(`tools/mcp/mcp.example.json`). Your live, authenticated configuration
(tokens, OAuth session state, generated client config from a provider's
settings page) belongs in a **user-scoped** or **local, git-ignored** file —
see [`.gitignore`](../../.gitignore) for the ignored patterns.

Prefer user-scoped, OAuth-authenticated configuration over project-scoped
files containing secrets, wherever the client supports it.

## D-drive preparation

All local MCP tooling, Node package caches, and browser binaries must live
under `D:\Forecasting-Tool-Local`, matching the project's existing
convention of keeping large caches off `C:` and out of the repository
(see the main [README](../../README.md) local setup section).

Required directories (created once, idempotent):

```powershell
$dirs = @(
  "D:\Forecasting-Tool-Local\cache\npm",
  "D:\Forecasting-Tool-Local\cache\npx",
  "D:\Forecasting-Tool-Local\cache\playwright",
  "D:\Forecasting-Tool-Local\cache\mcp",
  "D:\Forecasting-Tool-Local\mcp",
  "D:\Forecasting-Tool-Local\mcp\logs",
  "D:\Forecasting-Tool-Local\mcp\state",
  "D:\Forecasting-Tool-Local\temp"
)
foreach ($d in $dirs) { New-Item -ItemType Directory -Force -Path $d | Out-Null }
```

Required environment variables before installing or running any local
(`npx`/Node-based) MCP server:

```powershell
$env:npm_config_cache = "D:\Forecasting-Tool-Local\cache\npm"
$env:PLAYWRIGHT_BROWSERS_PATH = "D:\Forecasting-Tool-Local\cache\playwright"
$env:TMP = "D:\Forecasting-Tool-Local\temp"
$env:TEMP = "D:\Forecasting-Tool-Local\temp"
```

Do not install Node packages, browsers, or MCP caches under the repository
or on `C:`. If `D:` is not available on a given machine, do not install
local MCP tooling there — use remote HTTP MCP servers instead, or skip that
integration until `D:` is available.

## Per-server setup

### GitHub MCP

- Prefer the official **remote** GitHub MCP server with OAuth if your
  client supports remote HTTP MCP (Claude Code does).
- If remote/OAuth is unavailable, fall back to the official Docker image
  `ghcr.io/github/github-mcp-server`, started in **read-only** mode
  (`GITHUB_READ_ONLY=1`) with a limited toolset
  (`GITHUB_TOOLSETS=context,repos,pull_requests,actions,issues`).
- If a PAT is required (OAuth unavailable), use a fine-grained token scoped
  only to `papayasamosa/Forecasting-Tool`, with the minimum permissions and
  shortest practical expiry.
- See [`tools/mcp/mcp.example.json`](../../tools/mcp/mcp.example.json) for
  the template.

### Context7 MCP

- Prefer the hosted remote server: `https://mcp.context7.com/mcp`.
- An API key is optional for basic usage; if used, pass it via
  `CONTEXT7_API_KEY` as an environment variable reference, never a literal
  value in a committed file.
- Local alternative: `@upstash/context7-mcp` (stdio, Node-based, respects
  the D-drive npm cache above).

### Playwright MCP

- Official server: `@playwright/mcp`. Requires Node.js 18+ (verified locally
  against Node v24.18.0 / npm 11.16.0 — see verification output for your
  machine).
- Install/run only after setting the D-drive environment variables above,
  so the Chromium binary lands under
  `D:\Forecasting-Tool-Local\cache\playwright`.
- Use a clean, disposable browser context. Never point it at a personal
  browser profile or any authenticated session unrelated to this project
  (email, banking, password manager, cloud consoles).
- Initial setup may use `npx @playwright/mcp@latest`; after verification,
  pin the exact tested version in
  [`tools/mcp/mcp-versions.json`](../../tools/mcp/mcp-versions.json) and in
  the template's `args`.

### Hugging Face MCP

- Use the hosted server generated from
  `https://huggingface.co/settings/mcp` (logged in) — do not hand-write an
  authentication endpoint.
- Enable only Hub search and documentation exploration. Leave Jobs,
  Sandboxes, repository-write, and community Space execution tools
  disabled.
- Do not let MCP setup touch `HF_HOME`, `HF_HUB_CACHE`, `HF_XET_CACHE`, or
  `TRANSFORMERS_CACHE` — those are the application's runtime cache
  variables, already configured per the main README, and must stay
  untouched by developer tooling.

## Client-specific configuration location (Claude Code)

- **Root `.mcp.json` is git-ignored** per the repository's `.gitignore`.
  Do **not** commit this file. Only the example template in
  `tools/mcp/mcp.example.json` is tracked. Copy the relevant server block
  into your own local, git-ignored `.mcp.json` or register it as
  user-scoped.
- User-scoped (preferred for anything authenticated): register via
  `claude mcp add --scope user ...` or through Claude Code's `/mcp` UI,
  which stores credentials outside the repository.

## Authentication methods summary

| Server | Preferred auth | Fallback |
|---|---|---|
| GitHub | OAuth via remote MCP | Fine-grained PAT, repo-scoped, read-only |
| Context7 | None required (optional API key) | `CONTEXT7_API_KEY` env var |
| Playwright | N/A (local browser automation) | N/A |
| Hugging Face | OAuth via hosted MCP settings page | N/A |

## Version pinning

Official installation examples may use `@latest` for first-time setup.
After you have verified a server works, resolve and record the exact
version in [`tools/mcp/mcp-versions.json`](../../tools/mcp/mcp-versions.json)
and replace `@latest` references with the pinned version in your local,
authenticated config. Never guess a version, and never pin a version you
have not actually tested.

## Verification

Run the non-authenticated structural checks:

```powershell
.\scripts\verify_mcp_setup.ps1
```

This script checks D-drive layout, Node/Docker availability, `.gitignore`
coverage, JSON validity of the committed templates, and that no MCP
package has leaked into `requirements.txt`. It does not — and cannot —
verify live OAuth sessions; those must be confirmed interactively inside
your MCP client (e.g. `/mcp` in Claude Code).

## Removal procedure

1. Remove the server entry from your local (git-ignored) MCP client
   configuration, or `claude mcp remove <name>` for user-scoped servers.
2. Revoke any associated OAuth grant or PAT at the provider (GitHub
   Developer Settings, Hugging Face Access Tokens page, etc.).
3. Local caches under `D:\Forecasting-Tool-Local\cache\{npm,npx,playwright,mcp}`
   and `D:\Forecasting-Tool-Local\mcp\{logs,state}` may be deleted freely —
   nothing under the repository depends on them.

## Troubleshooting

- **"D: drive not found"** — do not install local MCP tooling; use remote
  HTTP servers only, or wait until `D:` is available.
- **Playwright browser download fails** — confirm
  `PLAYWRIGHT_BROWSERS_PATH` is set to the D-drive path *before* running
  `npx @playwright/mcp`, and that you have free space on `D:`.
- **GitHub MCP returns permission errors** — expected if a tool outside the
  read-only toolset was requested; this is by design (see
  [`mcp_usage_policy.md`](mcp_usage_policy.md)).
- **Docker not found** — local Docker-based GitHub MCP is unavailable on
  this machine; use the remote HTTP GitHub MCP server instead.
