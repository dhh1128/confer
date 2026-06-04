"""Tests for the invisible-Unicode / Trojan-Source CI gate (this.i uc7nqx4p).

The scanner lives at scripts/check_unicode.py — outside the confer package, so
outside the 100% production-coverage gate — but it is load-bearing CI security
tooling and gets its own test. Dangerous characters are constructed with chr()
escapes, NEVER pasted as literal invisible characters into this file: a literal
would be invisible in review and would itself trip the gate on this very file.
"""
import importlib.util
from pathlib import Path

import pytest

_SCANNER = Path(__file__).resolve().parents[1] / "scripts" / "check_unicode.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_unicode", _SCANNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


check_unicode = _load()


# One representative dangerous code point per category the gate must reject.
DANGEROUS = {
    "bidi-control": 0x202E,      # RIGHT-TO-LEFT OVERRIDE (Trojan Source)
    "directional-mark": 0x200F,  # RIGHT-TO-LEFT MARK
    "zero-width": 0x200B,        # ZERO WIDTH SPACE
    "variation-selector": 0xFE0F,
    "tag-char": 0xE0041,         # TAG LATIN CAPITAL LETTER A
    "private-use": 0xE000,
}

# Honest non-ASCII confer actually uses on purpose; must NOT be flagged.
# (em-dash, rightwards arrow, box-drawing rule, e-acute, CJK, emoji)
HONEST = [0x2014, 0x2192, 0x2500, 0x00E9, 0x4E2D, 0x1F600]


@pytest.mark.parametrize("cp,expected", [(cp, cat) for cat, cp in DANGEROUS.items()])
def test_category_flags_each_dangerous_class(cp, expected):
    assert check_unicode.category(cp) == expected


@pytest.mark.parametrize("cp", HONEST)
def test_category_allows_honest_glyphs(cp):
    assert check_unicode.category(cp) is None


def test_find_disallowed_reports_line_and_column():
    text = "ok\nva" + chr(0x202E) + "r = 1\n"
    assert check_unicode.find_disallowed(text) == [(2, 3, 0x202E, "bidi-control")]


def test_scanner_flags_a_planted_codepoint(tmp_path):
    (tmp_path / "evil.py").write_text("x = 1  " + chr(0x200B) + "\n", encoding="utf-8")
    assert check_unicode.main(["check_unicode", str(tmp_path)]) == 1


def test_scanner_passes_honest_glyphs(tmp_path):
    (tmp_path / "fine.py").write_text(
        "# em-dash " + chr(0x2014) + " arrow " + chr(0x2192) + "\n", encoding="utf-8"
    )
    assert check_unicode.main(["check_unicode", str(tmp_path)]) == 0
