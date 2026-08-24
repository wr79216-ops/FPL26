"""Presentation-safe text helpers for searchable player names."""

from __future__ import annotations

import unicodedata


SPECIAL_CHARACTER_TRANSLATIONS = str.maketrans(
    {
        "Ø": "O",
        "ø": "o",
        "Đ": "D",
        "đ": "d",
        "Ð": "D",
        "ð": "d",
        "Ł": "L",
        "ł": "l",
        "Æ": "AE",
        "æ": "ae",
        "Œ": "OE",
        "œ": "oe",
        "Þ": "Th",
        "þ": "th",
        "ß": "ss",
    }
)


def normalize_display_name(value: str) -> str:
    """Make an official name easy to type while preserving normal word spacing."""
    translated = value.translate(SPECIAL_CHARACTER_TRANSLATIONS)
    decomposed = unicodedata.normalize("NFKD", translated)
    return "".join(character for character in decomposed if not unicodedata.combining(character))
