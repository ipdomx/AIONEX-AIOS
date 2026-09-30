#!/usr/bin/env python3
"""Render an inert C5E boot dependency proposal, never install or activate it.

Prepared commit 13b76558 ordered encrypted swap after local-fs.target while
/tmp tmpfs depends on swap.target. That enables a dependency cycle. Require
specific backing/code mounts instead. This graph proposal does not fix the
unmerged activation operator's crash journal or rollback; those block deployment.
"""

from __future__ import annotations

import json

SWAP_UNIT = """[Unit]
Description=AIONEX FR-06C5 random-key encrypted swap (pending activation acceptance)
DefaultDependencies=no
RequiresMountsFor=/usr/bin/python3 /opt/AIOS/scripts/security /var/lib/aionex/fr06-vaults /var/lib/aionex/fr06c5-memory-controls
After=systemd-remount-fs.service
Before=swap.target umount.target
Conflicts=swap.img.swap umount.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/bin/false
ExecStop=/usr/bin/false
TimeoutStartSec=120
TimeoutStopSec=120

[Install]
WantedBy=swap.target
"""

TMP_UNIT = """[Unit]
Description=AIONEX FR-06C5 volatile /tmp (pending activation acceptance)
Requires=aionex-fr06c5-encrypted-swap.service
After=aionex-fr06c5-encrypted-swap.service swap.target
Before=local-fs.target

[Mount]
What=tmpfs
Where=/tmp
Type=tmpfs
Options=mode=1777,nodev,nosuid,size=8G

[Install]
WantedBy=local-fs.target
"""


class BootGraphRejected(RuntimeError):
    """A zero verifier exit status alone does not prove an intact boot graph."""


def accept_offline_verification(
    returncode: int, stdout: str, stderr: str
) -> dict[str, object]:
    """Fail on any diagnostic, including jobs dropped to break an ordering cycle.

    systemd-analyze may return zero after removing a WantedBy job from a cyclic
    transaction. Only a silent successful isolated verification is accepted.
    This function does not claim a host boot or execute the verifier itself.
    """
    if (
        type(returncode) is not int
        or returncode != 0
        or stdout.strip()
        or stderr.strip()
    ):
        raise BootGraphRejected(
            "enabled graph verification incomplete or diagnostic-bearing"
        )
    return {
        "offline_graph_accepted": True,
        "host_boot_verified": False,
        "activation_authorized": False,
    }


def proposal() -> dict[str, object]:
    return {
        "schema_version": 1,
        "subpart": "FR-06C5E1",
        "prepared_source_commit": "13b76558f585f432acc831b6ad0448ee5909b5bd",
        "units": {
            "aionex-fr06c5-encrypted-swap.service": SWAP_UNIT,
            "tmp.mount": TMP_UNIT,
        },
        "enabled_links": {
            "swap.target.wants/aionex-fr06c5-encrypted-swap.service": "../aionex-fr06c5-encrypted-swap.service",
            "local-fs.target.wants/tmp.mount": "../tmp.mount",
        },
        "activation_authorized": False,
        "operator_integrated_in_main": True,
        "real_host_dependency_graph_verified": False,
        "remaining_prerequisites": [
            "Accepted host-state cutover, operation-bound writer quiescence and pinned underlay recheck",
            "Actual mapper/backing encryption attestation and safe memory reserve",
            "Full intended host enabled dependency graph and independently accepted boot/recovery",
        ],
        "production_changed": False,
    }


if __name__ == "__main__":
    print(json.dumps(proposal(), sort_keys=True))
