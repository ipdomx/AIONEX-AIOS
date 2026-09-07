#!/usr/bin/env python3
"""Generate the production Apple App Site Association file from real signing authority."""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

TEAM_ID_RE = re.compile(r"^[A-Z0-9]{10}$")
BUNDLE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{2,127}$")


def build(team_id: str, bundle_id: str) -> dict:
    team_id = team_id.strip().upper()
    bundle_id = bundle_id.strip()
    if not TEAM_ID_RE.fullmatch(team_id):
        raise ValueError("Apple Team ID must be exactly 10 uppercase alphanumeric characters")
    if not BUNDLE_ID_RE.fullmatch(bundle_id):
        raise ValueError("Apple bundle ID is invalid")
    app_id = f"{team_id}.{bundle_id}"
    return {
        "applinks": {
            "details": [
                {
                    "appIDs": [app_id],
                    "components": [
                        {"/": "/*", "comment": "AIONEX universal links"},
                    ],
                }
            ]
        },
        "webcredentials": {"apps": [app_id]},
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--bundle-id", default="net.vipe.aionex")
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    payload = build(args.team_id, args.bundle_id)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"apple_association_written={output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
