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
