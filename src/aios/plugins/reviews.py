from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ReviewState(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"


@dataclass(slots=True)
class PluginReview:
    review_id: str
    plugin_id: str
    reviewer_id: str
    rating: int
    comment: str
    state: ReviewState = ReviewState.PENDING


class PluginReviewService:
    def __init__(self) -> None:
        self._reviews: dict[str, PluginReview] = {}

    def submit(self, review: PluginReview) -> PluginReview:
        if review.review_id in self._reviews:
            raise ValueError(f"duplicate review: {review.review_id}")
        if not 1 <= review.rating <= 5:
            raise ValueError("rating must be between 1 and 5")
        self._reviews[review.review_id] = review
        return review

    def moderate(self, review_id: str, *, approved: bool) -> PluginReview:
        review = self._reviews[review_id]
        if review.state is not ReviewState.PENDING:
            raise RuntimeError("review already moderated")
        review.state = ReviewState.APPROVED if approved else ReviewState.REJECTED
        return review

    def approved_for_plugin(self, plugin_id: str) -> list[PluginReview]:
        return [
            review
            for review in self._reviews.values()
            if review.plugin_id == plugin_id and review.state is ReviewState.APPROVED
        ]

    def average_rating(self, plugin_id: str) -> float | None:
        reviews = self.approved_for_plugin(plugin_id)
        if not reviews:
            return None
        return sum(review.rating for review in reviews) / len(reviews)
