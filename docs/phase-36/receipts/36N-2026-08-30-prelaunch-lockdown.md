# Phase 36N — Pre-launch lockdown — 2026-08-30

## Owner intent

Keep the project fully prepared and hardened while preventing persistent provider mutation/spend until the explicit full-launch authorization.

## Fail-closed production state

Both canonical Production Compose files keep all persistent paid/external media execution workers disabled:

- `AUDIO_SPEECH_LIVE_ENABLED=false`
- `AUDIO_TRANSCRIPT_LIVE_ENABLED=false`
- `AUDIO_DUBBING_LIVE_ENABLED=false`
- `AUDIO_MUSIC_LIVE_ENABLED=false`
- `AUDIO_SONG_LIVE_ENABLED=false` for primary and secondary workers
- `VIDEO_EXECUTION_LIVE_ENABLED=false`
- `DESIGN_IMAGE_LIVE_ENABLED=false`
- `DESIGN_IMAGE_DERIVATIVE_ENABLED=false`
- `PROJECT_AI_LIVE_RUNTIME_ENABLED=false`
- `PROJECT_EXECUTION_RUNNER_MODE=legacy`

The secondary RunPod account remains owner-deferred and must not be activated, populated from the primary account, or used before separate owner instructions.

This lockdown does not remove or regress the merged real-runtime integrations. Source, API, UI, provider transports, cost/rights/idempotency controls and hardened container definitions remain deployable and testable. Persistent workers simply stay fail-closed until launch.

## Host/network posture verified before rollout

- Public host listeners are limited to SSH `22`; application origins `8080/8081/8082`, ADB `5556`, ADB server `5037`, DNS and MCP/tunnel listeners are loopback-only.
- Docker forwarding policy is default-drop for the production bridge and explicit external-to-loopback/origin drop rules remain installed.
- ADB `5556` is bound to `127.0.0.1` and also protected by an explicit non-loopback drop rule.
- Fail2ban SSH jail is active and is actively blocking brute-force sources.
- SSH has `MaxAuthTries=3`, X11 forwarding off, agent forwarding off, gateway ports off, tunnels off and TCP forwarding restricted to local. Root/password login remain a deliberate operator-access gate until a tested replacement public-key path exists; they must not be disabled blindly.
- Owner host remains behind Cloudflare Access; public/portal/API routing is through the existing tunnel/origin boundary.

## Security image posture retained

The merged hardening remains intact:

- pinned base-image digests for Node, Redis and Cloudflared;
- hardened non-root Nginx image with read-only filesystem and bounded tmpfs;
- hardened PostgreSQL image and non-root runtime;
- frontend/portal read-only root filesystems, dropped capabilities and bounded tmpfs;
- Cloudflared read-only root filesystem and dropped capabilities;
- security scan/ZAP isolation retained.

## Launch rule

No persistent `*_LIVE_ENABLED` flag, `PROJECT_AI_LIVE_RUNTIME_ENABLED`, secondary RunPod worker, provider write/spend path, or campaign launch gate may be enabled merely because the code is present. Full launch requires an explicit owner authorization plus the applicable credential, legal/rights, quota/credit, budget/stop-loss and provider-readiness gates.

Credential rotation and SSH password/root retirement remain controlled operator migrations because blind mutation can destroy encrypted-data access or lock out server administration. They are not to be simulated or marked complete without a tested replacement path.

## Post-restart recovery note — 2026-08-30

A host UFW enable attempt failed before activation because the running kernel/netfilter environment could not load required `addrtype`, `conntrack` and `mark` matches. No firewall bypass was forced. After a graceful host reboot, recovery verification confirmed `ufw` is inactive, the host INPUT policy is ACCEPT, SSH is active and listening on IPv4/IPv6 port 22, Fail2ban is active, and both AIONEX MCP tunnels are active. The failed UFW path must not be retried until kernel/netfilter compatibility is proven offline.

The reboot also exposed an external object-storage readiness gate: a direct S3 `HeadBucket` preflight for the configured production media bucket returns HTTP 403. Workers that fail only on this object-storage preflight are intentionally stopped while their persistent live-execution flags remain false, preventing restart churn and provider execution. No S3 credential is modified or exposed by this closeout. Storage access must be repaired through a controlled credential/provider migration before those workers are re-enabled.
