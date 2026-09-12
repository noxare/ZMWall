from zmwall.i18n import DE, EN, resolve_language, translate


class AcceptedLanguages:
    def __init__(self, match):
        self.match = match

    def best_match(self, supported, default=None):
        return self.match if self.match in supported else default


def test_explicit_language_overrides_browser_language():
    assert resolve_language("en", AcceptedLanguages("de")) == "en"
    assert resolve_language("de", AcceptedLanguages("en")) == "de"


def test_browser_language_is_default_and_unknown_language_falls_back_to_english():
    assert resolve_language(None, AcceptedLanguages("de")) == "de"
    assert resolve_language(None, AcceptedLanguages("fr")) == "en"


def test_translation_catalogs_have_matching_keys_and_format_values():
    assert set(DE) == set(EN)
    assert translate("de", "cameras_updated", count=3) == "3 Kameras aktualisiert."
    assert translate("en", "cameras_updated", count=3) == "3 cameras updated."
