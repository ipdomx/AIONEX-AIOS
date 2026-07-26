from __future__ import annotations

from dataclasses import dataclass

from .catalog import MarketplaceCatalog
from .entitlements import EntitlementManager
from .installations import InstallationManager
from .licensing import LicenseManager
from .reviews import ReviewRegistry


@dataclass
class EnterpriseMarketplacePlatform:
    catalog: MarketplaceCatalog
    licenses: LicenseManager
    entitlements: EntitlementManager
    installations: InstallationManager
    reviews: ReviewRegistry

    @classmethod
    def build_default(cls) -> "EnterpriseMarketplacePlatform":
        catalog = MarketplaceCatalog()
        licenses = LicenseManager()
        entitlements = EntitlementManager()
        installations = InstallationManager(catalog, licenses, entitlements)
        reviews = ReviewRegistry()
        return cls(
            catalog=catalog,
            licenses=licenses,
            entitlements=entitlements,
            installations=installations,
            reviews=reviews,
        )

    def validate(self) -> dict[str, bool]:
        checks = {
            "catalog": self.catalog is not None,
            "license_manager": self.licenses is not None,
            "entitlement_manager": self.entitlements is not None,
            "installation_manager": self.installations is not None,
            "review_registry": self.reviews is not None,
        }
        checks["ready"] = all(checks.values())
        return checks
