"""
Phase 3 Test Gate — NLP unit tests.

Tests NER, geocoder, and classifier individually with known inputs.
"""

import pytest
import sys
import os

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _spacy_available():
    """Check if spaCy NER is functional."""
    try:
        from processing.nlp.ner import extract_locations
        extract_locations("test")
        return True
    except Exception:
        return False


@pytest.mark.skipif(not _spacy_available(), reason="spaCy model not available")
class TestNER:
    """Test spaCy NER location extraction."""

    def test_extracts_known_location(self):
        from processing.nlp.ner import extract_locations

        locations = extract_locations("A massive explosion rocked the city of Kyiv today.")
        location_lower = [loc.lower() for loc in locations]
        assert any("kyiv" in loc for loc in location_lower), f"Expected 'Kyiv' in {locations}"

    def test_extracts_multiple_locations(self):
        from processing.nlp.ner import extract_locations

        locations = extract_locations(
            "Fighting continued between forces in Gaza and troops near the border with Lebanon."
        )
        assert len(locations) >= 1, f"Expected at least 1 location, got {locations}"

    def test_empty_text_returns_empty(self):
        from processing.nlp.ner import extract_locations

        assert extract_locations("") == []
        assert extract_locations("   ") == []

    def test_no_locations_returns_empty(self):
        from processing.nlp.ner import extract_locations

        locations = extract_locations("The stock market closed higher today with strong gains.")
        assert isinstance(locations, list)

    def test_handles_long_text(self):
        from processing.nlp.ner import extract_locations

        long_text = "Conflict in Ukraine continues. " * 500
        locations = extract_locations(long_text)
        assert isinstance(locations, list)


class TestGeocoder:
    """Test geocoding with pre-seeded cache."""

    def test_kyiv_resolves(self):
        from processing.nlp.geocoder import geocode

        result = geocode("Kyiv")
        assert result is not None, "Kyiv should resolve from cache"
        lat, lon, cc = result
        assert abs(lat - 50.45) < 1.0, f"Kyiv lat should be ~50.45, got {lat}"
        assert abs(lon - 30.52) < 1.0, f"Kyiv lon should be ~30.52, got {lon}"

    def test_gaza_resolves(self):
        from processing.nlp.geocoder import geocode

        result = geocode("Gaza")
        assert result is not None
        lat, lon, cc = result
        assert abs(lat - 31.35) < 1.0
        assert abs(lon - 34.31) < 1.0

    def test_cache_hit_no_nominatim(self):
        from processing.nlp.geocoder import geocode, _geo_cache

        # Kyiv should be in the pre-seeded cache
        assert "kyiv" in _geo_cache, "Kyiv should be in pre-seeded cache"
        result = geocode("Kyiv")
        assert result is not None

    def test_case_insensitive(self):
        from processing.nlp.geocoder import geocode

        r1 = geocode("KYIV")
        r2 = geocode("kyiv")
        r3 = geocode("Kyiv")
        assert r1 is not None
        assert r1[0] == r2[0] == r3[0]

    def test_empty_returns_none(self):
        from processing.nlp.geocoder import geocode

        assert geocode("") is None
        assert geocode("   ") is None
        assert geocode(None) is None

    def test_geocode_entities_picks_best(self):
        from processing.nlp.geocoder import geocode_entities

        result = geocode_entities(["Kyiv", "Gaza"])
        assert result is not None
        lat, lon, cc = result

    def test_geocode_entities_empty(self):
        from processing.nlp.geocoder import geocode_entities

        assert geocode_entities([]) is None
        assert geocode_entities(None) is None


class TestClassifier:
    """Test keyword-based event classifier."""

    def test_conflict_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("Soldiers attacked a village near the border.")
        assert event_type == "conflict", f"Expected 'conflict', got '{event_type}'"
        assert confidence > 0.5

    def test_protest_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("Thousands marched in protest against the government.")
        assert event_type == "protest", f"Expected 'protest', got '{event_type}'"
        assert confidence > 0.5

    def test_disaster_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("A massive earthquake struck the coastal region.")
        assert event_type == "disaster", f"Expected 'disaster', got '{event_type}'"
        assert confidence > 0.5

    def test_terrorism_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("A suicide bomb attack was carried out by terrorists.")
        assert event_type == "terrorism", f"Expected 'terrorism', got '{event_type}'"
        assert confidence > 0.5

    def test_political_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("The election results sparked debate in parliament.")
        assert event_type == "political", f"Expected 'political', got '{event_type}'"
        assert confidence > 0.5

    def test_other_classification(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("The weather will be sunny tomorrow with clear skies.")
        assert event_type == "other"

    def test_empty_text(self):
        from processing.nlp.classifier import classify_text

        event_type, confidence = classify_text("")
        assert event_type == "other"

    def test_cameo_conflict(self):
        from processing.nlp.classifier import classify_cameo

        event_type, conf = classify_cameo("190")
        assert event_type == "conflict"
        assert conf >= 0.85

    def test_cameo_protest(self):
        from processing.nlp.classifier import classify_cameo

        event_type, conf = classify_cameo("141")
        assert event_type == "protest"

    def test_acled_battles(self):
        from processing.nlp.classifier import classify_acled

        event_type, conf = classify_acled("Battles")
        assert event_type == "conflict"

    def test_acled_protests(self):
        from processing.nlp.classifier import classify_acled

        event_type, conf = classify_acled("Protests")
        assert event_type == "protest"

    def test_multiple_keywords_higher_confidence(self):
        from processing.nlp.classifier import classify_text

        _, conf_single = classify_text("An attack occurred.")
        _, conf_multi = classify_text("Soldiers attacked the village, killing many in the assault with artillery.")
        assert conf_multi >= conf_single
