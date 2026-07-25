#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
mkdir -p backups
tar -czf "backups/aios-$stamp.tar.gz" AFS config data src pyproject.toml VERSION
echo "backups/aios-$stamp.tar.gz"
