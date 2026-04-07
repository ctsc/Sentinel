"""
Named Entity Recognition — extracts GPE/LOC entities from unstructured text.

Only used for unstructured sources (RSS, Bluesky, Wikipedia).
GDELT/ACLED already have coordinates — they skip NER entirely.
"""

import logging
from typing import List

logger = logging.getLogger(__name__)

_nlp = None


def _load_model():
    """Lazy-load spaCy model to avoid startup cost if not needed."""
    global _nlp
    if _nlp is None:
        import spacy
        try:
            _nlp = spacy.load("en_core_web_lg", disable=["lemmatizer", "textcat"])
        except OSError:
            logger.warning("en_core_web_lg not found, falling back to en_core_web_sm")
            try:
                _nlp = spacy.load("en_core_web_sm", disable=["lemmatizer", "textcat"])
            except OSError:
                logger.error("No spaCy model found. Install with: python -m spacy download en_core_web_lg")
                raise
    return _nlp


def extract_locations(text: str) -> List[str]:
    """
    Extract GPE (geopolitical entity) and LOC (location) entities from text.

    Returns a deduplicated list of location strings.
    """
    if not text or not text.strip():
        return []

    nlp = _load_model()

    # Truncate very long texts to avoid slow processing
    max_chars = 5000
    if len(text) > max_chars:
        text = text[:max_chars]

    doc = nlp(text)

    locations = []
    seen = set()
    for ent in doc.ents:
        if ent.label_ in ("GPE", "LOC"):
            name = ent.text.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                locations.append(name)

    return locations
