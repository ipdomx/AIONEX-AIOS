from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
LOCALE_ENGINE = ROOT / "web-dashboard/frontend/src/lib/locale-engine.ts"
VOICE_PROVIDER = (
    ROOT
    / "web-dashboard/frontend/src/components/providers/LanguageVoiceProvider.tsx"
)
CONTROLS = (
    ROOT
    / "web-dashboard/frontend/src/components/accessibility/LanguageVoiceControls.tsx"
)
LAYOUT = ROOT / "web-dashboard/frontend/src/app/layout.tsx"
TRANSLATIONS = ROOT / "web-dashboard/frontend/src/lib/interface-translations.ts"


def test_locale_priority_is_user_first_and_ip_is_only_fallback():
    source = LOCALE_ENGINE.read_text(encoding="utf-8")
    explicit = source.index('"explicit"')
    account = source.index('"account"')
    browser = source.index('"browser"')
    phone = source.index('"phone-country"')
    ip = source.index('"ip-country"')
    assert explicit < account < browser < phone < ip
    assert 'return finish("en-US", "fallback"' in source


def test_arabic_dialects_and_rtl_are_first_class():
    source = LOCALE_ENGINE.read_text(encoding="utf-8")
    for dialect in (
        "egyptian",
        "gulf",
        "saudi",
        "levantine",
        "iraqi",
        "maghrebi",
    ):
        assert dialect in source
    assert 'direction: "ltr" | "rtl"' in source
    assert "detectArabicDialect" in source


def test_voice_input_output_and_live_interface_controls_are_wired():
    provider = VOICE_PROVIDER.read_text(encoding="utf-8")
    controls = CONTROLS.read_text(encoding="utf-8")
    layout = LAYOUT.read_text(encoding="utf-8")
    assert "SpeechRecognition" in provider
    assert "webkitSpeechRecognition" in provider
    assert "SpeechSynthesisUtterance" in provider
    assert "aionex:voice-transcript" in provider
    assert "MutationObserver" in provider
    assert "LanguageVoiceProvider" in layout
    assert "Interface language" in controls
    assert "Arabic dialect" in controls


def test_translation_catalog_covers_core_live_registration_and_projects():
    source = TRANSLATIONS.read_text(encoding="utf-8")
    for phrase in (
        '"Sign in"',
        '"Create a free account"',
        '"Mobile verification"',
        '"Send code"',
        '"Projects"',
        '"New Project"',
        '"Create Project"',
    ):
        assert phrase in source
    for locale_marker in ("const AR", "const FR", "const ES", "const DE", "const TR", "const ZH", "const HI", "const UR"):
        assert locale_marker in source
