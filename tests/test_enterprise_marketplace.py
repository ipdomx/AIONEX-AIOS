from aios.enterprise_marketplace import (
    EnterpriseMarketplacePlatform,
    Entitlement,
    Installation,
    InstallationState,
    License,
    LicensePlan,
    MarketplaceItem,
    MarketplaceItemType,
    MarketplaceReview,
    PublicationState,
)


def test_enterprise_marketplace_end_to_end() -> None:
    platform = EnterpriseMarketplacePlatform.build_default()
    item = MarketplaceItem(
        item_id="agent-1",
        name="Reliability Agent",
        item_type=MarketplaceItemType.AGENT,
        publisher_id="publisher-1",
        version="1.0.0",
        description="Enterprise reliability automation",
        capabilities={"reliability.inspect"},
        categories={"operations"},
        price=49.0,
    )
    platform.catalog.register(item)
    item.transition(PublicationState.PENDING_REVIEW)
    item.transition(PublicationState.PUBLISHED)

    license = License(
        license_id="license-1",
        item_id="agent-1",
        organization_id="org-1",
        plan=LicensePlan.ENTERPRISE,
        seats=25,
    )
    platform.licenses.issue(license)
    platform.entitlements.grant(
        Entitlement(
            entitlement_id="entitlement-1",
            license_id="license-1",
            principal_id="owner-1",
            capabilities={"marketplace.install:agent-1"},
        )
    )

    installation = platform.installations.install(
        Installation(
            installation_id="installation-1",
            item_id="agent-1",
            organization_id="org-1",
            license_id="license-1",
            requested_by="owner-1",
        )
    )
    assert installation.state is InstallationState.ACTIVE
    assert platform.catalog.search("reliability")[0].item_id == "agent-1"
    assert platform.validate()["ready"] is True


def test_marketplace_review_and_removal() -> None:
    platform = EnterpriseMarketplacePlatform.build_default()
    item = MarketplaceItem(
        item_id="connector-1",
        name="Secure Connector",
        item_type=MarketplaceItemType.CONNECTOR,
        publisher_id="publisher-2",
        version="2.0.0",
    )
    platform.catalog.register(item)
    item.transition(PublicationState.PENDING_REVIEW)
    item.transition(PublicationState.PUBLISHED)
    platform.reviews.add(
        MarketplaceReview(
            review_id="review-1",
            item_id="connector-1",
            reviewer_id="reviewer-1",
            rating=5,
            approved=True,
        )
    )
    assert platform.reviews.average_rating("connector-1") == 5.0
