"""
Keyword/rule-based event classifier.

Maps text to: conflict, protest, disaster, political, terrorism, other.

Only used for unstructured sources (RSS, Bluesky, Wikipedia).
GDELT uses CAMEO codes, ACLED uses event_type — both already classified.

Runs in <1ms per event, zero ML dependencies.
"""

import logging
from typing import Tuple

logger = logging.getLogger(__name__)

# Keywords ordered by priority — first match wins.
# More specific categories checked before broader ones.

TERRORISM_KEYWORDS = [
    "terrorist", "terrorism", "isis", "isil", "al-qaeda", "al qaeda",
    "boko haram", "al-shabaab", "al shabaab", "suicide bomb", "car bomb",
    "ied", "improvised explosive", "jihad", "jihadist", "extremist",
    "radicalize", "radicalise", "lone wolf", "hostage",
]

PROTEST_KEYWORDS = [
    "protest", "protester", "protestor", "demonstration", "demonstrator",
    "rally", "march", "uprising", "civil disobedience", "riot", "rioter",
    "unrest", "dissent", "strike action", "general strike",
    "tear gas", "water cannon", "rubber bullet",
]

DISASTER_KEYWORDS = [
    "earthquake", "tsunami", "hurricane", "typhoon", "cyclone", "tornado",
    "flood", "flooding", "wildfire", "forest fire", "bushfire",
    "volcanic", "volcano", "eruption", "landslide", "mudslide",
    "drought", "famine", "pandemic", "epidemic", "outbreak",
]

CONFLICT_KEYWORDS = [
    "war", "warfare", "armed conflict", "military", "troops", "soldiers",
    "airstrike", "air strike", "bombing", "bombard", "shelling", "shell",
    "artillery", "missile", "rocket", "drone strike",
    "invasion", "invade", "offensive", "counteroffensive",
    "battle", "combat", "fighting", "firefight", "clash",
    "kill", "killed", "casualty", "casualties", "fatality", "fatalities",
    "wounded", "injured", "dead", "death toll",
    "siege", "blockade", "ceasefire", "cease-fire", "truce",
    "rebel", "insurgent", "insurgency", "militia", "guerrilla",
    "genocide", "ethnic cleansing", "massacre", "atrocity",
    "weapons", "ammunition", "arms", "warplane", "tank",
    "sniper", "ambush", "raid", "assault",
    "attack", "attacked",
]

POLITICAL_KEYWORDS = [
    "election", "vote", "voting", "ballot", "referendum",
    "coup", "coup d'etat", "martial law", "state of emergency",
    "sanction", "sanctions", "embargo", "diplomat", "diplomacy",
    "treaty", "agreement", "peace deal", "negotiation",
    "parliament", "congress", "senate", "legislation",
    "president", "prime minister", "government",
    "annex", "annexation", "sovereignty", "territorial",
    "nuclear deal", "arms control", "disarmament",
]

# CAMEO event code mapping for GDELT
CAMEO_CONFLICT_PREFIXES = ("18", "19", "20")  # assault, fight, unconventional mass violence
CAMEO_PROTEST_PREFIXES = ("14",)  # protest
CAMEO_POLITICAL_PREFIXES = ("01", "02", "03", "04", "05", "06", "07", "08")

# ACLED event_type mapping
ACLED_TYPE_MAP = {
    "battles": "conflict",
    "violence against civilians": "conflict",
    "explosions/remote violence": "conflict",
    "riots": "protest",
    "protests": "protest",
    "strategic developments": "political",
}


def classify_text(text: str) -> Tuple[str, float]:
    """
    Classify free text into an event type using keyword matching.

    Returns (event_type, confidence) where confidence is 0.0-1.0.
    """
    if not text:
        return "other", 0.1

    text_lower = text.lower()

    # Check categories in priority order
    for keywords, event_type, base_conf in [
        (TERRORISM_KEYWORDS, "terrorism", 0.75),
        (PROTEST_KEYWORDS, "protest", 0.70),
        (DISASTER_KEYWORDS, "disaster", 0.75),
        (CONFLICT_KEYWORDS, "conflict", 0.65),
        (POLITICAL_KEYWORDS, "political", 0.60),
    ]:
        matches = sum(1 for kw in keywords if kw in text_lower)
        if matches > 0:
            # More keyword matches = higher confidence, capped at 0.95
            confidence = min(base_conf + (matches - 1) * 0.05, 0.95)
            return event_type, round(confidence, 2)

    return "other", 0.1


def classify_cameo(event_code: str) -> Tuple[str, float]:
    """Classify a GDELT event using its CAMEO event code."""
    if not event_code:
        return "other", 0.3

    code = str(event_code).strip()

    if code[:2] in CAMEO_CONFLICT_PREFIXES:
        return "conflict", 0.90
    if code[:2] in CAMEO_PROTEST_PREFIXES:
        return "protest", 0.85
    if code[:2] in CAMEO_POLITICAL_PREFIXES:
        return "political", 0.70

    return "other", 0.3


def classify_acled(event_type: str) -> Tuple[str, float]:
    """Classify an ACLED event using its event_type field."""
    if not event_type:
        return "other", 0.3

    mapped = ACLED_TYPE_MAP.get(event_type.lower())
    if mapped:
        return mapped, 0.90

    return "other", 0.3
