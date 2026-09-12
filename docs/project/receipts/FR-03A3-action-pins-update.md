# FR-03A3 — GitHub Actions full-SHA pin update

- Scope: update only the pinned SBOM and Trivy actions in Phase34E and Phase34F workflows.
- anchore/sbom-action target SHA: `3ad7283483fc7af8ff2b4ea19663c2d5ca935e26`.
- aquasecurity/trivy-action target SHA: `ed142fd0673e97e23eac54620cfb913e5ce36c25`.
- No tag-based references are introduced. No application runtime, Cloudflare, secrets, or production containers are changed.
- The transition contract merged in PR632 intentionally accepts only the old and target full SHAs until this PR is merged.
