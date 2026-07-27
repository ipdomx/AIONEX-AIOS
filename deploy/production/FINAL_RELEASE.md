# AIONEX AIOS Final Production Release

Production endpoints:

- Web: `https://ai.vip-e.net`
- API: `https://api.ai.vip-e.net`

## Final deployment sequence

1. Copy `.env.production.example` to `.env.production` and provide production secrets.
2. Run `bash deploy/production/final-release-check.sh`.
3. Run the production deployment script.
4. Run production health checks.
5. Verify backup and restore automation.

The repository now contains the production runtime, deployment stack, TLS reverse proxy, configuration validation, health checks, backup, restore, and final release gate required for transfer to the production server.
