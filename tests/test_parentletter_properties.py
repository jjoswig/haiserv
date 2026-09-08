"""Property-based tests for the Elternbrief (parent letter) HTML parser.

Uses Hypothesis to verify invariants on parse_parentletter_list:

Property A — Idempotency of parse count
    Generating N valid table rows and wrapping them in a <table> always yields
    exactly N ParentLetter objects.

Property B — UUID field integrity
    Every returned ParentLetter has a non-empty letter_uuid and child_uuid that
    match the UUID pattern used to generate the rows.

Property C — Robustness to arbitrary HTML injection
    Injecting arbitrary Unicode text into cell content never raises an exception
    and always returns a list (possibly empty).

Property D — Unread flag consistency
    The is_unread flag on each letter matches whether its row contained the
    unread CSS class.
"""

from __future__ import annotations

import re

from hypothesis import given, settings
from hypothesis import strategies as st

from custom_components.haiserv.parentletter_parser import parse_parentletter_list

# ---------------------------------------------------------------------------
# Strategies
# ---------------------------------------------------------------------------

UUID_ST = st.from_regex(
    r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}",
    fullmatch=True,
)

# Safe cell text: printable characters that won't break basic HTML structure
SAFE_TEXT_ST = st.text(
    alphabet=st.characters(
        whitelist_categories=("L", "N", "Zs", "P"),
        blacklist_characters="<>&\"'",
    ),
    min_size=0,
    max_size=50,
)

# A strategy for building one complete valid <tr> HTML fragment
_row_st = st.fixed_dictionaries(
    {
        "letter_uuid": UUID_ST,
        "child_uuid": UUID_ST,
        "subject": SAFE_TEXT_ST,
        "sender": SAFE_TEXT_ST,
        "additional": SAFE_TEXT_ST,
        "child": SAFE_TEXT_ST,
        "recipient": SAFE_TEXT_ST,
        "date": st.just("15.03.2024 09:30"),
        "is_unread": st.booleans(),
    }
)


def _build_row(row: dict) -> str:
    """Render one <tr> fragment from a dict produced by _row_st."""
    lu = row["letter_uuid"]
    cu = row["child_uuid"]
    unread_class = " class=\"parent-index-table-unread\"" if row["is_unread"] else ""
    return (
        f"<tr>"
        f"<td><input type=\"checkbox\" value=\"{lu}-{cu}\"></td>"
        f"<td{unread_class}>"
        f"<a href=\"/iserv/parentletter/parent/show/{lu}/{cu}\">{row['subject']}</a>"
        f"</td>"
        f"<td>{row['sender']}</td>"
        f"<td>{row['additional']}</td>"
        f"<td>{row['child']}</td>"
        f"<td>{row['recipient']}</td>"
        f"<td>{row['date']}</td>"
        f"</tr>"
    )


def _build_table(rows: list[dict]) -> str:
    row_html = "\n".join(_build_row(r) for r in rows)
    return f"<table><tbody>{row_html}</tbody></table>"


# ---------------------------------------------------------------------------
# Property A — Idempotency of parse count
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(rows=st.lists(_row_st, min_size=1, max_size=20))
def test_property_a_parse_count_matches_row_count(rows: list[dict]) -> None:
    """Property A: parsing N valid rows yields exactly N ParentLetter objects."""
    html = _build_table(rows)
    letters = parse_parentletter_list(html)
    assert len(letters) == len(rows), (
        f"Expected {len(rows)} letters, got {len(letters)}"
    )


@settings(max_examples=50)
@given(rows=st.lists(_row_st, min_size=0, max_size=5))
def test_property_a_empty_table_yields_empty_list(rows: list[dict]) -> None:
    """Property A supplementary: empty input always yields an empty list."""
    assert parse_parentletter_list("") == []
    assert parse_parentletter_list("  ") == []


# ---------------------------------------------------------------------------
# Property B — UUID field integrity
# ---------------------------------------------------------------------------

_UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@settings(max_examples=100)
@given(rows=st.lists(_row_st, min_size=1, max_size=15))
def test_property_b_uuid_fields_are_valid(rows: list[dict]) -> None:
    """Property B: every letter has non-empty, UUID-shaped letter_uuid and child_uuid."""
    html = _build_table(rows)
    letters = parse_parentletter_list(html)
    for letter in letters:
        assert letter.letter_uuid, "letter_uuid must not be empty"
        assert letter.child_uuid, "child_uuid must not be empty"
        assert _UUID_PATTERN.match(letter.letter_uuid), (
            f"letter_uuid does not look like a UUID: {letter.letter_uuid!r}"
        )
        assert _UUID_PATTERN.match(letter.child_uuid), (
            f"child_uuid does not look like a UUID: {letter.child_uuid!r}"
        )


@settings(max_examples=100)
@given(rows=st.lists(_row_st, min_size=1, max_size=15))
def test_property_b_uuids_match_source_rows(rows: list[dict]) -> None:
    """Property B supplementary: UUIDs in parsed letters match the generated rows."""
    html = _build_table(rows)
    letters = parse_parentletter_list(html)
    assert len(letters) == len(rows)
    for row, letter in zip(rows, letters):
        assert letter.letter_uuid.lower() == row["letter_uuid"].lower()
        assert letter.child_uuid.lower() == row["child_uuid"].lower()


# ---------------------------------------------------------------------------
# Property C — Robustness to arbitrary HTML injection
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(
    arbitrary_html=st.text(
        alphabet=st.characters(blacklist_categories=("Cs",)),
        min_size=0,
        max_size=500,
    )
)
def test_property_c_never_raises_on_arbitrary_input(arbitrary_html: str) -> None:
    """Property C: parse_parentletter_list never raises; always returns a list."""
    result = parse_parentletter_list(arbitrary_html)
    assert isinstance(result, list)


@settings(max_examples=50)
@given(
    subject=st.text(
        alphabet=st.characters(
            blacklist_characters="<>&\"'",
            blacklist_categories=("Cs",),
        ),
        min_size=0,
        max_size=200,
    ),
    row_data=_row_st,
)
def test_property_c_arbitrary_subject_does_not_raise(
    subject: str, row_data: dict
) -> None:
    """Property C supplementary: arbitrary subjects in rows never raise."""
    row_data = dict(row_data)
    row_data["subject"] = subject
    html = _build_table([row_data])
    result = parse_parentletter_list(html)
    assert isinstance(result, list)


# ---------------------------------------------------------------------------
# Property D — Unread flag consistency
# ---------------------------------------------------------------------------


@settings(max_examples=100)
@given(rows=st.lists(_row_st, min_size=1, max_size=20))
def test_property_d_unread_flag_matches_css_class(rows: list[dict]) -> None:
    """Property D: is_unread on each letter matches the CSS class in its row."""
    html = _build_table(rows)
    letters = parse_parentletter_list(html)
    assert len(letters) == len(rows)
    for row, letter in zip(rows, letters):
        assert letter.is_unread is row["is_unread"], (
            f"Expected is_unread={row['is_unread']}, got {letter.is_unread}"
        )


@settings(max_examples=50)
@given(rows=st.lists(_row_st, min_size=1, max_size=10))
def test_property_d_unread_count_consistent(rows: list[dict]) -> None:
    """Property D supplementary: unread count equals the number of rows marked unread."""
    html = _build_table(rows)
    letters = parse_parentletter_list(html)
    expected_unread = sum(1 for r in rows if r["is_unread"])
    actual_unread = sum(1 for letter in letters if letter.is_unread)
    assert actual_unread == expected_unread
