"""Unit tests for the Elternbrief (parent letter) HTML parser."""

from __future__ import annotations

from datetime import datetime

import pytest

from custom_components.haiserv.parentletter_parser import (
    ParentLetter,
    extract_csrf_token,
    parse_parentletter_detail,
    parse_parentletter_list,
)

# ---------------------------------------------------------------------------
# Shared HTML fixtures
# ---------------------------------------------------------------------------

LETTER_UUID = "aabbccdd-1111-2222-3333-444455556666"
CHILD_UUID = "ffffeee0-aaaa-bbbb-cccc-ddddeeee1111"

_ROW_UNREAD = f"""
<tr>
  <td>
    <input type="checkbox" name="letters[]"
           value="{LETTER_UUID}-{CHILD_UUID}">
  </td>
  <td class="parent-index-table-unread">
    <a href="/iserv/parentletter/parent/show/{LETTER_UUID}/{CHILD_UUID}">
      Ausflug Klasse 12
    </a>
  </td>
  <td>Max Mustermann</td>
  <td>Frau Müller</td>
  <td>Herr Schmidt</td>
  <td>Klasse o12a</td>
  <td>15.03.2024 09:30</td>
</tr>
"""

_ROW_READ = f"""
<tr>
  <td><input type="checkbox" value="{LETTER_UUID}-{CHILD_UUID}"></td>
  <td>
    <a href="/iserv/parentletter/parent/show/{LETTER_UUID}/{CHILD_UUID}">
      Elternsprechtag
    </a>
  </td>
  <td>Erika Muster</td>
  <td>Herr Müller</td>
  <td></td>
  <td>Klasse 5b</td>
  <td>01.01.2024 14:00</td>
</tr>
"""

_LIST_HTML = f"""
<!DOCTYPE html>
<html>
<head><title>Elternbrief</title></head>
<body>
<table class="table">
  <thead>
    <tr><th>Auswahl</th><th>Betreff</th><th>Absender</th>
        <th>Weitere</th><th>Kind</th><th>Empfänger</th><th>Datum</th>
    </tr>
  </thead>
  <tbody>
    {_ROW_UNREAD}
    {_ROW_READ}
  </tbody>
</table>
</body>
</html>
"""

_DETAIL_HTML = f"""
<!DOCTYPE html>
<html>
<body>
<div class="parent-show">
  <h2 class="translatable-content">Ausflug Klasse 12</h2>
  <dl>
    <dt>Kind</dt>
    <dd>Max Mustermann</dd>
    <dt>Empfänger</dt>
    <dd>Klasse o12a</dd>
    <dt>Absender</dt>
    <dd>Frau Müller</dd>
    <dt>Weitere Absender</dt>
    <dd>Herr Schmidt, Frau Huber</dd>
    <dt>Versandzeitpunkt</dt>
    <dd>15.03.2024 09:30</dd>
  </dl>
  <div class="parent-letter-body translatable-content editor-content">
    <p>Liebe Eltern, wir planen einen Ausflug nach Berlin.</p>
  </div>
  <form method="post">
    <input type="hidden" name="_token" value="my-csrf-token-123">
    <button type="submit" name="submit" value="1">Als gelesen markieren</button>
  </form>
</div>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# parse_parentletter_list
# ---------------------------------------------------------------------------


class TestParseParentletterList:
    """Tests for parse_parentletter_list()."""

    def test_empty_html_returns_empty_list(self) -> None:
        assert parse_parentletter_list("") == []
        assert parse_parentletter_list("   ") == []

    def test_html_without_rows_returns_empty_list(self) -> None:
        assert parse_parentletter_list("<html><body></body></html>") == []

    def test_parses_two_letters(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert len(letters) == 2

    def test_unread_flag_detected(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert letters[0].is_unread is True
        assert letters[1].is_unread is False

    def test_letter_uuid_extracted_from_href(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert letters[0].letter_uuid == LETTER_UUID

    def test_child_uuid_extracted_from_href(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert letters[0].child_uuid == CHILD_UUID

    def test_subject_extracted(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert "Ausflug Klasse 12" in letters[0].subject
        assert "Elternsprechtag" in letters[1].subject

    def test_sender_extracted(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert "Frau Müller" in letters[0].sender

    def test_additional_senders_extracted(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert "Herr Schmidt" in letters[0].additional_senders

    def test_child_name_extracted(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert "Max Mustermann" in letters[0].child

    def test_recipient_extracted(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert "Klasse o12a" in letters[0].recipient

    def test_created_at_parsed(self) -> None:
        letters = parse_parentletter_list(_LIST_HTML)
        assert isinstance(letters[0].created_at, datetime)
        assert letters[0].created_at == datetime(2024, 3, 15, 9, 30)

    def test_body_html_empty_from_list(self) -> None:
        """List view does not populate body_html."""
        letters = parse_parentletter_list(_LIST_HTML)
        assert letters[0].body_html == ""

    def test_header_row_skipped(self) -> None:
        """The <thead> row has no checkbox / href and should be skipped."""
        letters = parse_parentletter_list(_LIST_HTML)
        assert len(letters) == 2

    def test_uuid_from_checkbox_fallback(self) -> None:
        """When no <a href> is present, parse IDs from checkbox value."""
        lu = "00000000-0000-0000-0000-000000000001"
        cu = "00000000-0000-0000-0000-000000000002"
        html = f"""
        <table><tbody>
        <tr>
          <td><input type="checkbox" value="{lu}-{cu}"></td>
          <td>Only checkbox, no link</td>
          <td>Kind B</td>
          <td>Sender A</td>
          <td></td>
          <td>Klasse 7c</td>
          <td>10.10.2023 08:00</td>
        </tr>
        </tbody></table>
        """
        letters = parse_parentletter_list(html)
        assert len(letters) == 1
        assert letters[0].letter_uuid == lu
        assert letters[0].child_uuid == cu

    def test_row_without_uuids_skipped(self) -> None:
        """Rows without recognizable UUIDs are silently skipped."""
        html = """
        <table><tbody>
        <tr>
          <td>no checkbox here</td>
          <td><a href="/iserv/some/other/path">Link</a></td>
          <td>Sender</td>
        </tr>
        </tbody></table>
        """
        letters = parse_parentletter_list(html)
        assert letters == []

    def test_single_row_list(self) -> None:
        html = f"""
        <table><tbody>{_ROW_UNREAD}</tbody></table>
        """
        letters = parse_parentletter_list(html)
        assert len(letters) == 1

    def test_date_without_time_parsed(self) -> None:
        lu = "11111111-1111-1111-1111-111111111111"
        cu = "22222222-2222-2222-2222-222222222222"
        html = f"""
        <table><tbody>
        <tr>
          <td><input type="checkbox" value="{lu}-{cu}"></td>
          <td><a href="/iserv/parentletter/parent/show/{lu}/{cu}">Subj</a></td>
          <td>S</td><td></td><td>K</td><td>R</td>
          <td>20.06.2023</td>
        </tr>
        </tbody></table>
        """
        letters = parse_parentletter_list(html)
        assert letters[0].created_at == datetime(2023, 6, 20)

    def test_malformed_html_does_not_raise(self) -> None:
        """Parser must not raise on garbled HTML."""
        letters = parse_parentletter_list("<table><tr><td><<>>")
        assert isinstance(letters, list)


# ---------------------------------------------------------------------------
# parse_parentletter_detail
# ---------------------------------------------------------------------------


class TestParseParentletterDetail:
    """Tests for parse_parentletter_detail()."""

    @pytest.fixture
    def stub_letter(self) -> ParentLetter:
        return ParentLetter(
            letter_uuid=LETTER_UUID,
            child_uuid=CHILD_UUID,
            subject="Old subject",
            sender="Old sender",
        )

    def test_empty_html_returns_original(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail("", stub_letter)
        assert enriched.subject == stub_letter.subject
        assert enriched.sender == stub_letter.sender

    def test_subject_updated_from_h2(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert enriched.subject == "Ausflug Klasse 12"

    def test_child_updated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert enriched.child == "Max Mustermann"

    def test_recipient_updated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert enriched.recipient == "Klasse o12a"

    def test_sender_updated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert enriched.sender == "Frau Müller"

    def test_additional_senders_updated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert "Herr Schmidt" in enriched.additional_senders
        assert "Frau Huber" in enriched.additional_senders

    def test_created_at_updated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert enriched.created_at == datetime(2024, 3, 15, 9, 30)

    def test_body_html_populated(self, stub_letter: ParentLetter) -> None:
        enriched = parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert "Liebe Eltern" in enriched.body_html

    def test_original_letter_not_mutated(self, stub_letter: ParentLetter) -> None:
        """parse_parentletter_detail must not mutate the original object."""
        original_subject = stub_letter.subject
        parse_parentletter_detail(_DETAIL_HTML, stub_letter)
        assert stub_letter.subject == original_subject

    def test_missing_fields_do_not_override(self, stub_letter: ParentLetter) -> None:
        """Fields absent from the HTML remain as on the stub."""
        html = "<html><body><div class='parent-show'></div></body></html>"
        enriched = parse_parentletter_detail(html, stub_letter)
        assert enriched.sender == stub_letter.sender


# ---------------------------------------------------------------------------
# extract_csrf_token
# ---------------------------------------------------------------------------


class TestExtractCsrfToken:
    """Tests for extract_csrf_token()."""

    def test_extracts_token(self) -> None:
        token = extract_csrf_token(_DETAIL_HTML)
        assert token == "my-csrf-token-123"

    def test_returns_none_if_absent(self) -> None:
        assert extract_csrf_token("<html></html>") is None

    def test_returns_none_on_empty_html(self) -> None:
        assert extract_csrf_token("") is None

    def test_handles_single_quotes(self) -> None:
        html = "<input type='hidden' name='_token' value='tok123'>"
        assert extract_csrf_token(html) == "tok123"

    def test_handles_reversed_attribute_order(self) -> None:
        html = "<input type='hidden' value='rev-tok' name='_token'>"
        assert extract_csrf_token(html) == "rev-tok"
