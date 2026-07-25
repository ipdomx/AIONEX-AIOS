from __future__ import annotations
from dataclasses import dataclass

@dataclass(frozen=True)
class DiscoveryCandidate:
    service_id: str
    official_docs: str
    value_summary: str
    security_notes: tuple[str,...]
    license_notes: tuple[str,...]

class FutureServiceDiscovery:
    """Stores researched candidates; it never installs or enables them automatically."""
    def __init__(self) -> None:
        self._candidates: dict[str, DiscoveryCandidate] = {}

    def submit(self, candidate: DiscoveryCandidate) -> None:
        if not candidate.official_docs.startswith(('https://','http://')):
            raise ValueError('official documentation URL required')
        self._candidates[candidate.service_id]=candidate

    def candidates(self) -> tuple[DiscoveryCandidate,...]:
        return tuple(self._candidates.values())
