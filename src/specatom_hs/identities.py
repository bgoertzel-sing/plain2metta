"""Shared canonical-identity checks used by validators and backends."""

from __future__ import annotations

import unicodedata


def _is_unicode_noncharacter(character: str) -> bool:
    codepoint = ord(character)
    return 0xFDD0 <= codepoint <= 0xFDEF or codepoint & 0xFFFF in {0xFFFE, 0xFFFF}


def _is_unicode_variation_selector(character: str) -> bool:
    codepoint = ord(character)
    return 0xFE00 <= codepoint <= 0xFE0F or 0xE0100 <= codepoint <= 0xE01EF


def is_canonical_object_subtarget(subtarget: str) -> bool:
    """Return whether ``subtarget`` is a stable, visible Unicode identity."""
    return (
        bool(subtarget)
        and subtarget == subtarget.strip()
        and subtarget == unicodedata.normalize("NFC", subtarget)
        and subtarget == unicodedata.normalize("NFKC", subtarget)
        and not any(
            character.isspace()
            or unicodedata.category(character) in {"Cc", "Cf", "Cn", "Co", "Cs"}
            or unicodedata.category(character).startswith("M")
            or _is_unicode_noncharacter(character)
            or _is_unicode_variation_selector(character)
            for character in subtarget
        )
    )
