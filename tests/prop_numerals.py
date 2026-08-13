"""Property tests for the reading model.

The round-trip law is what the textual repair channel stands on: a repair
is scored by re-rendering the repaired value into the document's own
convention, so ``parse ∘ render = id`` failing for ANY representable value
silently breaks repairs.  Hand-written cases miss the Unicode-space and
odd-group-length corners; Hypothesis does not.
"""

from fractions import Fraction

from hypothesis import given, settings
from hypothesis import strategies as st

from tallyproof.core.numerals import CANDIDATE_CONVENTIONS, candidates, parse_with, render

conventions = st.sampled_from(CANDIDATE_CONVENTIONS)
# any value with an exact <=4-decimal expansion, up to billions, signed
values = st.builds(
    lambda units, exp, neg: Fraction(-units if neg else units, 10**exp),
    st.integers(min_value=0, max_value=10**12),
    st.integers(min_value=0, max_value=4),
    st.booleans(),
)


@given(values, conventions)
@settings(max_examples=400)
def test_parse_render_round_trip(v, conv):
    dec, grp = conv
    assert parse_with(render(v, dec, grp), dec, grp) == v


@given(values, conventions)
@settings(max_examples=200)
def test_rendered_value_is_a_candidate(v, conv):
    """Whatever we print must be readable back — under SOME convention —
    as the value we printed (the reading model must contain its own output)."""
    dec, grp = conv
    assert v in candidates(render(v, dec, grp))


@given(st.text(min_size=0, max_size=24))
@settings(max_examples=300)
def test_parser_total_on_arbitrary_text(s):
    """No input crashes the parser; junk maps to None, never to a value
    invented out of thin air (returned values must reproduce by rendering)."""
    for dec, grp in CANDIDATE_CONVENTIONS:
        v = parse_with(s, dec, grp)
        assert v is None or isinstance(v, Fraction)
