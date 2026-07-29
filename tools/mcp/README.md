# tools/mcp/

Templates and version records for the MCP (Model Context Protocol) servers
used as **developer tooling** on this repository. See
[`docs/development/mcp_setup.md`](../../docs/development/mcp_setup.md) for
full setup instructions and
[`docs/development/mcp_usage_policy.md`](../../docs/development/mcp_usage_policy.md)
for usage rules.

## Files here

- **`mcp.example.json`** — an unauthenticated template showing the
  `mcpServers` shape for GitHub, Context7, Playwright, and Hugging Face
  MCP. It contains no secrets and is safe to commit. It is a template, not
  live configuration — nothing reads this file at runtime.
- **`mcp-versions.json`** — a record of the exact server versions (or
  hosted-service identifiers) that have actually been verified against
  this repository, with the verification date and transport used.

## These are templates, not live configuration

Do not point your MCP client directly at `mcp.example.json` and add
secrets to it. Instead:

1. Copy the relevant server block out of `mcp.example.json` into your own
   **local, git-ignored** configuration (see the `.gitignore` patterns for
   `.env.mcp`, `.mcp.local.json`, `.mcp-auth/`, `.mcp-state/`), or
2. Register the server as **user-scoped** in your MCP client (preferred
   for anything authenticated — e.g. `claude mcp add --scope user ...` in
   Claude Code), which keeps credentials entirely outside the repository.

Fill in `${VAR}`-style placeholders from your own environment or your
client's secret store — never by editing a literal value into a tracked
file.

## Recording verified versions

After you've confirmed a server works end-to-end for a given task:

1. Resolve the exact installed package version (or, for hosted-only
   services like Hugging Face's hosted MCP, note that it's a hosted
   service with no local version to pin).
2. Add/update its entry in `mcp-versions.json` with `version`,
   `verified_at_utc`, `transport`, and `implementation`.
3. If the server is started via a local command (e.g. `npx
   @playwright/mcp@latest`), replace `@latest` with the pinned version in
   your local configuration once verified.

Never guess a version. Never pin a version you have not personally tested
against this repository.
