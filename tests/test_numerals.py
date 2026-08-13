"""Hand cases for the reading model — each one is a bug class we expect."""

from fractions import Fraction as F

from tallyproof.core.numerals import candidates, parse_with, render, surface_variants


def test_us_and_continental_collide():
    # THE ambiguity: same glyphs, both readings valid, values 1000x apart.
    assert parse_with("1.234", ".", ",") == F(1234, 1000)
    assert parse_with("1.234", ",", ".") == F(1234)
    assert candidates("1.234") >= {F(1234, 1000), F(1234)}


def test_grouping_shape_prunes():
    # interior groups must be exactly 3 digits
    assert parse_with("1,23", ".", ",") is None
    assert parse_with("12,3456", ".", ",") is None
    assert parse_with("1234,567", ".", ",") is None  # leading group max 3
    assert parse_with("1,234,567", ".", ",") == F(1234567)


def test_negatives():
    assert parse_with("-2.000", ",", ".") == F(-2000)
    assert parse_with("(1.50)", ".", ",") == F(-150, 100)


def test_unicode_spaces_group():
    # NBSP and NNBSP group separators (CLDR's choice for 175 locales)
    assert parse_with("1 234,56", ",", " ") == F(123456, 100)
    assert parse_with("1 234,56", ",", " ") == F(123456, 100)


def test_swiss_apostrophe():
    assert parse_with("1'234.56", ".", "'") == F(123456, 100)


def test_garbage_rejected():
    for junk in ("", "abc", "1..2", "1,2,3", "12,34", "--5", "1.2.3", "['10,000']"):
        assert parse_with(junk, ".", ",") is None


def test_zero_reading_tokens():
    assert candidates("O.OO") == set()  # letters never parse


def test_surface_variants_contains_confusions():
    # 3<->8 confusion: "3,900" must admit 8,900 and 3,900 among others
    vs = surface_variants("3,900")
    assert F(3900) in vs and F(8900) in vs
    # dropped separator: "39.000" admits 39000 (continental) and 39.0 (US)
    vs2 = surface_variants("39.000")
    assert F(39000) in vs2


def test_render_round_trip_hand():
    assert render(F(1234567), ".", ",") == "1,234,567"
    assert render(F(-123456, 100), ",", ".") == "-1.234,56"
    assert render(F(95, 10), ".", ",") == "9.5"


def test_variants_bounded():
    # completeness is affordable because the variant space is tiny
    assert len(surface_variants("123,456.78")) < 200
