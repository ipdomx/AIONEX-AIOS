from __future__ import annotations
import asyncio, time
from dataclasses import dataclass
from enum import Enum
from typing import Dict, Optional

class LeadershipState(str, Enum):
    FOLLOWER="FOLLOWER"; CANDIDATE="CANDIDATE"; LEADER="LEADER"

@dataclass
class Candidate:
    node_id: str
    priority: int
    last_seen: float

class LeaderElection:
    def __init__(self, lease_seconds: float = 15.0):
        self.lease_seconds = lease_seconds
        self.candidates: Dict[str, Candidate] = {}
        self.leader_id: Optional[str] = None
        self.leader_expires_at: float = 0.0
        self.lock = asyncio.Lock()

    async def campaign(self, node_id: str, priority: int = 100) -> str:
        async with self.lock:
            self.candidates[node_id] = Candidate(node_id, priority, time.time())
            await self._elect_locked()
            return self.leader_id or node_id

    async def heartbeat(self, node_id: str) -> bool:
        async with self.lock:
            candidate = self.candidates.get(node_id)
            if candidate:
                candidate.last_seen = time.time()
            if self.leader_id == node_id:
                self.leader_expires_at = time.time() + self.lease_seconds
                return True
            await self._elect_locked()
            return self.leader_id == node_id

    async def resign(self, node_id: str) -> None:
        async with self.lock:
            self.candidates.pop(node_id, None)
            if self.leader_id == node_id:
                self.leader_id = None
                self.leader_expires_at = 0.0
            await self._elect_locked()

    async def _elect_locked(self) -> None:
        now = time.time()
        active = [c for c in self.candidates.values() if now-c.last_seen <= self.lease_seconds]
        if self.leader_id and self.leader_expires_at > now and any(c.node_id == self.leader_id for c in active):
            return
        if not active:
            self.leader_id = None
            self.leader_expires_at = 0.0
            return
        winner = min(active, key=lambda c: (c.priority, c.node_id))
        self.leader_id = winner.node_id
        self.leader_expires_at = now + self.lease_seconds

    async def state(self, node_id: str) -> LeadershipState:
        async with self.lock:
            if self.leader_id == node_id and self.leader_expires_at > time.time():
                return LeadershipState.LEADER
            return LeadershipState.FOLLOWER if node_id in self.candidates else LeadershipState.CANDIDATE

    async def summary(self) -> dict:
        async with self.lock:
            return {"leader_id": self.leader_id, "leader_expires_at": self.leader_expires_at, "candidates": sorted(self.candidates)}
