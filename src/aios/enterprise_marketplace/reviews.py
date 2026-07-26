from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


@dataclass(frozen=True)
class MarketplaceReview:
    review_id: str
    item_id: str
    reviewer_id: str
    rating: int
    comment: str = ""
    approved: bool = False
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ReviewRegistry:
    def __init__(self) -> None:
        self._reviews: dict[str, MarketplaceReview] = {}

    def add(self, review: MarketplaceReview) -> MarketplaceReview:
        if not review.review_id.strip() or not review.item_id.strip() or not review.reviewer_id.strip():
            raise ValueError("review_id, item_id, and reviewer_id are required")
        if not 1 <= review.rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        if review.review_id in self._reviews:
            raise ValueError(f"duplicate review_id: {review.review_id}")
        self._reviews[review.review_id] = review
        return review

    def list_for_item(self, item_id: str, approved_only: bool = True) -> list[MarketplaceReview]:
        items = [review for review in self._reviews.values() if review.item_id == item_id]
        if approved_only:
            items = [review for review in items if review.approved]
        return items

    def average_rating(self, item_id: str) -> float:
        reviews = self.list_for_item(item_id)
        if not reviews:
            return 0.0
        return sum(review.rating for review in reviews) / len(reviews)
