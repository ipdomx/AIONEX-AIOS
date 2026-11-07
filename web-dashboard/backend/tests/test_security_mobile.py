import plistlib
from app.services.security_mobile import analyze_android_manifest, analyze_ios_plist


def test_android_manifest_flags_debug_cleartext_and_unprotected_export():
    xml = """<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application android:debuggable="true" android:usesCleartextTraffic="true"><activity android:name=".AdminActivity" android:exported="true" /></application></manifest>"""
    titles = {item["title"] for item in analyze_android_manifest(xml)}
    assert "Android application is debuggable" in titles
    assert "Android application permits cleartext traffic" in titles
    assert "Exported Android component has no component permission" in titles


def test_ios_plist_flags_arbitrary_transport_loads():
    body = plistlib.dumps(
        {
            "NSAppTransportSecurity": {"NSAllowsArbitraryLoads": True},
            "UIFileSharingEnabled": True,
        }
    )
    titles = {item["title"] for item in analyze_ios_plist(body)}
    assert "iOS App Transport Security allows arbitrary loads" in titles
    assert "iOS file sharing is enabled" in titles


def test_fr23_android_manifest_refuses_dtd_and_entity_expansion(tmp_path):
    """FR-23 regression: an untrusted manifest cannot use a DTD (XXE / entity bomb)."""

    import pytest
    from defusedxml import DefusedXmlException  # type: ignore[import-untyped]

    from app.services.security_mobile import scan_mobile_source

    bomb = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE manifest [<!ENTITY a "aaaaaaaaaa">'
        '<!ENTITY b "&a;&a;&a;&a;&a;&a;&a;&a;&a;&a;">'
        '<!ENTITY c "&b;&b;&b;&b;&b;&b;&b;&b;&b;&b;">]>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<application android:debuggable="true" android:label="&c;" /></manifest>'
    )
    external = (
        '<?xml version="1.0"?>\n'
        '<!DOCTYPE manifest [<!ENTITY x SYSTEM "file:///etc/passwd">]>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android">'
        '<application android:label="&x;" /></manifest>'
    )
    for document in (bomb, external):
        with pytest.raises(DefusedXmlException):
            analyze_android_manifest(document)

    (tmp_path / "AndroidManifest.xml").write_text(bomb, encoding="utf-8")
    report = scan_mobile_source(tmp_path)
    assert not any(item["title"] == "Android application is debuggable" for item in report["findings"])
