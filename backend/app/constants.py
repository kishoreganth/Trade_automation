"""
Application-wide constants — single source of truth shared across services,
routers, AI prompts, and exposed via /api/pe_analysis/valuation_options
so the frontend can render dropdowns without hardcoding the list.

Adding / removing a valuation option here is the ONLY place you need to edit.
The DB column `quarterly_results.valuation` is plain TEXT so no migration is
needed when this list changes — the values are stored verbatim.
"""

from typing import Final


# Valuation tone groups — used by report aggregation + sector summary
VALUATION_TONE_BULLISH: Final[str] = "bullish"   # cheap-side
VALUATION_TONE_NEUTRAL: Final[str] = "neutral"   # fair-side
VALUATION_TONE_BEARISH: Final[str] = "bearish"   # expensive-side
VALUATION_TONE_IGNORED: Final[str] = "ignored"   # excluded from rollups


# Canonical valuation options. `value` is what is stored in DB.
# `label` is the human-readable display string.
# `tone` drives semantic grouping (bullish/bearish counts in reports).
# Order is the order shown in the UI dropdown.
VALUATION_OPTIONS: Final[list[dict]] = [
    {"value": "CHEAP",         "label": "Cheap",         "tone": VALUATION_TONE_BULLISH},
    {"value": "UNDER_VALUED",  "label": "Under Valued",  "tone": VALUATION_TONE_BULLISH},
    {"value": "INLINE",        "label": "Inline",        "tone": VALUATION_TONE_NEUTRAL},
    {"value": "FAIRLY_VALUED", "label": "Fairly Valued", "tone": VALUATION_TONE_NEUTRAL},
    {"value": "EXPENSIVE",     "label": "Expensive",     "tone": VALUATION_TONE_BEARISH},
    {"value": "IGNORE",        "label": "Ignore",        "tone": VALUATION_TONE_IGNORED},
]


VALUATION_VALUES: Final[set[str]] = {opt["value"] for opt in VALUATION_OPTIONS}


# Backward-compat: legacy stored values that should still render + count correctly.
# Keys are legacy DB values; values are the canonical option they map to.
VALUATION_LEGACY_ALIASES: Final[dict[str, str]] = {
    "FAIR": "FAIRLY_VALUED",
    "FAIRLY VALUED": "FAIRLY_VALUED",
    "UNDER VALUED": "UNDER_VALUED",
    "UNDERVALUED": "UNDER_VALUED",
    "OVERVALUED": "EXPENSIVE",
    "OVER VALUED": "EXPENSIVE",
    "OVER_VALUED": "EXPENSIVE",
}


def canonicalize_valuation(value: str | None) -> str | None:
    """Normalize a stored valuation value to its canonical form.
    Returns None when value is empty/null. Returns the input as-is for
    unknown non-empty values (tolerated, just not styled by the UI badge)."""
    if not value:
        return None
    v = value.strip().upper()
    if v in VALUATION_VALUES:
        return v
    return VALUATION_LEGACY_ALIASES.get(v, v)


_TONE_BY_VALUE: Final[dict[str, str]] = {opt["value"]: opt["tone"] for opt in VALUATION_OPTIONS}


def valuation_tone(value: str | None) -> str | None:
    """Return the tone group ('bullish' / 'neutral' / 'bearish' / 'ignored') for a value."""
    canon = canonicalize_valuation(value)
    if canon is None:
        return None
    return _TONE_BY_VALUE.get(canon)
