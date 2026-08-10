"""Owner-controlled public portal presentation, pricing catalogue, and assets.

The public VIP frontend is a static shell.  This service provides the versioned,
durable configuration that the shell consumes at runtime, allowing the Super
Owner to change branding, design tokens, navigation, page sections, pricing,
SEO, announcements, contact details, and assets without rebuilding the portal.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from defusedxml import ElementTree as ET  # type: ignore[import-untyped]
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal
from urllib.parse import urlparse

from fastapi import HTTPException, UploadFile, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import AuditEvent, OwnerControlRecord, uuid_str

# UserRecord is intentionally not imported here to keep this service independent
# from the authentication layer; actor fields are supplied explicitly.

SUPPORTED_LOCALES = ("ar", "en", "fr", "de", "es", "tr")
PORTAL_DOMAIN = "portal-cms"
ASSET_DOMAIN = "portal-assets"
DRAFT_RESOURCE = "draft"
PUBLISHED_RESOURCE = "published"
HISTORY_PREFIX = "history-"
MAX_CONFIGURATION_BYTES = 750_000
MAX_HISTORY = 100
SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
SAFE_FONT_FAMILY = re.compile(r"^[A-Za-z0-9 _,'\"-]{1,120}$")
HEX_COLOR = re.compile(r"^#[0-9A-Fa-f]{6}([0-9A-Fa-f]{2})?$")
SECRET_FIELD_NAMES = {
    "api_key",
    "secret",
    "secret_key",
    "password",
    "private_key",
    "credential",
    "credentials",
    "access_token",
    "refresh_token",
    "bot_token",
}
SECRET_VALUE_PATTERNS = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(
        r"\b(?:sk_live_|sk_test_|sk-proj-|ghp_|github_pat_|xox[baprs]-)[A-Za-z0-9_-]{12,}"
    ),
)


class PortalConfigurationError(ValueError):
    """Raised when a portal configuration cannot be safely accepted."""


def _localized(
    english: str,
    arabic: str,
    *,
    french: str | None = None,
    german: str | None = None,
    spanish: str | None = None,
    turkish: str | None = None,
) -> dict[str, str]:
    return {
        "ar": arabic,
        "en": english,
        "fr": french or english,
        "de": german or english,
        "es": spanish or english,
        "tr": turkish or english,
    }


def _validate_localized(value: dict[str, str], *, field_name: str) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be a localized object")
    unknown = sorted(set(value) - set(SUPPORTED_LOCALES))
    if unknown:
        raise ValueError(
            f"{field_name} contains unsupported locales: {', '.join(unknown)}"
        )
    normalized: dict[str, str] = {}
    for locale in SUPPORTED_LOCALES:
        text = str(
            value.get(locale) or value.get("en") or value.get("ar") or ""
        ).strip()
        if len(text) > 5000:
            raise ValueError(f"{field_name}.{locale} exceeds 5000 characters")
        normalized[locale] = text
    return normalized


def _safe_url(value: str, *, allow_empty: bool = True) -> str:
    normalized = value.strip()
    if not normalized and allow_empty:
        return ""
    if any(
        character in normalized
        for character in ("\x00", "\r", "\n", "\\", '"', "'", "(", ")", "<", ">")
    ):
        raise ValueError("URL contains unsafe characters")
    if normalized.startswith("/"):
        if normalized.startswith("//") or ".." in normalized.split("/"):
            raise ValueError("relative URL escapes the public origin")
        return normalized
    parsed = urlparse(normalized)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise ValueError("portal URLs must be root-relative or HTTPS")
    return normalized


def _validate_safe_json(
    value: Any, *, depth: int = 0, path: str = "configuration"
) -> Any:
    if depth > 10:
        raise ValueError(f"{path} exceeds the maximum nesting depth")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) > 10_000:
            raise ValueError(f"{path} contains an oversized string")
        lowered = value.lower()
        forbidden = (
            "<script",
            "javascript:",
            "data:text/html",
            "vbscript:",
            "onerror=",
            "onload=",
        )
        if any(marker in lowered for marker in forbidden):
            raise ValueError(f"{path} contains executable content")
        if any(pattern.search(value) for pattern in SECRET_VALUE_PATTERNS):
            raise ValueError(f"{path} contains secret-shaped content")
        return value
    if isinstance(value, list):
        if len(value) > 500:
            raise ValueError(f"{path} contains too many list items")
        return [
            _validate_safe_json(item, depth=depth + 1, path=f"{path}[{index}]")
            for index, item in enumerate(value)
        ]
    if isinstance(value, dict):
        if len(value) > 500:
            raise ValueError(f"{path} contains too many fields")
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key).strip()
            if (
                not key_text
                or len(key_text) > 120
                or any(char in key_text for char in ("\x00", "\r", "\n"))
            ):
                raise ValueError(f"{path} contains an unsafe key")
            normalized_key = key_text.lower().replace("-", "_")
            if normalized_key in SECRET_FIELD_NAMES:
                raise ValueError(f"{path}.{key_text} is not a public portal field")
            normalized[key_text] = _validate_safe_json(
                item,
                depth=depth + 1,
                path=f"{path}.{key_text}",
            )
        return normalized
    raise ValueError(f"{path} contains an unsupported value type")


class PortalBranding(BaseModel):
    site_name: str = Field(default="AIONEX AIOS", min_length=1, max_length=120)
    short_name: str = Field(default="AIONEX", min_length=1, max_length=40)
    wordmark_suffix: str = Field(default="AIOS", max_length=30)
    logo_url: str = "/brand/aionex-mark.svg"
    icon_url: str = "/icons/aionex-192.png"
    favicon_url: str = "/brand/aionex-mark.svg"
    logo_alt: dict[str, str] = Field(
        default_factory=lambda: _localized("AIONEX AIOS", "AIONEX AIOS")
    )
    tagline: dict[str, str] = Field(
        default_factory=lambda: _localized(
            "Governed AI project delivery",
            "تنفيذ مشروعات الذكاء الاصطناعي بضوابط واضحة",
        )
    )

    @field_validator("logo_url", "icon_url", "favicon_url")
    @classmethod
    def validate_asset_url(cls, value: str) -> str:
        return _safe_url(value)

    @field_validator("logo_alt", "tagline")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(value, field_name=info.field_name)


class PortalTheme(BaseModel):
    default_mode: Literal["dark", "light", "system"] = "dark"
    page_color: str = "#03050A"
    page_deep_color: str = "#070B14"
    surface_color: str = "#0B1220"
    text_color: str = "#FFFFFF"
    muted_color: str = "#94A3B8"
    primary_color: str = "#14B8E6"
    secondary_color: str = "#8B5CF6"
    success_color: str = "#10B981"
    warning_color: str = "#F59E0B"
    danger_color: str = "#EF4444"
    heading_font_family: str = 'Inter, "Segoe UI", Arial, sans-serif'
    body_font_family: str = 'Inter, "Segoe UI", Arial, sans-serif'
    arabic_font_family: str = "Tahoma, Arial, sans-serif"
    heading_font_url: str = ""
    body_font_url: str = ""
    arabic_font_url: str = ""
    radius_px: int = Field(default=16, ge=0, le=48)
    page_max_width_px: int = Field(default=1280, ge=960, le=1920)
    section_spacing_px: int = Field(default=96, ge=40, le=200)
    logo_size_px: int = Field(default=42, ge=24, le=128)
    button_style: Literal["rounded", "pill", "square"] = "rounded"
    background_grid: bool = True
    background_glow: bool = True
    background_image_url: str = ""
    background_image_position: Literal["center", "top", "bottom", "left", "right"] = (
        "center"
    )
    background_image_opacity: float = Field(default=0.12, ge=0, le=1)

    @field_validator("background_image_url")
    @classmethod
    def validate_background_image_url(cls, value: str) -> str:
        return _safe_url(value)

    @field_validator(
        "page_color",
        "page_deep_color",
        "surface_color",
        "text_color",
        "muted_color",
        "primary_color",
        "secondary_color",
        "success_color",
        "warning_color",
        "danger_color",
    )
    @classmethod
    def validate_color(cls, value: str) -> str:
        if not HEX_COLOR.fullmatch(value.strip()):
            raise ValueError("theme colors must use #RRGGBB or #RRGGBBAA")
        return value.upper()

    @field_validator("heading_font_family", "body_font_family", "arabic_font_family")
    @classmethod
    def validate_font_family(cls, value: str) -> str:
        normalized = value.strip()
        if not SAFE_FONT_FAMILY.fullmatch(normalized):
            raise ValueError("font family contains unsupported characters")
        return normalized

    @field_validator("heading_font_url", "body_font_url", "arabic_font_url")
    @classmethod
    def validate_font_url(cls, value: str) -> str:
        return _safe_url(value)


class PortalNavigationItem(BaseModel):
    id: str
    href: str
    label: dict[str, str]
    enabled: bool = True
    order: int = Field(default=0, ge=0, le=10_000)
    audience: Literal["all", "guest", "authenticated"] = "all"
    external: bool = False

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("navigation id is invalid")
        return value

    @field_validator("href")
    @classmethod
    def validate_href(cls, value: str) -> str:
        return _safe_url(value, allow_empty=False)

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_localized(value, field_name="navigation.label")


class PortalSection(BaseModel):
    id: str
    type: Literal[
        "hero",
        "features",
        "steps",
        "cta",
        "rich-text",
        "image-text",
        "stats",
        "faq",
        "logo-cloud",
        "contact",
        "pricing",
    ]
    enabled: bool = True
    order: int = Field(default=0, ge=0, le=10_000)
    content: dict[str, Any] = Field(default_factory=dict)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("section id is invalid")
        return value

    @field_validator("content")
    @classmethod
    def validate_content(cls, value: dict[str, Any]) -> dict[str, Any]:
        return _validate_safe_json(value, path="section.content")


class PortalSEO(BaseModel):
    title: dict[str, str]
    description: dict[str, str]
    keywords: dict[str, str] = Field(default_factory=lambda: _localized("", ""))
    image_url: str = ""
    noindex: bool = False

    @field_validator("title", "description", "keywords")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(value, field_name=f"seo.{info.field_name}")

    @field_validator("image_url")
    @classmethod
    def validate_image_url(cls, value: str) -> str:
        return _safe_url(value)


class PortalPage(BaseModel):
    slug: str
    enabled: bool = True
    navigation_label: dict[str, str]
    sections: list[PortalSection] = Field(default_factory=list, max_length=100)
    seo: PortalSEO

    @field_validator("slug")
    @classmethod
    def validate_slug(cls, value: str) -> str:
        normalized = value.strip().strip("/")
        if normalized and not re.fullmatch(r"[a-z0-9-]+(?:/[a-z0-9-]+)*", normalized):
            raise ValueError("page slug is invalid")
        return normalized

    @field_validator("navigation_label")
    @classmethod
    def validate_navigation_label(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_localized(value, field_name="page.navigation_label")

    @model_validator(mode="after")
    def unique_sections(self):
        identifiers = [section.id for section in self.sections]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("page section ids must be unique")
        return self


class PortalBillingPeriod(BaseModel):
    id: str
    label: dict[str, str]
    months: int = Field(ge=0, le=120)
    price: float | None = Field(default=None, ge=0, le=10_000_000)
    compare_at_price: float | None = Field(default=None, ge=0, le=10_000_000)
    currency: str = Field(default="USD", min_length=3, max_length=3)
    enabled: bool = True
    checkout_provider: (
        Literal["none", "stripe", "paddle", "paypal", "manual", "bank_transfer"] | None
    ) = None
    checkout_reference: str = Field(default="", max_length=255)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("billing period id is invalid")
        return value

    @field_validator("label")
    @classmethod
    def validate_label(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_localized(value, field_name="billing_period.label")

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper()
        if not normalized.isalpha():
            raise ValueError("currency must be a three-letter code")
        return normalized

    @model_validator(mode="after")
    def compare_price(self):
        if (
            self.compare_at_price is not None
            and self.price is not None
            and self.compare_at_price < self.price
        ):
            raise ValueError("compare_at_price cannot be lower than price")
        return self


class PortalPricingPlan(BaseModel):
    id: str
    enabled: bool = False
    featured: bool = False
    order: int = Field(default=0, ge=0, le=10_000)
    name: dict[str, str]
    description: dict[str, str]
    badge: dict[str, str] = Field(default_factory=lambda: _localized("", ""))
    periods: list[PortalBillingPeriod] = Field(default_factory=list, max_length=12)
    features: list[dict[str, str]] = Field(default_factory=list, max_length=100)
    limits: dict[str, int | float | str | bool | None] = Field(default_factory=dict)
    entitlements: list[str] = Field(default_factory=list, max_length=200)
    metering: dict[str, dict[str, int | str]] = Field(default_factory=dict)
    cta_label: dict[str, str]
    cta_url: str = "/register"
    checkout_provider: Literal[
        "none", "stripe", "paddle", "paypal", "manual", "bank_transfer"
    ] = "none"
    checkout_reference: str = Field(default="", max_length=200)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("pricing plan id is invalid")
        return value

    @field_validator("name", "description", "badge", "cta_label")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(value, field_name=f"pricing.{info.field_name}")

    @field_validator("features")
    @classmethod
    def validate_features(cls, value: list[dict[str, str]]) -> list[dict[str, str]]:
        return [
            _validate_localized(item, field_name=f"pricing.features[{index}]")
            for index, item in enumerate(value)
        ]

    @field_validator("cta_url")
    @classmethod
    def validate_cta_url(cls, value: str) -> str:
        return _safe_url(value, allow_empty=False)

    @field_validator("entitlements")
    @classmethod
    def validate_entitlements(cls, value: list[str]) -> list[str]:
        normalized = []
        for item in value:
            text = str(item).strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,119}", text):
                raise ValueError("pricing entitlement is invalid")
            if text not in normalized:
                normalized.append(text)
        return normalized

    @field_validator("metering")
    @classmethod
    def validate_metering(cls, value: dict[str, dict[str, int | str]]):
        normalized: dict[str, dict[str, int | str]] = {}
        for metric, raw in value.items():
            key = str(metric).strip().lower()
            if not re.fullmatch(r"[a-z0-9][a-z0-9._:-]{0,119}", key):
                raise ValueError("pricing metering metric is invalid")
            rule = dict(raw or {})
            for numeric in ("included", "unit_size", "unit_price_minor"):
                if numeric in rule and int(rule[numeric]) < 0:
                    raise ValueError("pricing metering values cannot be negative")
            normalized[key] = rule
        return normalized

    @model_validator(mode="after")
    def unique_periods(self):
        identifiers = [period.id for period in self.periods]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("billing period ids must be unique per plan")
        return self


class PortalPricingCatalogue(BaseModel):
    enabled: bool = True
    show_tax_note: bool = True
    default_currency: str = "USD"
    default_period: str = "monthly"
    heading: dict[str, str]
    description: dict[str, str]
    tax_note: dict[str, str]
    plans: list[PortalPricingPlan] = Field(default_factory=list, max_length=50)
    faq: list[dict[str, dict[str, str]]] = Field(default_factory=list, max_length=100)

    @field_validator("heading", "description", "tax_note")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(
            value, field_name=f"pricing_catalogue.{info.field_name}"
        )

    @field_validator("default_currency")
    @classmethod
    def validate_currency(cls, value: str) -> str:
        normalized = value.upper()
        if len(normalized) != 3 or not normalized.isalpha():
            raise ValueError("default currency must be a three-letter code")
        return normalized

    @field_validator("faq")
    @classmethod
    def validate_faq(cls, value: list[dict[str, dict[str, str]]]):
        normalized = []
        for index, item in enumerate(value):
            if set(item) != {"question", "answer"}:
                raise ValueError("each pricing FAQ item requires question and answer")
            normalized.append(
                {
                    "question": _validate_localized(
                        item["question"], field_name=f"faq[{index}].question"
                    ),
                    "answer": _validate_localized(
                        item["answer"], field_name=f"faq[{index}].answer"
                    ),
                }
            )
        return normalized

    @model_validator(mode="after")
    def unique_plans(self):
        identifiers = [plan.id for plan in self.plans]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("pricing plan ids must be unique")
        return self


class PortalFooterColumn(BaseModel):
    id: str
    title: dict[str, str]
    links: list[PortalNavigationItem] = Field(default_factory=list, max_length=50)

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not SAFE_ID.fullmatch(value):
            raise ValueError("footer column id is invalid")
        return value

    @field_validator("title")
    @classmethod
    def validate_title(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_localized(value, field_name="footer.title")


class PortalFooter(BaseModel):
    enabled: bool = True
    description: dict[str, str]
    security_note: dict[str, str]
    copyright_text: dict[str, str]
    columns: list[PortalFooterColumn] = Field(default_factory=list, max_length=12)

    @field_validator("description", "security_note", "copyright_text")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(value, field_name=f"footer.{info.field_name}")


class PortalAnnouncement(BaseModel):
    enabled: bool = False
    severity: Literal["info", "success", "warning", "critical"] = "info"
    message: dict[str, str] = Field(default_factory=lambda: _localized("", ""))
    link_label: dict[str, str] = Field(default_factory=lambda: _localized("", ""))
    link_url: str = ""
    dismissible: bool = True

    @field_validator("message", "link_label")
    @classmethod
    def validate_localized_fields(cls, value: dict[str, str], info):
        return _validate_localized(value, field_name=f"announcement.{info.field_name}")

    @field_validator("link_url")
    @classmethod
    def validate_link_url(cls, value: str) -> str:
        return _safe_url(value)


class PortalContact(BaseModel):
    support_email: str = Field(default="", max_length=320)
    sales_email: str = Field(default="", max_length=320)
    phone: str = Field(default="", max_length=40)
    whatsapp_url: str = ""
    address: dict[str, str] = Field(default_factory=lambda: _localized("", ""))
    social_links: dict[str, str] = Field(default_factory=dict)

    @field_validator("support_email", "sales_email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized and not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,255}", normalized):
            raise ValueError("contact email is invalid")
        return normalized

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, value: str) -> str:
        normalized = value.strip()
        if normalized and not re.fullmatch(r"[+0-9() .-]{7,40}", normalized):
            raise ValueError("contact phone contains unsupported characters")
        return normalized

    @field_validator("whatsapp_url")
    @classmethod
    def validate_whatsapp_url(cls, value: str) -> str:
        return _safe_url(value)

    @field_validator("address")
    @classmethod
    def validate_address(cls, value: dict[str, str]) -> dict[str, str]:
        return _validate_localized(value, field_name="contact.address")

    @field_validator("social_links")
    @classmethod
    def validate_social_links(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {}
        for key, url in value.items():
            identifier = str(key).strip().lower()
            if not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", identifier):
                raise ValueError("social link id is invalid")
            normalized[identifier] = _safe_url(str(url), allow_empty=False)
        return normalized


class PortalConfiguration(BaseModel):
    schema_version: Literal[1] = 1
    branding: PortalBranding
    theme: PortalTheme
    navigation: list[PortalNavigationItem] = Field(default_factory=list, max_length=100)
    pages: dict[str, PortalPage]
    pricing: PortalPricingCatalogue
    footer: PortalFooter
    announcement: PortalAnnouncement = Field(default_factory=PortalAnnouncement)
    contact: PortalContact = Field(default_factory=PortalContact)
    translation_overrides: dict[str, dict[str, str]] = Field(default_factory=dict)
    custom_metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("translation_overrides")
    @classmethod
    def validate_translation_overrides(cls, value: dict[str, dict[str, str]]):
        if len(value) > 2000:
            raise ValueError("too many translation overrides")
        normalized = {}
        for key, localized in value.items():
            if not re.fullmatch(r"[A-Za-z0-9_.-]{1,160}", key):
                raise ValueError("translation override key is invalid")
            normalized[key] = _validate_localized(
                localized, field_name=f"translation_overrides.{key}"
            )
        return normalized

    @field_validator("custom_metadata")
    @classmethod
    def validate_custom_metadata(cls, value: dict[str, Any]):
        return _validate_safe_json(value, path="custom_metadata")

    @model_validator(mode="after")
    def consistency(self):
        navigation_ids = [item.id for item in self.navigation]
        if len(navigation_ids) != len(set(navigation_ids)):
            raise ValueError("navigation item ids must be unique")
        if "home" not in self.pages or self.pages["home"].slug != "":
            raise ValueError("pages.home with an empty slug is required")
        for key, page in self.pages.items():
            if not SAFE_ID.fullmatch(key):
                raise ValueError("page identifiers must be safe ids")
            if key != "home" and not page.slug:
                raise ValueError("only the home page may have an empty slug")
        public_payload = self.model_dump(mode="json")
        _validate_safe_json(public_payload, path="configuration")
        encoded = json.dumps(public_payload, ensure_ascii=False, sort_keys=True).encode(
            "utf-8"
        )
        if len(encoded) > MAX_CONFIGURATION_BYTES:
            raise ValueError("portal configuration exceeds the maximum size")
        return self


def default_portal_configuration() -> dict[str, Any]:
    home_sections = [
        {
            "id": "hero",
            "type": "hero",
            "order": 10,
            "content": {
                "eyebrow": _localized("Governed intelligence", "ذكاء محكوم"),
                "title_lead": _localized(
                    "Turn ambitious ideas into", "حوّل الأفكار الطموحة إلى"
                ),
                "title_accent": _localized(
                    "disciplined AI execution", "تنفيذ ذكي منضبط"
                ),
                "description": _localized(
                    "AIONEX AIOS combines agents, models, memory, project workflows, safety controls, and recovery in one scalable operating layer.",
                    "يجمع AIONEX AIOS الوكلاء والنماذج والذاكرة ومسارات المشاريع وضوابط الأمان والتعافي في طبقة تشغيل واحدة قابلة للتوسع.",
                ),
                "primary_label": _localized("Create your account", "أنشئ حسابك"),
                "primary_url": "/register",
                "secondary_label": _localized("Explore the system", "استكشف النظام"),
                "secondary_url": "/about",
                "honesty_note": _localized(
                    "Service availability and account limits are loaded from the active platform policy.",
                    "يتم تحميل إتاحة الحساب وحدود الاستخدام من سياسة المنصة النشطة.",
                ),
                "image_url": "/brand/aionex-mark.svg",
            },
        },
        {
            "id": "capabilities",
            "type": "features",
            "order": 20,
            "content": {
                "eyebrow": _localized("Capabilities", "القدرات"),
                "title": _localized(
                    "One operating layer for the project lifecycle",
                    "طبقة تشغيل واحدة لدورة حياة المشروع",
                ),
                "description": _localized(
                    "Plan, coordinate, execute, review, secure, and improve work from one governed environment.",
                    "خطط ونسّق ونفّذ وراجع وأمّن وطوّر العمل من بيئة واحدة محكومة.",
                ),
                "items": [
                    {
                        "icon": "workflow",
                        "title": _localized("Project orchestration", "تنسيق المشروعات"),
                        "copy": _localized(
                            "Structured workflows, evidence, approvals, and status visibility.",
                            "مسارات منظمة وأدلة وموافقات ورؤية واضحة للحالة.",
                        ),
                    },
                    {
                        "icon": "brain",
                        "title": _localized(
                            "Multi-model intelligence", "ذكاء متعدد النماذج"
                        ),
                        "copy": _localized(
                            "Route work to suitable models and agents under owner controls.",
                            "توجيه العمل للنماذج والوكلاء المناسبين تحت تحكم المالك.",
                        ),
                    },
                    {
                        "icon": "shield",
                        "title": _localized("Safety and governance", "الأمان والحوكمة"),
                        "copy": _localized(
                            "Budgets, permissions, audit evidence, and production boundaries.",
                            "ميزانيات وصلاحيات وأدلة تدقيق وحدود واضحة للإنتاج.",
                        ),
                    },
                    {
                        "icon": "network",
                        "title": _localized("Scalable execution", "تنفيذ قابل للتوسع"),
                        "copy": _localized(
                            "Durable workers, retries, recovery, and controlled distributed execution.",
                            "عمال دائمون وإعادة محاولات وتعافٍ وتنفيذ موزع منضبط.",
                        ),
                    },
                    {
                        "icon": "shield",
                        "title": _localized(
                            "Adaptive security validation",
                            "تحقق أمني متكيّف",
                            french="Validation de sécurité adaptative",
                            german="Adaptive Sicherheitsvalidierung",
                            spanish="Validación de seguridad adaptativa",
                            turkish="Uyarlanabilir güvenlik doğrulaması",
                        ),
                        "copy": _localized(
                            "Combine source, dependency, secret, API, TLS, container, and authorized runtime evidence with learning and verified remediation.",
                            "ادمج أدلة الكود والحزم والأسرار وواجهات API وTLS والحاويات والفحص التشغيلي المصرح به مع التعلم والإصلاح المتحقق منه.",
                            french="Croisez le code, les dépendances, les secrets, les API, TLS, les conteneurs et les contrôles d’exécution autorisés avec apprentissage et remédiation vérifiée.",
                            german="Kombiniert Quellcode-, Abhängigkeits-, Secret-, API-, TLS-, Container- und autorisierte Laufzeitprüfungen mit Lernen und verifizierter Behebung.",
                            spanish="Combina evidencia de código, dependencias, secretos, API, TLS, contenedores y ejecución autorizada con aprendizaje y remediación verificada.",
                            turkish="Kaynak, bağımlılık, gizli bilgi, API, TLS, konteyner ve yetkili çalışma zamanı kanıtlarını öğrenme ve doğrulanmış düzeltmeyle birleştirir.",
                        ),
                    },
                ],
            },
        },
        {
            "id": "workflow",
            "type": "steps",
            "order": 30,
            "content": {
                "eyebrow": _localized("Workflow", "مسار العمل"),
                "title": _localized("From request to evidence", "من الطلب إلى الدليل"),
                "description": _localized(
                    "Every project moves through explicit stages with measurable evidence.",
                    "يمر كل مشروع بمراحل واضحة مع أدلة قابلة للقياس.",
                ),
                "items": [
                    {
                        "title": _localized("Define", "التعريف"),
                        "copy": _localized(
                            "Capture the objective, constraints, budget, and success criteria.",
                            "تحديد الهدف والقيود والميزانية ومعايير النجاح.",
                        ),
                    },
                    {
                        "title": _localized("Execute", "التنفيذ"),
                        "copy": _localized(
                            "Coordinate providers, agents, tools, and project workers.",
                            "تنسيق المزودين والوكلاء والأدوات وعمال المشروع.",
                        ),
                    },
                    {
                        "title": _localized("Review", "المراجعة"),
                        "copy": _localized(
                            "Collect evidence, identify rework, and approve only proven outcomes.",
                            "جمع الأدلة وتحديد إعادة العمل واعتماد النتائج المثبتة فقط.",
                        ),
                    },
                ],
            },
        },
        {
            "id": "cta",
            "type": "cta",
            "order": 40,
            "content": {
                "title": _localized(
                    "Start with a controlled project", "ابدأ بمشروع منضبط"
                ),
                "description": _localized(
                    "Create an account and test the platform within the owner-defined limits.",
                    "أنشئ حسابًا وجرّب المنصة ضمن الحدود التي يحددها المالك.",
                ),
                "button_label": _localized("Get started", "ابدأ الآن"),
                "button_url": "/register",
            },
        },
    ]
    pricing_plans = [
        {
            "id": "free",
            "enabled": True,
            "featured": False,
            "order": 10,
            "name": _localized("Free", "مجاني"),
            "description": _localized(
                "Evaluate the core user journey before upgrading.",
                "جرّب رحلة المستخدم الأساسية قبل الترقية.",
            ),
            "badge": _localized("Start here", "ابدأ من هنا"),
            "periods": [
                {
                    "id": "monthly",
                    "label": _localized("Monthly", "شهري"),
                    "months": 1,
                    "price": 0,
                    "currency": "USD",
                    "enabled": True,
                }
            ],
            "features": [
                _localized("One project", "مشروع واحد"),
                _localized(
                    "Owner-defined monthly message quota",
                    "حصة رسائل شهرية يحددها المالك",
                ),
                _localized(
                    "Core project execution access", "الوصول الأساسي لتنفيذ المشروعات"
                ),
            ],
            "limits": {"projects": 1},
            "entitlements": ["projects.core"],
            "cta_label": _localized("Create free account", "أنشئ حسابًا مجانيًا"),
            "cta_url": "/register",
            "checkout_provider": "none",
        },
        {
            "id": "professional",
            "enabled": False,
            "featured": True,
            "order": 20,
            "name": _localized("Professional", "احترافي"),
            "description": _localized(
                "For active professionals and growing project workloads.",
                "للمحترفين وأحمال المشروعات المتنامية.",
            ),
            "badge": _localized("Recommended", "موصى به"),
            "periods": [
                {
                    "id": "monthly",
                    "label": _localized("Monthly", "شهري"),
                    "months": 1,
                    "price": None,
                    "currency": "USD",
                    "enabled": True,
                },
                {
                    "id": "yearly",
                    "label": _localized("Yearly", "سنوي"),
                    "months": 12,
                    "price": None,
                    "currency": "USD",
                    "enabled": True,
                },
            ],
            "features": [
                _localized(
                    "Configure features from Owner Control",
                    "اضبط المزايا من لوحة المالك",
                )
            ],
            "limits": {},
            "entitlements": [],
            "cta_label": _localized("Contact sales", "تواصل مع المبيعات"),
            "cta_url": "/contact",
            "checkout_provider": "none",
        },
        {
            "id": "business",
            "enabled": False,
            "featured": False,
            "order": 30,
            "name": _localized("Business", "أعمال"),
            "description": _localized(
                "For teams requiring governed capacity and support.",
                "للفرق التي تحتاج سعة محكومة ودعمًا مخصصًا.",
            ),
            "badge": _localized("Custom", "مخصص"),
            "periods": [
                {
                    "id": "monthly",
                    "label": _localized("Monthly", "شهري"),
                    "months": 1,
                    "price": None,
                    "currency": "USD",
                    "enabled": True,
                },
                {
                    "id": "yearly",
                    "label": _localized("Yearly", "سنوي"),
                    "months": 12,
                    "price": None,
                    "currency": "USD",
                    "enabled": True,
                },
            ],
            "features": [
                _localized(
                    "Configure features from Owner Control",
                    "اضبط المزايا من لوحة المالك",
                )
            ],
            "limits": {},
            "entitlements": ["3d.generation"],
            "cta_label": _localized("Contact sales", "تواصل مع المبيعات"),
            "cta_url": "/contact",
            "checkout_provider": "manual",
        },
    ]
    configuration = PortalConfiguration(
        branding=PortalBranding(),
        theme=PortalTheme(),
        navigation=[
            PortalNavigationItem(
                id="home", href="/", label=_localized("Home", "الرئيسية"), order=10
            ),
            PortalNavigationItem(
                id="about",
                href="/about",
                label=_localized("About", "عن المنصة"),
                order=20,
            ),
            PortalNavigationItem(
                id="pricing",
                href="/pricing",
                label=_localized("Pricing", "الأسعار"),
                order=30,
            ),
            PortalNavigationItem(
                id="contact",
                href="/contact",
                label=_localized("Contact", "تواصل معنا"),
                order=40,
            ),
        ],
        pages={
            "home": PortalPage(
                slug="",
                navigation_label=_localized("Home", "الرئيسية"),
                sections=[PortalSection.model_validate(item) for item in home_sections],
                seo=PortalSEO(
                    title=_localized(
                        "AIONEX AIOS — Governed AI project execution",
                        "AIONEX AIOS — تنفيذ مشروعات ذكية منضبط",
                    ),
                    description=_localized(
                        "Plan and execute AI projects with governed providers, agents, evidence, and owner controls.",
                        "خطط ونفّذ مشروعات الذكاء الاصطناعي بمزودين ووكلاء وأدلة وتحكم كامل للمالك.",
                    ),
                ),
            ),
            "about": PortalPage(
                slug="about",
                navigation_label=_localized("About", "عن المنصة"),
                sections=[
                    PortalSection(
                        id="about-hero",
                        type="rich-text",
                        order=10,
                        content={
                            "eyebrow": _localized("About AIONEX", "عن AIONEX"),
                            "title": _localized(
                                "An operating system for governed AI delivery",
                                "نظام تشغيل لتنفيذ الذكاء الاصطناعي بحوكمة واضحة",
                            ),
                            "body": _localized(
                                "AIONEX AIOS brings project planning, providers, agents, memory, evidence, security, owner controls, and recovery into one operating layer.",
                                "يجمع AIONEX AIOS تخطيط المشروعات والمزودين والوكلاء والذاكرة والأدلة والأمان وتحكم المالك والتعافي في طبقة تشغيل واحدة.",
                            ),
                        },
                    ),
                    PortalSection(
                        id="about-principles",
                        type="features",
                        order=20,
                        content={
                            "eyebrow": _localized("Principles", "المبادئ"),
                            "title": _localized(
                                "Built around control and evidence",
                                "مبني حول التحكم والأدلة",
                            ),
                            "description": _localized(
                                "The owner can govern the product while every execution remains measurable.",
                                "يستطيع المالك إدارة المنتج بينما يظل كل تنفيذ قابلًا للقياس.",
                            ),
                            "items": [
                                {
                                    "icon": "shield",
                                    "title": _localized(
                                        "Security first", "الأمان أولًا"
                                    ),
                                    "copy": _localized(
                                        "Permissions, budgets, audit trails, and production boundaries.",
                                        "صلاحيات وميزانيات وسجلات تدقيق وحدود واضحة للإنتاج.",
                                    ),
                                },
                                {
                                    "icon": "workflow",
                                    "title": _localized(
                                        "Explicit workflows", "مسارات واضحة"
                                    ),
                                    "copy": _localized(
                                        "Projects move through visible stages, reviews, and evidence.",
                                        "تمر المشروعات بمراحل ومراجعات وأدلة مرئية.",
                                    ),
                                },
                                {
                                    "icon": "brain",
                                    "title": _localized(
                                        "Provider choice", "اختيار المزود"
                                    ),
                                    "copy": _localized(
                                        "Models and services remain replaceable under owner policy.",
                                        "تظل النماذج والخدمات قابلة للتبديل وفق سياسة المالك.",
                                    ),
                                },
                                {
                                    "icon": "network",
                                    "title": _localized(
                                        "Scalable foundation", "أساس قابل للتوسع"
                                    ),
                                    "copy": _localized(
                                        "Start on one server and scale only when usage justifies cost.",
                                        "ابدأ على خادم واحد وتوسع فقط عندما يبرر الاستخدام التكلفة.",
                                    ),
                                },
                            ],
                        },
                    ),
                ],
                seo=PortalSEO(
                    title=_localized("About AIONEX AIOS", "عن AIONEX AIOS"),
                    description=_localized(
                        "Mission, principles, and product scope.",
                        "رسالة المنصة ومبادئها ونطاقها.",
                    ),
                ),
            ),
            "pricing": PortalPage(
                slug="pricing",
                navigation_label=_localized("Pricing", "الأسعار"),
                sections=[
                    PortalSection(id="pricing", type="pricing", order=10, content={})
                ],
                seo=PortalSEO(
                    title=_localized("Plans and pricing", "الخطط والأسعار"),
                    description=_localized(
                        "Compare active AIONEX AIOS plans and subscription periods.",
                        "قارن خطط AIONEX AIOS النشطة ومدد الاشتراك.",
                    ),
                ),
            ),
            "contact": PortalPage(
                slug="contact",
                navigation_label=_localized("Contact", "تواصل معنا"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Contact AIONEX AIOS", "تواصل مع AIONEX AIOS"),
                    description=_localized(
                        "Contact support or sales.", "تواصل مع الدعم أو المبيعات."
                    ),
                ),
            ),
            "privacy": PortalPage(
                slug="legal/privacy",
                navigation_label=_localized("Privacy", "الخصوصية"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Privacy policy", "سياسة الخصوصية"),
                    description=_localized(
                        "How AIONEX AIOS handles account and service data.",
                        "كيفية تعامل AIONEX AIOS مع بيانات الحساب والخدمة.",
                    ),
                ),
            ),
            "terms": PortalPage(
                slug="legal/terms",
                navigation_label=_localized("Terms", "الشروط"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Terms of service", "شروط الخدمة"),
                    description=_localized(
                        "Terms governing access to AIONEX AIOS.",
                        "الشروط المنظمة لاستخدام AIONEX AIOS.",
                    ),
                ),
            ),
            "login": PortalPage(
                slug="login",
                navigation_label=_localized("Login", "تسجيل الدخول"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Sign in", "تسجيل الدخول"),
                    description=_localized(
                        "Sign in to your AIONEX AIOS account.",
                        "سجل الدخول إلى حساب AIONEX AIOS.",
                    ),
                    noindex=True,
                ),
            ),
            "register": PortalPage(
                slug="register",
                navigation_label=_localized("Register", "إنشاء حساب"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Create account", "إنشاء حساب"),
                    description=_localized(
                        "Create an AIONEX AIOS account.", "أنشئ حساب AIONEX AIOS."
                    ),
                    noindex=True,
                ),
            ),
            "dashboard": PortalPage(
                slug="dashboard",
                navigation_label=_localized("Dashboard", "لوحة المستخدم"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("User dashboard", "لوحة المستخدم"),
                    description=_localized(
                        "Your AIONEX AIOS account dashboard.",
                        "لوحة حسابك في AIONEX AIOS.",
                    ),
                    noindex=True,
                ),
            ),
            "projects": PortalPage(
                slug="projects",
                navigation_label=_localized("Projects", "المشروعات"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Projects", "المشروعات"),
                    description=_localized(
                        "Create, execute, and review projects.",
                        "أنشئ المشروعات ونفذها وراجعها.",
                    ),
                    noindex=True,
                ),
            ),
            "security-lab": PortalPage(
                slug="security-lab",
                navigation_label=_localized(
                    "Security Lab",
                    "مختبر الأمان",
                    french="Laboratoire de sécurité",
                    german="Security Lab",
                    spanish="Laboratorio de seguridad",
                    turkish="Güvenlik Laboratuvarı",
                ),
                sections=[],
                seo=PortalSEO(
                    title=_localized(
                        "Security Lab",
                        "مختبر الأمان",
                        french="Laboratoire de sécurité",
                        german="Security Lab",
                        spanish="Laboratorio de seguridad",
                        turkish="Güvenlik Laboratuvarı",
                    ),
                    description=_localized(
                        "Owner-granted security validation for authorized AIONEX project targets.",
                        "تحقق أمني يمنحه المالك لأهداف مشروعات AIONEX المصرح بها.",
                        french="Validation de sécurité accordée par le propriétaire pour les cibles de projets AIONEX autorisées.",
                        german="Vom Eigentümer freigegebene Sicherheitsvalidierung für autorisierte AIONEX-Projektziele.",
                        spanish="Validación de seguridad concedida por el propietario para objetivos de proyectos AIONEX autorizados.",
                        turkish="Yetkili AIONEX proje hedefleri için sahip tarafından verilen güvenlik doğrulaması.",
                    ),
                    noindex=True,
                ),
            ),
            "profile": PortalPage(
                slug="profile",
                navigation_label=_localized("Profile", "الحساب"),
                sections=[],
                seo=PortalSEO(
                    title=_localized("Account settings", "إعدادات الحساب"),
                    description=_localized(
                        "Manage account and security settings.",
                        "إدارة إعدادات الحساب والأمان.",
                    ),
                    noindex=True,
                ),
            ),
        },
        pricing=PortalPricingCatalogue(
            enabled=True,
            heading=_localized(
                "Plans built for controlled growth", "خطط مصممة للنمو المنضبط"
            ),
            description=_localized(
                "The owner controls every price, period, feature, limit, and checkout route.",
                "يتحكم المالك في كل سعر ومدة وميزة وحد ومسار دفع.",
            ),
            tax_note=_localized(
                "Taxes and payment availability depend on the selected provider and country.",
                "تعتمد الضرائب وإتاحة الدفع على المزود والدولة المختارة.",
            ),
            plans=[PortalPricingPlan.model_validate(item) for item in pricing_plans],
            faq=[
                {
                    "question": _localized("Can plans change?", "هل يمكن تغيير الخطط؟"),
                    "answer": _localized(
                        "Yes. Published prices, durations, features, and visibility are controlled by the Super Owner.",
                        "نعم. يتحكم المالك الأعلى في الأسعار والمدد والمزايا والظهور المنشور.",
                    ),
                }
            ],
        ),
        footer=PortalFooter(
            description=_localized(
                "Governed AI project execution with transparent controls and evidence.",
                "تنفيذ مشروعات ذكية بضوابط وأدلة واضحة.",
            ),
            security_note=_localized("Protected public portal", "بوابة عامة محمية"),
            copyright_text=_localized("All rights reserved.", "جميع الحقوق محفوظة."),
            columns=[
                PortalFooterColumn(
                    id="platform",
                    title=_localized("Platform", "المنصة"),
                    links=[
                        PortalNavigationItem(
                            id="footer-about",
                            href="/about",
                            label=_localized("About", "عن المنصة"),
                        ),
                        PortalNavigationItem(
                            id="footer-pricing",
                            href="/pricing",
                            label=_localized("Pricing", "الأسعار"),
                        ),
                        PortalNavigationItem(
                            id="footer-contact",
                            href="/contact",
                            label=_localized("Contact", "تواصل معنا"),
                        ),
                    ],
                ),
                PortalFooterColumn(
                    id="legal",
                    title=_localized("Legal", "قانوني"),
                    links=[
                        PortalNavigationItem(
                            id="footer-privacy",
                            href="/legal/privacy",
                            label=_localized("Privacy", "الخصوصية"),
                        ),
                        PortalNavigationItem(
                            id="footer-terms",
                            href="/legal/terms",
                            label=_localized("Terms", "الشروط"),
                        ),
                    ],
                ),
            ],
        ),
    )
    return configuration.model_dump(mode="json")


def validate_portal_configuration(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        configuration = PortalConfiguration.model_validate(payload)
    except Exception as exc:
        raise PortalConfigurationError(str(exc)) from exc
    return configuration.model_dump(mode="json")


def _now() -> datetime:
    return datetime.now(UTC)


def _published_payload(
    configuration: dict[str, Any], version: int, actor_id: str
) -> dict[str, Any]:
    return {
        "configuration": deepcopy(configuration),
        "publication": {
            "version": version,
            "published_at": _now().isoformat(),
            "published_by": actor_id,
        },
    }


async def _get_record(
    session: AsyncSession,
    resource_id: str,
    *,
    lock: bool = False,
) -> OwnerControlRecord | None:
    statement = select(OwnerControlRecord).where(
        OwnerControlRecord.domain == PORTAL_DOMAIN,
        OwnerControlRecord.resource_id == resource_id,
    )
    if lock:
        statement = statement.with_for_update()
    return await session.scalar(statement)


async def ensure_portal_records(
    session: AsyncSession,
) -> tuple[OwnerControlRecord, OwnerControlRecord]:
    configuration = default_portal_configuration()
    now = _now()
    await session.execute(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=PORTAL_DOMAIN,
            resource_id=DRAFT_RESOURCE,
            status="draft",
            enabled=True,
            payload={"configuration": configuration},
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
    )
    await session.execute(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=PORTAL_DOMAIN,
            resource_id=PUBLISHED_RESOURCE,
            status="published",
            enabled=True,
            payload=_published_payload(configuration, 1, "system-bootstrap"),
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
    )
    draft = await _get_record(session, DRAFT_RESOURCE)
    published = await _get_record(session, PUBLISHED_RESOURCE)
    if draft is None or published is None:
        raise RuntimeError("portal CMS records could not be initialized")
    return draft, published


def _record_snapshot(record: OwnerControlRecord) -> dict[str, Any]:
    return {
        "resource_id": record.resource_id,
        "status": record.status,
        "enabled": record.enabled,
        "record_version": record.version,
        "updated_at": record.updated_at.isoformat() if record.updated_at else None,
        **dict(record.payload or {}),
    }


async def get_portal_snapshot(session: AsyncSession) -> dict[str, Any]:
    draft, published = await ensure_portal_records(session)
    history = await list_portal_history(session)
    assets = await list_portal_assets(session)
    return {
        "draft": _record_snapshot(draft),
        "published": _record_snapshot(published),
        "history": history,
        "assets": assets,
        "supported_locales": list(SUPPORTED_LOCALES),
        "limits": {
            "configuration_bytes": MAX_CONFIGURATION_BYTES,
            "asset_bytes": settings.PORTAL_ASSET_MAX_BYTES,
            "history_entries": MAX_HISTORY,
        },
    }


async def get_published_portal(session: AsyncSession) -> dict[str, Any]:
    _, published = await ensure_portal_records(session)
    payload = dict(published.payload or {})
    configuration = validate_portal_configuration(
        dict(payload.get("configuration") or {})
    )
    publication = dict(payload.get("publication") or {})
    return {
        "configuration": configuration,
        "publication": publication,
        "etag": hashlib.sha256(
            json.dumps(
                {"configuration": configuration, "publication": publication},
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest(),
    }


async def replace_portal_draft(
    session: AsyncSession,
    configuration: dict[str, Any],
    *,
    actor_id: str,
    organization_id: str | None,
) -> dict[str, Any]:
    normalized = validate_portal_configuration(configuration)
    await ensure_portal_records(session)
    draft = await _get_record(session, DRAFT_RESOURCE, lock=True)
    assert draft is not None
    draft.payload = {
        "configuration": normalized,
        "draft_metadata": {
            "updated_at": _now().isoformat(),
            "updated_by": actor_id,
        },
    }
    draft.version += 1
    draft.status = "draft"
    draft.enabled = True
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.portal.draft_updated",
            resource_type="portal_configuration",
            resource_id=DRAFT_RESOURCE,
            details={
                "record_version": draft.version,
                "configuration_sha256": hashlib.sha256(
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True).encode(
                        "utf-8"
                    )
                ).hexdigest(),
            },
        )
    )
    await session.flush()
    return _record_snapshot(draft)


async def _archive_published(
    session: AsyncSession,
    published: OwnerControlRecord,
) -> None:
    payload = dict(published.payload or {})
    publication = dict(payload.get("publication") or {})
    version = int(publication.get("version") or published.version or 1)
    await session.execute(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=PORTAL_DOMAIN,
            resource_id=f"{HISTORY_PREFIX}{version:06d}",
            status="archived",
            enabled=False,
            payload=payload,
            version=version,
            created_at=_now(),
            updated_at=_now(),
        )
        .on_conflict_do_nothing(constraint="uq_owner_control_domain_resource")
    )
    stale_ids = list(
        (
            await session.scalars(
                select(OwnerControlRecord.id)
                .where(
                    OwnerControlRecord.domain == PORTAL_DOMAIN,
                    OwnerControlRecord.resource_id.like(f"{HISTORY_PREFIX}%"),
                )
                .order_by(OwnerControlRecord.version.desc())
                .offset(MAX_HISTORY)
            )
        ).all()
    )
    if stale_ids:
        await session.execute(
            delete(OwnerControlRecord).where(OwnerControlRecord.id.in_(stale_ids))
        )


async def publish_portal_draft(
    session: AsyncSession,
    *,
    actor_id: str,
    organization_id: str | None,
) -> dict[str, Any]:
    await ensure_portal_records(session)
    draft = await _get_record(session, DRAFT_RESOURCE, lock=True)
    published = await _get_record(session, PUBLISHED_RESOURCE, lock=True)
    assert draft is not None and published is not None
    normalized = validate_portal_configuration(
        dict((draft.payload or {}).get("configuration") or {})
    )
    await _archive_published(session, published)
    current_publication = dict((published.payload or {}).get("publication") or {})
    next_version = int(current_publication.get("version") or published.version or 0) + 1
    published.payload = _published_payload(normalized, next_version, actor_id)
    published.version = next_version
    published.status = "published"
    published.enabled = True
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.portal.published",
            resource_type="portal_configuration",
            resource_id=PUBLISHED_RESOURCE,
            details={"publication_version": next_version},
        )
    )
    await session.flush()
    return _record_snapshot(published)


async def reset_portal_draft(
    session: AsyncSession,
    *,
    actor_id: str,
    organization_id: str | None,
) -> dict[str, Any]:
    return await replace_portal_draft(
        session,
        default_portal_configuration(),
        actor_id=actor_id,
        organization_id=organization_id,
    )


async def list_portal_history(session: AsyncSession) -> list[dict[str, Any]]:
    rows = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(
                    OwnerControlRecord.domain == PORTAL_DOMAIN,
                    OwnerControlRecord.resource_id.like(f"{HISTORY_PREFIX}%"),
                )
                .order_by(OwnerControlRecord.version.desc())
                .limit(MAX_HISTORY)
            )
        ).all()
    )
    return [
        {
            "version": int(
                (row.payload or {}).get("publication", {}).get("version") or row.version
            ),
            "resource_id": row.resource_id,
            "published_at": (row.payload or {})
            .get("publication", {})
            .get("published_at"),
            "published_by": (row.payload or {})
            .get("publication", {})
            .get("published_by"),
            "configuration": (row.payload or {}).get("configuration"),
        }
        for row in rows
    ]


async def rollback_portal_publication(
    session: AsyncSession,
    version: int,
    *,
    actor_id: str,
    organization_id: str | None,
) -> dict[str, Any]:
    if version < 1:
        raise HTTPException(status_code=422, detail="Portal version must be positive")
    history = await _get_record(session, f"{HISTORY_PREFIX}{version:06d}", lock=True)
    if history is None:
        raise HTTPException(status_code=404, detail="Portal history version not found")
    configuration = validate_portal_configuration(
        dict((history.payload or {}).get("configuration") or {})
    )
    await replace_portal_draft(
        session,
        configuration,
        actor_id=actor_id,
        organization_id=organization_id,
    )
    result = await publish_portal_draft(
        session,
        actor_id=actor_id,
        organization_id=organization_id,
    )
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.portal.rolled_back",
            resource_type="portal_configuration",
            resource_id=PUBLISHED_RESOURCE,
            details={
                "source_version": version,
                "new_version": result.get("publication", {}).get("version"),
            },
        )
    )
    await session.flush()
    return result


def _asset_root() -> Path:
    raw = Path(settings.PORTAL_ASSET_ROOT)
    if not raw.is_absolute():
        raise RuntimeError("PORTAL_ASSET_ROOT must be absolute")
    raw.mkdir(parents=True, exist_ok=True, mode=0o750)
    return raw.resolve(strict=True)


def _detect_asset(data: bytes, content_type: str) -> tuple[str, str]:
    normalized_type = content_type.split(";", 1)[0].strip().lower()
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png", "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg", "image/jpeg"
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    if data.startswith(b"\x00\x00\x01\x00"):
        return "ico", "image/x-icon"
    if data.startswith(b"wOF2"):
        return "woff2", "font/woff2"
    if normalized_type == "image/svg+xml" or data.lstrip().startswith(b"<svg"):
        _validate_svg(data)
        return "svg", "image/svg+xml"
    raise HTTPException(
        status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
        detail="Supported portal assets are PNG, JPEG, WebP, ICO, SVG, and WOFF2",
    )


def _validate_svg(data: bytes) -> None:
    if len(data) > settings.PORTAL_ASSET_MAX_BYTES:
        raise HTTPException(
            status_code=413, detail="Portal asset exceeds the configured limit"
        )
    try:
        text = data.decode("utf-8")
        root = ET.fromstring(text)
    except (UnicodeDecodeError, ET.ParseError) as exc:
        raise HTTPException(status_code=422, detail="SVG is invalid") from exc
    allowed_tags = {
        "svg",
        "g",
        "defs",
        "title",
        "desc",
        "description",
        "path",
        "circle",
        "ellipse",
        "rect",
        "line",
        "polyline",
        "polygon",
        "linearGradient",
        "radialGradient",
        "stop",
        "clipPath",
        "mask",
    }
    for element in root.iter():
        tag = element.tag.rsplit("}", 1)[-1]
        if tag not in allowed_tags:
            raise HTTPException(
                status_code=422, detail=f"SVG element is not allowed: {tag}"
            )
        for attribute, value in element.attrib.items():
            name = attribute.rsplit("}", 1)[-1].lower()
            lowered = str(value).lower()
            if name.startswith("on") or name in {"href", "xlink:href", "style"}:
                raise HTTPException(
                    status_code=422, detail="SVG contains an unsafe attribute"
                )
            if (
                "javascript:" in lowered
                or "data:text/html" in lowered
                or "url(http" in lowered
            ):
                raise HTTPException(
                    status_code=422, detail="SVG contains an unsafe reference"
                )


async def save_portal_asset(
    session: AsyncSession,
    upload: UploadFile,
    *,
    actor_id: str,
    organization_id: str | None,
) -> dict[str, Any]:
    data = await upload.read(settings.PORTAL_ASSET_MAX_BYTES + 1)
    if not data:
        raise HTTPException(status_code=422, detail="Portal asset is empty")
    if len(data) > settings.PORTAL_ASSET_MAX_BYTES:
        raise HTTPException(
            status_code=413, detail="Portal asset exceeds the configured limit"
        )
    extension, media_type = _detect_asset(data, upload.content_type or "")
    digest = hashlib.sha256(data).hexdigest()
    asset_id = digest[:32]
    root = _asset_root()
    directory = root / asset_id[:2]
    directory.mkdir(parents=True, exist_ok=True, mode=0o750)
    destination = directory / f"{asset_id}.{extension}"
    if not destination.exists():
        temporary = directory / f".{asset_id}.{os.getpid()}.tmp"
        with temporary.open("xb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, 0o640)
        os.replace(temporary, destination)
    original_name = Path(upload.filename or f"asset.{extension}").name[:240]
    payload = {
        "asset_id": asset_id,
        "filename": original_name,
        "extension": extension,
        "media_type": media_type,
        "size_bytes": len(data),
        "sha256": digest,
        "path": str(destination),
        "public_url": f"{settings.PORTAL_PUBLIC_API_ORIGIN.rstrip('/')}/api/v1/portal/assets/{asset_id}",
        "uploaded_at": _now().isoformat(),
        "uploaded_by": actor_id,
    }
    now = _now()
    await session.execute(
        pg_insert(OwnerControlRecord)
        .values(
            id=uuid_str(),
            domain=ASSET_DOMAIN,
            resource_id=asset_id,
            status="active",
            enabled=True,
            payload=payload,
            version=1,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            constraint="uq_owner_control_domain_resource",
            set_={
                "payload": payload,
                "status": "active",
                "enabled": True,
                "updated_at": now,
            },
        )
    )
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.portal.asset_uploaded",
            resource_type="portal_asset",
            resource_id=asset_id,
            details={
                "media_type": media_type,
                "size_bytes": len(data),
                "sha256": digest,
            },
        )
    )
    await session.flush()
    return payload


async def list_portal_assets(session: AsyncSession) -> list[dict[str, Any]]:
    records = list(
        (
            await session.scalars(
                select(OwnerControlRecord)
                .where(OwnerControlRecord.domain == ASSET_DOMAIN)
                .order_by(OwnerControlRecord.updated_at.desc())
                .limit(1000)
            )
        ).all()
    )
    return [dict(record.payload or {}) for record in records if record.enabled]


async def get_portal_asset(session: AsyncSession, asset_id: str) -> dict[str, Any]:
    if not re.fullmatch(r"[0-9a-f]{32}", asset_id):
        raise HTTPException(status_code=404, detail="Portal asset not found")
    record = await session.scalar(
        select(OwnerControlRecord).where(
            OwnerControlRecord.domain == ASSET_DOMAIN,
            OwnerControlRecord.resource_id == asset_id,
            OwnerControlRecord.enabled.is_(True),
        )
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Portal asset not found")
    payload = dict(record.payload or {})
    path = Path(str(payload.get("path") or ""))
    root = _asset_root()
    try:
        resolved = path.resolve(strict=True)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=404, detail="Portal asset file not found"
        ) from exc
    if root not in resolved.parents or not resolved.is_file() or resolved.is_symlink():
        raise HTTPException(status_code=404, detail="Portal asset path is invalid")
    payload["resolved_path"] = str(resolved)
    return payload


async def delete_portal_asset(
    session: AsyncSession,
    asset_id: str,
    *,
    actor_id: str,
    organization_id: str | None,
) -> None:
    asset = await get_portal_asset(session, asset_id)
    draft, published = await ensure_portal_records(session)
    public_url = str(asset["public_url"])
    combined = json.dumps(
        {"draft": draft.payload, "published": published.payload},
        ensure_ascii=False,
        sort_keys=True,
    )
    if public_url in combined:
        raise HTTPException(
            status_code=409,
            detail="Portal asset is referenced by draft or published configuration",
        )
    record = await session.scalar(
        select(OwnerControlRecord)
        .where(
            OwnerControlRecord.domain == ASSET_DOMAIN,
            OwnerControlRecord.resource_id == asset_id,
        )
        .with_for_update()
    )
    if record is None:
        raise HTTPException(status_code=404, detail="Portal asset not found")
    record.enabled = False
    record.status = "deleted"
    Path(str(asset["resolved_path"])).unlink(missing_ok=True)
    session.add(
        AuditEvent(
            organization_id=organization_id,
            user_id=actor_id,
            action="owner.portal.asset_deleted",
            resource_type="portal_asset",
            resource_id=asset_id,
            details={"sha256": asset.get("sha256")},
        )
    )
    await session.flush()
