"""The declared reading model: every value a printed numeral admits.

This module answers one question: *given the glyphs that appear on paper,
which numbers could they mean?*  It is deliberately closed-world.  The
conventions, confusion pairs and fade rules below are the **entire**
hypothesis space the solver searches, so every claim of the form
"exactly one reading closes the residual" is a claim *within this model*
and is only as strong as the model is honest.  See docs/reading_model.md.

Three layers, composed:

1.  Grouping conventions — a (decimal, group) separator pair.  ``1.234``
    is one thousand two hundred and thirty-four in Berlin and a little
    over one in Boston; both readings are produced, and shape validity
    (leading group 1-3 digits, interior groups exactly 3) prunes the rest.
2.  Single-glyph OCR confusion — ``8`` read for ``3``, ``0`` for ``8``,
    the classic thermal-paper substitutions.  One glyph per variant.
3.  Dropped separator — thermal fade eats a ``.`` or ``,``.

Everything returns exact ``Fraction`` values.  No floats, ever: a float
cannot represent 0.1 and a verifier that says "proven" must not be
arguing with IEEE 754.

The model is FROZEN to what was measured on CORD-v2 (see eval/): adding
a convention or a confusion pair changes every published number, so any
change here must regenerate eval/report.md in the same commit (CI checks).
"""

from __future__ import annotations

import re
from fractions import Fraction

# --- conventions -----------------------------------------------------------
# (decimal, group) pairs.  CANDIDATE_CONVENTIONS is what a token may mean;
# DOC_CONVENTIONS is what a whole document may be printed in (apostrophe
# grouping is admitted per-token but never wins a document vote — it is
# too rare on receipts to be a stable document-level convention).
CANDIDATE_CONVENTIONS: tuple[tuple[str, str], ...] = (
    (".", ","),  # US/UK:      1,234.56
    (",", "."),  # continental: 1.234,56
    (",", " "),  # SI + comma decimal: 1 234,56
    (".", " "),  # SI + point decimal: 1 234.56
    (".", "'"),  # Swiss/Setswana: 1'234.56
    (",", "'"),
)
DOC_CONVENTIONS: tuple[tuple[str, str], ...] = (
    (",", "."),
    (".", ","),
    (",", " "),
    (".", " "),
)

# Unicode spaces that appear as group separators in the wild.  CLDR uses
# NBSP (U+00A0) or NNBSP (U+202F) for 175 locales; ASCII space shows up in
# OCR output for either.  All are normalised to ASCII space before parsing.
_SPACE_CHARS = "   "

# Single-glyph OCR confusion set, as measured (thermal print, low DPI).
# Values are the glyphs each key is misread AS.  Non-digit outputs (O, S)
# simply never parse, which keeps the table symmetric and harmless.
CONFUSION: dict[str, str] = {
    "0": "8O",
    "1": "7",
    "2": "7",
    "3": "8",
    "4": "9",
    "5": "6S",
    "6": "58",
    "7": "12",
    "8": "306",
    "9": "4",
}

_NUMERALISH = re.compile(r"[0-9][0-9.,' ]*")


def _normalise(surface: str) -> tuple[str, bool]:
    """Strip sign wrappers and unify Unicode spaces.

    Returns (bare token, is_negative).  Negatives are recognised as a
    leading minus or full parenthesisation — the two forms receipts use.
    """
    t = str(surface).strip()
    for ch in _SPACE_CHARS:
        t = t.replace(ch, " ")
    neg = t.startswith("-") or (t.startswith("(") and t.endswith(")"))
    t = t.strip("()")
    t = t.removeprefix("-")  # exactly one sign; "--5" is junk, not a negative
    return t.strip(), neg


def parse_with(surface: str, dec: str, grp: str) -> Fraction | None:
    """Parse *surface* under one fixed (decimal, group) convention.

    Returns None unless the token is shape-valid under that convention:
    at most one decimal separator, digit-only fraction part, and group
    runs of exactly 3 digits after a leading run of 1-3.
    """
    if surface is None:
        return None
    t, neg = _normalise(surface)
    if not t or not _NUMERALISH.fullmatch(t):
        return None
    if dec in t:
        if t.count(dec) != 1:
            return None
        int_part, frac_part = t.split(dec)
    else:
        int_part, frac_part = t, ""
    if frac_part and not frac_part.isdigit():
        return None
    if grp in int_part:
        groups = int_part.split(grp)
        if not (1 <= len(groups[0]) <= 3):
            return None
        if not all(len(g) == 3 for g in groups[1:]):
            return None
        if not all(g.isdigit() for g in groups):
            return None
        digits = "".join(groups)
    else:
        if not int_part.isdigit():
            return None
        digits = int_part
    # nothing but digits and the two declared separators may remain
    if set(t) - set("0123456789") - {dec, grp}:
        return None
    value = Fraction(int(digits or 0))
    if frac_part:
        value += Fraction(int(frac_part), 10 ** len(frac_part))
    return -value if neg else value


def candidates(surface: str) -> set[Fraction]:
    """Every value *surface* admits across the candidate conventions.

    This is V(s) **without** OCR-confusion variants: the readings of the
    glyphs exactly as printed.  ``len(candidates(s)) > 1`` is the measured
    83.5%-of-money-tokens ambiguity (see eval/report.md).
    """
    out: set[Fraction] = set()
    for dec, grp in CANDIDATE_CONVENTIONS:
        v = parse_with(surface, dec, grp)
        if v is not None:
            out.add(v)
    return out


def surface_variants(surface: str) -> set[Fraction]:
    """Every value the printed glyphs admit under the full fault model.

    The single-fault re-reading space: grouping conventions x single-glyph
    OCR confusion x one dropped separator.  This is the set the solver
    enumerates exhaustively; its size is bounded by
    ``len(surface) * max_confusions * len(CANDIDATE_CONVENTIONS)`` — tens,
    not thousands — which is what makes completeness affordable.
    """
    if not isinstance(surface, str):
        return set()
    surfaces = {surface}
    for i, ch in enumerate(surface):
        for sub in CONFUSION.get(ch, ""):
            surfaces.add(surface[:i] + sub + surface[i + 1 :])
        if ch in ".,":  # separator lost to thermal fade
            surfaces.add(surface[:i] + surface[i + 1 :])
    out: set[Fraction] = set()
    for dec, grp in CANDIDATE_CONVENTIONS:
        for s in surfaces:
            v = parse_with(s, dec, grp)
            if v is not None:
                out.add(v)
    return out


def render(value: Fraction, dec: str = ".", grp: str = ",", decimals: int | None = None) -> str:
    """Render a value back into a printed convention.

    Inverse of ``parse_with`` for representable values — the round-trip
    property ``parse_with(render(v, dec, grp), dec, grp) == v`` is tested
    with Hypothesis across all conventions (tests/prop_numerals.py).
    """
    neg = value < 0
    value = -value if neg else value
    if decimals is None:
        # smallest decimal expansion that is exact, up to 6 places
        for d in range(7):
            if (value * 10**d).denominator == 1:
                decimals = d
                break
        else:
            raise ValueError(f"{value} has no exact decimal rendering <= 6 places")
    scaled = value * 10**decimals
    if scaled.denominator != 1:
        raise ValueError(f"{value} not representable with {decimals} decimals")
    digits = str(scaled.numerator)
    digits = digits.rjust(decimals + 1, "0")
    int_digits, frac_digits = digits[: len(digits) - decimals], digits[len(digits) - decimals :]
    groups = []
    while len(int_digits) > 3:
        groups.insert(0, int_digits[-3:])
        int_digits = int_digits[:-3]
    groups.insert(0, int_digits)
    out = grp.join(groups)
    if decimals:
        out += dec + frac_digits
    return ("-" if neg else "") + out
