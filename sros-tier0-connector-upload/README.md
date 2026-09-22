# SROS Tier-0 Quick Check Service

Strict one-call Seafood Tier-0 serving layer for Store #1032.

- `GET /health` — public health/readiness summary.
- `GET /quick-check?q=<query>` — exact Tier-0 lookup; requires `Authorization: Bearer <SROS_API_TOKEN>`.
- `GET /ready` — current READY artifact; requires auth.

No Library/Drive/raw/SQLite fallback and no on-demand business calculations.
