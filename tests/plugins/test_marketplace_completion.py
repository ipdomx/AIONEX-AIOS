from aios.plugins.billing import PluginBillingService, PluginPurchase, PurchaseState
from aios.plugins.marketplace import ListingState, PluginListing, PluginMarketplace
from aios.plugins.reviews import PluginReview, PluginReviewService, ReviewState


def test_marketplace_publish_search_and_owner_scope() -> None:
    market = PluginMarketplace()
    market.submit(
        PluginListing(
            plugin_id="plugin-1",
            owner_id="owner-1",
            name="GitHub Automation",
            summary="Repository workflow automation",
            version="1.0.0",
            tags=("github", "automation"),
        )
    )
    assert market.search("github") == []
    listing = market.publish("plugin-1", "owner-1")
    assert listing.state is ListingState.PUBLISHED
    assert market.search("github")[0].plugin_id == "plugin-1"

    try:
        market.suspend("plugin-1", "owner-2")
    except PermissionError:
        pass
    else:
        raise AssertionError("another owner must not manage the listing")


def test_review_moderation_and_average() -> None:
    service = PluginReviewService()
    service.submit(PluginReview("r-1", "plugin-1", "user-1", 5, "Excellent"))
    service.submit(PluginReview("r-2", "plugin-1", "user-2", 3, "Good"))
    service.moderate("r-1", approved=True)
    service.moderate("r-2", approved=True)

    assert service.approved_for_plugin("plugin-1")[0].state is ReviewState.APPROVED
    assert service.average_rating("plugin-1") == 4.0


def test_purchase_settlement_and_refund() -> None:
    billing = PluginBillingService()
    purchase = billing.create(
        PluginPurchase(
            purchase_id="p-1",
            plugin_id="plugin-1",
            buyer_owner_id="buyer",
            seller_owner_id="seller",
            amount_cents=1000,
            platform_fee_cents=150,
        )
    )
    assert purchase.seller_net_cents == 850
    assert billing.mark_paid("p-1").state is PurchaseState.PAID
    assert billing.refund("p-1").state is PurchaseState.REFUNDED
