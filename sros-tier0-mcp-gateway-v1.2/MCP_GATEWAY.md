# SROS Tier-0 v1.2 — MCP Gateway

Endpoint: `/mcp`
Authentication: `Authorization: Bearer <SROS_API_TOKEN>`

Implemented MCP methods:
- `initialize`
- `ping`
- `tools/list`
- `tools/call`
- `notifications/*` accepted with 202

Exposed tool:
- `quick_check(q)`

The tool calls the same in-memory Tier-0 `lookup()` function used by `/quick-check`.
No raw-file fallback, Library search, SQLite/history scan, or query-time business calculations are added.
