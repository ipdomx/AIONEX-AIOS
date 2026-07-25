from __future__ import annotations

import hashlib
import json
import uuid
from pathlib import Path
from typing import Any

from .models import KnowledgeItem, MemoryScope, Provenance
from .storage import HashChainedJsonl


class EnterpriseMemory:
    """Scoped, deduplicated and versioned enterprise memory."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self._stores: dict[str, HashChainedJsonl] = {}

    def _key(self, scope: MemoryScope, owner: str) -> str:
        safe_owner = owner.replace("/", "_").replace("..", "_")
        return f"{scope.value}--{safe_owner}"

    def _store(self, scope: MemoryScope, owner: str) -> HashChainedJsonl:
        key = self._key(scope, owner)
        if key not in self._stores:
            self._stores[key] = HashChainedJsonl(self.root / f"{key}.jsonl")
        return self._stores[key]

    @staticmethod
    def _content_hash(subject: str, content: Any) -> str:
        canonical = json.dumps({"subject": subject, "content": content}, ensure_ascii=False, sort_keys=True, default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def remember(
        self,
        scope: MemoryScope,
        owner: str,
        namespace: str,
        subject: str,
        content: Any,
        *,
        confidence: float,
        provenance: tuple[Provenance, ...],
        tags: tuple[str, ...] = (),
        verified: bool = False,
    ) -> KnowledgeItem:
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not provenance:
            raise ValueError("provenance is required")
        store = self._store(scope, owner)
        fingerprint = self._content_hash(subject, content)
        existing = list(store.payloads())
        for payload in reversed(existing):
            if payload.get("fingerprint") == fingerprint and payload.get("namespace") == namespace:
                return self._deserialize(payload["item"])
        previous = next((payload["item"]["item_id"] for payload in reversed(existing)
                         if payload["item"].get("subject") == subject and payload.get("namespace") == namespace), None)
        item = KnowledgeItem(
            item_id=str(uuid.uuid4()), namespace=namespace, subject=subject, content=content,
            confidence=confidence, provenance=provenance, tags=tags, supersedes=previous, verified=verified,
        )
        store.append({"namespace": namespace, "fingerprint": fingerprint, "item": item.to_dict()})
        return item

    def recall(self, scope: MemoryScope, owner: str, *, namespace: str | None = None,
               subject: str | None = None, latest_only: bool = True) -> list[KnowledgeItem]:
        items = [self._deserialize(payload["item"]) for payload in self._store(scope, owner).payloads()]
        if namespace:
            items = [item for item in items if item.namespace == namespace]
        if subject:
            items = [item for item in items if item.subject == subject]
        if latest_only:
            superseded = {item.supersedes for item in items if item.supersedes}
            items = [item for item in items if item.item_id not in superseded]
        return items

    def verify(self, scope: MemoryScope, owner: str) -> bool:
        return self._store(scope, owner).verify()

    @staticmethod
    def _deserialize(data: dict) -> KnowledgeItem:
        provenance = tuple(Provenance(**item) for item in data["provenance"])
        return KnowledgeItem(**{**data, "provenance": provenance, "tags": tuple(data.get("tags", ()))})
