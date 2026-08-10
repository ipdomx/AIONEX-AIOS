"""Static Android/iOS security posture checks for managed project artifacts."""

from __future__ import annotations

import hashlib
import plistlib
from pathlib import Path
from typing import Any
from xml.etree import ElementTree

ANDROID_NS = "{http://schemas.android.com/apk/res/android}"


def _finding(
    marker: str,
    title: str,
    severity: str,
    evidence: dict[str, Any],
    remediation: str,
    *,
    cwe: str = "CWE-693",
) -> dict[str, Any]:
    return {
        "source": "aionex-mobile",
        "category": "mobile-security",
        "title": title,
        "severity": severity,
        "confidence": 0.9,
        "state": "observed",
        "fingerprint": hashlib.sha256(
            f"mobile|{marker}|{sorted(evidence.items())}".encode()
        ).hexdigest(),
        "cwe": cwe,
        "owasp": "OWASP-MASVS",
        "location": None,
        "evidence": evidence,
        "remediation": remediation,
    }


def analyze_android_manifest(xml_text: str) -> list[dict[str, Any]]:
    root = ElementTree.fromstring(xml_text)
    app = root.find("application")
    if app is None:
        return []
    findings: list[dict[str, Any]] = []
    if app.get(ANDROID_NS + "debuggable") == "true":
        findings.append(
            _finding(
                "android-debuggable",
                "Android application is debuggable",
                "high",
                {"debuggable": True},
                "Disable android:debuggable in production builds.",
            )
        )
    if app.get(ANDROID_NS + "usesCleartextTraffic") == "true":
        findings.append(
            _finding(
                "android-cleartext",
                "Android application permits cleartext traffic",
                "high",
                {"usesCleartextTraffic": True},
                "Disable cleartext traffic and use scoped network security configuration only where unavoidable.",
                cwe="CWE-319",
            )
        )
    if app.get(ANDROID_NS + "allowBackup") == "true":
        findings.append(
            _finding(
                "android-backup",
                "Android application allows platform backup",
                "medium",
                {"allowBackup": True},
                "Disable backups for sensitive applications or configure explicit data extraction rules.",
            )
        )
    for component in ("activity", "activity-alias", "service", "receiver", "provider"):
        for node in app.findall(component):
            exported = node.get(ANDROID_NS + "exported")
            name = node.get(ANDROID_NS + "name") or component
            if exported == "true" and not node.get(ANDROID_NS + "permission"):
                findings.append(
                    _finding(
                        f"android-exported-{component}-{name}",
                        "Exported Android component has no component permission",
                        "medium",
                        {"component": component, "name": name},
                        "Restrict exported components and require an appropriate permission or authenticated application-level gate.",
                    )
                )
    return findings


def analyze_ios_plist(data: bytes) -> list[dict[str, Any]]:
    payload = plistlib.loads(data)
    findings: list[dict[str, Any]] = []
    ats = payload.get("NSAppTransportSecurity") or {}
    if isinstance(ats, dict) and ats.get("NSAllowsArbitraryLoads") is True:
        findings.append(
            _finding(
                "ios-ats-arbitrary",
                "iOS App Transport Security allows arbitrary loads",
                "high",
                {"NSAllowsArbitraryLoads": True},
                "Remove NSAllowsArbitraryLoads and define only narrowly scoped transport exceptions.",
                cwe="CWE-319",
            )
        )
    if payload.get("UIFileSharingEnabled") is True:
        findings.append(
            _finding(
                "ios-file-sharing",
                "iOS file sharing is enabled",
                "medium",
                {"UIFileSharingEnabled": True},
                "Disable file sharing unless the product explicitly requires user-visible document exchange.",
            )
        )
    if payload.get("LSSupportsOpeningDocumentsInPlace") is True:
        findings.append(
            _finding(
                "ios-documents-in-place",
                "iOS documents-in-place access is enabled",
                "low",
                {"LSSupportsOpeningDocumentsInPlace": True},
                "Confirm in-place document access is required and sensitive files are excluded.",
            )
        )
    return findings


def scan_mobile_source(root: Path) -> dict[str, Any]:
    root = root.resolve(strict=True)
    findings: list[dict[str, Any]] = []
    android = list(root.rglob("AndroidManifest.xml"))[:20]
    for path in android:
        try:
            findings.extend(analyze_android_manifest(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeError, ElementTree.ParseError):
            continue
    plists = [
        path
        for path in root.rglob("*.plist")
        if path.name in {"Info.plist", "Runner-Info.plist"}
    ][:20]
    for path in plists:
        try:
            findings.extend(analyze_ios_plist(path.read_bytes()))
        except (OSError, ValueError, plistlib.InvalidFileException):
            continue
    return {
        "scanner": "aionex-mobile-v1",
        "android_manifests": len(android),
        "ios_plists": len(plists),
        "findings": findings,
    }
