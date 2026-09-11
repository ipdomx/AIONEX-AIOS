# Phase 36N receipt — FR-03C5 Realtime public gateway

A live acceptance gap was found after the FR-03C dependency rollout: the distributed realtime endpoint was healthy inside Backend but blocked by the public Nginx allowlist. The candidate adds only two explicit public realtime routes (`status`, authenticated WebSocket `connect`) and blocks the legacy unauthenticated `/ws/` public proxy.

The token-bearing WebSocket route disables Nginx access/error logging, preserves the public auth-channel boundary, forwards Upgrade/Connection, disables buffering, and uses bounded connection limits/timeouts. Candidate Nginx syntax and focused public/private gateway tests pass. Deployment remains gated by protected PR checks and a later Nginx-only live acceptance.
