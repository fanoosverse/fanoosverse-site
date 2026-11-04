"""
Module: /core/normalizer/unify.py
Description: Character unification and version-suffix stripping applied before vocabulary matching.
"""
from __future__ import annotations

import re
import unicodedata

_DIGIT_TRANSLATION = str.maketrans(
    "۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩",
    "01234567890123456789",
)

_LETTER_TRANSLATION = str.maketrans(
    {
        "\u064a": "\u06cc",  # arabic yeh -> farsi yeh
        "\u0649": "\u06cc",  # alef maksura -> farsi yeh
        "\u0643": "\u06a9",  # arabic kaf -> keheh
        "\u0623": "\u0627",  # alef with hamza -> alef
        "\u0625": "\u0627",  # alef with hamza below -> alef
        "\u0622": "\u0627",  # alef with madda -> alef
        "\u0671": "\u0627",  # alef wasla -> alef
        "\u0629": "\u0647",  # teh marbuta -> heh
        "\u0640": "",        # tatweel
        "\u064b": "",        # fathatan
        "\u064c": "",        # dammatan
        "\u064d": "",        # kasratan
        "\u064e": "",        # fatha
        "\u064f": "",        # damma
        "\u0650": "",        # kasra
        "\u0651": "",        # shadda
        "\u0652": "",        # sukun
        "\u066b": ".",       # arabic decimal separator
        "\u066c": "",        # arabic thousands separator
        "\u200c": " ",       # ZWNJ -> space
        "\u200e": "",        # LRM
        "\u200f": "",        # RLM
        "\u061c": "",        # ALM
        "\ufeff": "",        # BOM
    }
)

_WHITESPACE_RE = re.compile(r"\s+")
_PAREN_OR_VERSION_RE = re.compile(
    r"(\s*\([^)]*\)|\s+v?\d+(?:\.\d+)*(?:\+)?)$",
    re.IGNORECASE,
)

PLACEHOLDERS = {
    "", "n/a", "na", "none", "null", "unknown", "unspecified",
    "-", "—", "ندارد", "نامشخص", "توافقی",
}


def unify_text(value: str) -> str:
    """Return the unified matching form of `value`."""
    normalized = unicodedata.normalize("NFC", value)
    normalized = normalized.translate(_DIGIT_TRANSLATION).translate(_LETTER_TRANSLATION)
    return _WHITESPACE_RE.sub(" ", normalized).strip()


def unify_key(value: str) -> str:
    """Unified + case-folded + quote-stripped key for vocabulary lookups."""
    unified = unify_text(value).casefold()
    return unified.strip(" \t\"'`").strip()


def strip_version_and_parens(raw: str) -> tuple[str, str | None]:
    """
    Strips trailing version numbers or parenthetical remarks (e.g. 'PyTorch (نسخه ۲)' -> 'PyTorch').
    Returns (cleaned_base, removed_part_or_None).
    """
    cleaned = unify_text(raw)
    match = _PAREN_OR_VERSION_RE.search(cleaned)
    if match:
        base = cleaned[: match.start()].strip()
        removed = match.group(0).strip()
        if base:
            return base, removed
    return cleaned, None


def is_placeholder(value: str) -> bool:
    return unify_key(value) in PLACEHOLDERS