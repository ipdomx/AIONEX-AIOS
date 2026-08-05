from __future__ import annotations

import json
from pathlib import Path

from aios.ios import IOSRelease, IOSReleaseManager, IOSReleaseStage
from aios.ios_app import IOSDevice, IOSDeviceRegistry
from aios.mobile.android import AndroidRelease, AndroidReleaseManager, ReleaseChannel
from aios.telegram_bot import TelegramIdentityService, TelegramWebhookService

ROOT = Path(__file__).resolve().parents[1]


def test_mobile_and_telegram_packages_live_under_the_installed_src_tree() -> None:
    expected = (
        ROOT / "src/aios/ios",
        ROOT / "src/aios/ios_app",
        ROOT / "src/aios/mobile/android",
        ROOT / "src/aios/telegram_bot",
    )
    assert all(path.is_dir() for path in expected)
    assert not (ROOT / "aios/ios").exists()
    assert not (ROOT / "aios/ios_app").exists()
    assert not (ROOT / "aios/mobile/android").exists()
    assert not (ROOT / "aios/telegram_bot").exists()


def test_existing_mobile_release_and_security_contracts_remain_importable() -> None:
    android = AndroidReleaseManager()
    internal = android.publish(
        AndroidRelease("1.0.0", 1, "a" * 64, ReleaseChannel.INTERNAL)
    )
    beta = android.promote(internal.version_code, ReleaseChannel.BETA)
    assert beta.channel is ReleaseChannel.BETA

    ios = IOSReleaseManager()
    ios.create(IOSRelease("ios-1", "1.0.0", 1))
    assert ios.promote("ios-1", IOSReleaseStage.TESTFLIGHT).stage is IOSReleaseStage.TESTFLIGHT

    registry = IOSDeviceRegistry()
    registry.register(IOSDevice("device-1", "owner-1", "apns", "1.0.0", "18"))
    assert len(registry.active_for_owner("owner-1")) == 1

    identities = TelegramIdentityService()
    link = identities.issue_link_token("owner-1")
    assert identities.link(token=link.token, telegram_user_id="100").active is True
    webhook = TelegramWebhookService(secret_token="0123456789abcdef")
    assert webhook.verify("0123456789abcdef") is True


def test_android_release_source_is_remote_first_and_offline_safe() -> None:
    main_activity = (
        ROOT / "mobile/android/app/src/main/java/net/vipe/aionex/MainActivity.java"
    ).read_text(encoding="utf-8")
    manifest = (ROOT / "mobile/android/app/src/main/AndroidManifest.xml").read_text(
        encoding="utf-8"
    )
    gradle = (ROOT / "mobile/android/app/build.gradle").read_text(encoding="utf-8")
    build_script = (ROOT / "scripts/mobile/build_android.sh").read_text(
        encoding="utf-8"
    )
    ignore = (ROOT / "mobile/android/.gitignore").read_text(encoding="utf-8")

    assert 'PORTAL_URL = "https://" + PORTAL_HOST + "/ar/"' in main_activity
    assert 'PORTAL_HOST = "ai.vip-e.net"' in main_activity
    assert 'OFFLINE_URL = "https://" + ASSET_HOST + "/offline.html"' in main_activity
    assert "setAllowFileAccess(false)" in main_activity
    assert "MIXED_CONTENT_NEVER_ALLOW" in main_activity
    assert 'android:usesCleartextTraffic="false"' in manifest
    assert 'android:host="ai.vip-e.net"' in manifest
    assert "minSdk 27" in gradle and "targetSdk 36" in gradle
    assert "AIOS_ANDROID_KEYSTORE_FILE" in build_script
    assert "/root/.config/aionex/mobile/android-release.jks" in build_script
    assert "**/build/" in ignore and "generated-web/" in ignore


def test_ios_source_package_is_xcode_ready_without_committed_signing_material() -> None:
    project = (ROOT / "mobile/ios/project.yml").read_text(encoding="utf-8")
    portal = (ROOT / "mobile/ios/AIONEXAIOS/PortalView.swift").read_text(
        encoding="utf-8"
    )
    entitlements = (
        ROOT / "mobile/ios/AIONEXAIOS/AIONEXAIOS.entitlements"
    ).read_text(encoding="utf-8")
    assert "PRODUCT_BUNDLE_IDENTIFIER: net.vipe.aionex" in project
    assert 'URL(string: "https://ai.vip-e.net/ar/")' in portal
    assert "WKWebView" in portal
    assert "applinks:ai.vip-e.net" in entitlements
    assert not list((ROOT / "mobile/ios").rglob("*.p12"))
    assert not list((ROOT / "mobile/ios").rglob("*.mobileprovision"))


def test_pwa_manifest_service_worker_and_icons_are_delivery_ready() -> None:
    manifest = json.loads(
        (ROOT / "vip-frontend/public/manifest.webmanifest").read_text(encoding="utf-8")
    )
    service_worker = (ROOT / "vip-frontend/public/sw.js").read_text(encoding="utf-8")
    layout = (ROOT / "vip-frontend/src/app/[locale]/layout.tsx").read_text(
        encoding="utf-8"
    )
    assert manifest["display"] == "standalone"
    assert manifest["start_url"] == "/ar/"
    assert {item["sizes"] for item in manifest["icons"]} >= {"192x192", "512x512"}
    assert (ROOT / "vip-frontend/public/icons/aionex-180.png").is_file()
    assert (ROOT / "vip-frontend/public/icons/aionex-192.png").is_file()
    assert (ROOT / "vip-frontend/public/icons/aionex-512.png").is_file()
    assert 'url.pathname.startsWith("/api/")' in service_worker
    assert "PwaRegister" in layout


def test_telegram_delivery_is_optional_allowlisted_and_secret_file_based() -> None:
    worker = (
        ROOT / "web-dashboard/backend/app/services/telegram_worker.py"
    ).read_text(encoding="utf-8")
    compose = (ROOT / "web-dashboard/docker-compose.production.yml").read_text(
        encoding="utf-8"
    )
    assert "AIOS_TELEGRAM_ALLOWED_USERS" in worker
    assert "AIOS_TELEGRAM_BOT_TOKEN_FILE" in worker
    assert "not-allowlisted" in worker
    assert 'profiles: ["telegram"]' in compose
    assert "/run/secrets/aionex/telegram-bot-token:ro" in compose
    assert "TELEGRAM_BOT_TOKEN=" not in compose
