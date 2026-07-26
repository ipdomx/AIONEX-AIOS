from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum


class MarketplaceItemType(str, Enum):
    APPLICATION = "application"
    AGENT = "agent"
    CONNECTOR = "connector"
    WORKFLOW = "workflow"
    MODEL = "model"
    DATASET = "dataset"


class PublicationState(str, Enum):
    DRAFT = "draft"
    PENDING_REVIEW = "pending_review"
    PUBLISHED = "published"
    SUSPENDED = "suspended"
    ARCHIVED = "archived"


@dataclass
class MarketplaceItem:
    item_id: str
    name: str
    item_type: MarketplaceItemType
    publisher_id: str
    version: str
    description: str = ""
    state: PublicationState = PublicationState.DRAFT
    categories: set[str] = field(default_factory=set)
    capabilities: set[str] = field(default_factory=set)
    price: float = 0.0
    currency: str = "EUR"
    metadata: dict[str, str] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def transition(self, state: PublicationState) -> None:
        allowed = {
            PublicationState.DRAFT: {PublicationState.PENDING_REVIEW, PublicationState.ARCHIVED},
            PublicationState.PENDING_REVIEW: {PublicationState.PUBLISHED, PublicationState.DRAFT, PublicationState.SUSPENDED},
            PublicationState.PUBLISHED: {PublicationState.SUSPENDED, PublicationState.ARCHIVED},
            PublicationState.SUSPENDED: {PublicationState.PUBLISHED, PublicationState.ARCHIVED},
            PublicationState.ARCHIVED: set(),
        }
        if state not in allowed[self.state]:
            raise ValueError(f"invalid publication transition: {self.state.value} -> {state.value}")
        self.state = state
        self.updated_at = datetime.now(timezone.utc)


class MarketplaceCatalog:
    def __init__(self) -> None:
        self._items: dict[str, MarketplaceItem] = {}

    def register(self, item: MarketplaceItem) -> MarketplaceItem:
        if not item.item_id.strip() or not item.name.strip() or not item.publisher_id.strip():
            raise ValueError("item_id, name, and publisher_id are required")
        if not item.version.strip():
            raise ValueError("version is required")
        if item.price < 0:
            raise ValueError("price cannot be negative")
        if item.item_id in self._items:
            raise ValueError(f"duplicate item_id: {item.item_id}")
        self._items[item.item_id] = item
        return item

    def get(self, item_id: str) -> MarketplaceItem:
        try:
            return self._items[item_id]
        except KeyError as exc:
            raise LookupError(f"marketplace item not found: {item_id}") from exc

    def search(
        self,
        query: str | None = None,
        item_type: MarketplaceItemType | None = None,
        published_only: bool = True,
    ) -> list[MarketplaceItem]:
        items = list(self._items.values())
        if published_only:
            items = [item for item in items if item.state is PublicationState.PUBLISHED]
        if item_type is not None:
            items = [item for item in items if item.item_type is item_type]
        if query:
            needle = query.casefold()
            items = [
                item for item in items
                if needle in item.name.casefold()
                or needle in item.description.casefold()
                or any(needle in category.casefold() for category in item.categories)
            ]
        return sorted(items, key=lambda item: (item.name.casefold(), item.version))

    def list_for_publisher(self, publisher_id: str) -> list[MarketplaceItem]:
        return [item for item in self._items.values() if item.publisher_id == publisher_id]
