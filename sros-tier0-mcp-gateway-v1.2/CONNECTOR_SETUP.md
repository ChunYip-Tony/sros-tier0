# SROS Tier-0 Connector Package

This package preserves the existing Railway SROS Tier-0 service and adds an OpenAPI contract for a future ChatGPT/custom connector integration.

## Existing production API
- GET /health — public
- GET /ready — Bearer token required
- GET /quick-check?q=<exact query> — Bearer token required

## Security
Keep `SROS_API_TOKEN` only in Railway Variables. Never commit the token to GitHub.

## Deployment
Upload the contents of this folder into the existing `sros-tier0-github-upload/` directory in the GitHub repository, replacing same-named files when prompted. Railway should redeploy from that root directory.

## Important
`openapi.json` documents the REST interface. It does not by itself install a ChatGPT connector. Connector registration still requires a supported ChatGPT app/MCP registration path.
