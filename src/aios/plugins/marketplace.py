from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ListingState(str, Enum):
    DRAFT = "draft"
    PUBLISHED = "published"
    SUSPENDED = "suspended"
    RETIRED = "retired"


@dataclass(slots=True)
class PluginListing:
    plugin_id: str
    owner_id: str
    name: str
    summary: str
    version: str
    price_cents: int = 0
    currency: str = "EUR"
    state: ListingState = ListingState.DRAFT
    tags: tuple[str, ...] = field(default_factory=tuple)


class PluginMarketplace:
    def __init__(self) -> None:
        self._listings: dict[str, PluginListing] = {}

    def submit(self, listing: PluginListing) -> PluginListing:
        if listing.plugin_id in self._listings:
            raise ValueError(f"duplicate listing: {listing.plugin_id}")
        if listing.price_cents < 0:
            raise ValueError("price must be non-negative")
        self._listings[listing.plugin_id] = listing
        return listing

    def publish(self, plugin_id: str, owner_id: str) -> PluginListing:
        listing = self._require_owner(plugin_id, owner_id)
        if listing.state is ListingState.RETIRED:
            raise RuntimeError("retired listings cannot be republished")
        listing.state = ListingState.PUBLISHED
        return listing

    def suspend(self, plugin_id: str, owner_id: str) -> PluginListing:
        listing = self._require_owner(plugin_id, owner_id)
        listing.state = ListingState.SUSPENDED
        return listing

    def retire(self, plugin_id: str, owner_id: str) -> PluginListing:
        listing = self._require_owner(plugin_id, owner_id)
        listing.state = ListingState.RETIRED
        return listing

    def search(self, query: str = "") -> list[PluginListing]:
        needle = query.casefold().strip()
        result = [item for item in self._listings.values() if item.state is ListingState.PUBLISHED]
        if needle:
            result = [
                item
                for item in result
                if needle in item.name.casefold()
                or needle in item.summary.casefold()
                or any(needle in tag.casefold() for tag in item.tags)
            ]
        return sorted(result, key=lambda item: (item.name.casefold(), item.plugin_id))

    def _require_owner(self, plugin_id: str, owner_id: str) -> PluginListing:
        listing = self._listings[plugin_id]
        if listing.owner_id != owner_id:
            raise PermissionError("listing is not owned by this owner")
        return listing
