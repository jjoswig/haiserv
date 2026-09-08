"""Parser for iServ Elternbrief (parent letter) HTML responses."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from html.parser import HTMLParser

_LOGGER = logging.getLogger(__name__)

# Date format used by iServ in the list view
_DATE_FORMAT = "%d.%m.%Y %H:%M"
# Alternative without minute precision
_DATE_FORMAT_SHORT = "%d.%m.%Y"


@dataclass
class ParentLetter:
    """Represents a single Elternbrief (parent letter) from iServ.

    Attributes:
        letter_uuid: UUID of the letter (from URL path).
        child_uuid: UUID of the child the letter is addressed to (from URL).
        subject: Subject / title of the letter.
        sender: Primary sender (author) name.
        additional_senders: List of additional sender names (may be empty).
        child: Name of the student the letter is addressed to.
        recipient: Recipient group label (e.g. "Klasse o12a").
        created_at: Timestamp the letter was created/sent.
        is_unread: Whether the letter has not yet been read.
        body_html: HTML body of the letter; only populated from the detail view.
    """

    letter_uuid: str
    child_uuid: str
    subject: str
    sender: str
    additional_senders: list[str] = field(default_factory=list)
    child: str = ""
    recipient: str = ""
    created_at: datetime | None = None
    is_unread: bool = False
    body_html: str = ""


# ---------------------------------------------------------------------------
# List-view parser
# ---------------------------------------------------------------------------

# HTML void elements never emit a closing tag, so they must not affect the
# depth counter used to detect the end of a <tr> block.
_VOID_ELEMENTS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr",
})


class _TableRowCollector(HTMLParser):
    """Collect all <tr> elements from an HTML table body."""

    def __init__(self) -> None:
        super().__init__()
        self._depth: int = 0
        self._in_row: bool = False
        self._row_html: list[str] = []
        self.rows: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "tr":
            self._in_row = True
            self._depth = 1
            self._row_html = [self.get_starttag_text() or f"<{tag}>"]
            return
        if self._in_row:
            # Void elements (input, img, br, …) never produce a closing tag,
            # so do not increment depth — otherwise </tr> would never reach 0.
            if tag not in _VOID_ELEMENTS:
                self._depth += 1
            self._row_html.append(self.get_starttag_text() or f"<{tag}>")

    def handle_endtag(self, tag: str) -> None:
        if not self._in_row:
            return
        self._row_html.append(f"</{tag}>")
        if tag == "tr":
            self._depth -= 1
            if self._depth <= 0:
                self.rows.append("".join(self._row_html))
                self._in_row = False
                self._row_html = []
        else:
            self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._in_row:
            self._row_html.append(data)

    def handle_entityref(self, name: str) -> None:
        if self._in_row:
            self._row_html.append(f"&{name};")

    def handle_charref(self, name: str) -> None:
        if self._in_row:
            self._row_html.append(f"&#{name};")


def _strip_tags(html: str) -> str:
    """Remove all HTML tags and collapse whitespace."""
    no_tags = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", no_tags).strip()


def _attr(tag_html: str, attr_name: str) -> str | None:
    """Extract the value of *attr_name* from the first tag in *tag_html*."""
    pattern = re.compile(
        attr_name + r'\s*=\s*(?:"([^"]*)"' + r"|'([^']*)')", re.IGNORECASE
    )
    match = pattern.search(tag_html)
    if not match:
        return None
    return match.group(1) if match.group(1) is not None else match.group(2)


def _extract_uuids_from_href(href: str) -> tuple[str, str] | None:
    """Return (letter_uuid, child_uuid) from a parentletter show URL."""
    pattern = re.compile(
        r"/iserv/parentletter/parent/show/"
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/"
        r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        re.IGNORECASE,
    )
    match = pattern.search(href)
    if not match:
        return None
    return match.group(1), match.group(2)


def _extract_uuids_from_checkbox(value: str) -> tuple[str, str] | None:
    """Return (letter_uuid, child_uuid) from a checkbox value '{lu}-{cu}'."""
    uuid_pat = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
    pattern = re.compile(
        rf"^({uuid_pat})-({uuid_pat})$", re.IGNORECASE
    )
    match = pattern.fullmatch(value.strip())
    if not match:
        return None
    return match.group(1), match.group(2)


def _parse_date(value: str) -> datetime | None:
    """Parse an iServ list-view date string to a datetime object."""
    value = value.strip()
    for fmt in (_DATE_FORMAT, _DATE_FORMAT_SHORT):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def _cells_from_row(row_html: str) -> list[str]:
    """Extract text content of each <td> in a <tr> HTML fragment."""
    cells: list[str] = []
    for cell_match in re.finditer(r"<td[^>]*>(.*?)</td>", row_html, re.DOTALL | re.IGNORECASE):
        cells.append(_strip_tags(cell_match.group(1)))
    return cells


def _find_link_in_row(row_html: str) -> str | None:
    """Return the first href pointing to a parentletter show URL."""
    for link_match in re.finditer(r"<a\s[^>]*>", row_html, re.IGNORECASE):
        href = _attr(link_match.group(0), "href")
        if href and "/iserv/parentletter/parent/show/" in href:
            return href
    return None


def _is_unread_row(row_html: str) -> bool:
    """Detect the unread CSS marker class on any element in a row."""
    return "parent-index-table-unread" in row_html


def _checkbox_value_from_row(row_html: str) -> str | None:
    """Extract the value of the first checkbox input in a row."""
    for input_match in re.finditer(r"<input\s[^>]*/?>", row_html, re.IGNORECASE):
        tag = input_match.group(0)
        input_type = _attr(tag, "type")
        if input_type and input_type.lower() == "checkbox":
            return _attr(tag, "value")
    return None


def _parse_row(row_html: str) -> ParentLetter | None:
    """Parse a single <tr> HTML fragment into a ParentLetter, or return None."""
    # Resolve IDs: prefer href, fall back to checkbox value
    href = _find_link_in_row(row_html)
    uuids = _extract_uuids_from_href(href) if href else None

    if uuids is None:
        checkbox_val = _checkbox_value_from_row(row_html)
        if checkbox_val:
            uuids = _extract_uuids_from_checkbox(checkbox_val)

    if uuids is None:
        return None

    letter_uuid, child_uuid = uuids
    cells = _cells_from_row(row_html)
    is_unread = _is_unread_row(row_html)

    # iServ list column order (0-based) as observed in the live HTML:
    # 0: checkbox
    # 1: subject (with link)
    # 2: child name (the student the letter is addressed to)
    # 3: sender (primary author)
    # 4: additional senders
    # 5: recipient group (e.g. "Klasse o12a")
    # 6: created date
    # Columns may vary across iServ versions; fall back gracefully.
    subject = cells[1] if len(cells) > 1 else ""
    child = cells[2] if len(cells) > 2 else ""
    sender = cells[3] if len(cells) > 3 else ""
    additional_raw = cells[4] if len(cells) > 4 else ""
    recipient = cells[5] if len(cells) > 5 else ""
    date_str = cells[6] if len(cells) > 6 else ""

    additional_senders = (
        [s.strip() for s in additional_raw.split(",") if s.strip()]
        if additional_raw
        else []
    )
    created_at = _parse_date(date_str) if date_str else None

    return ParentLetter(
        letter_uuid=letter_uuid,
        child_uuid=child_uuid,
        subject=subject,
        sender=sender,
        additional_senders=additional_senders,
        child=child,
        recipient=recipient,
        created_at=created_at,
        is_unread=is_unread,
        body_html="",
    )


def parse_parentletter_list(html: str) -> list[ParentLetter]:
    """Parse the Elternbrief list-view HTML into ParentLetter objects.

    Scans all <tr> elements in the HTML, attempts to extract letter and child
    UUIDs from anchor hrefs or checkbox values, and falls back gracefully on
    malformed or unexpected markup.

    Args:
        html: Full HTML of ``/iserv/parentletter/parent/index``.

    Returns:
        List of ParentLetter objects found in the page, in document order.
        Rows that cannot be parsed (e.g. headers or malformed rows) are skipped.
    """
    if not html or not html.strip():
        return []

    collector = _TableRowCollector()
    try:
        collector.feed(html)
    except Exception:  # noqa: BLE001
        _LOGGER.warning("Failed to collect table rows from Elternbrief list HTML")
        return []

    letters: list[ParentLetter] = []
    for row_html in collector.rows:
        letter = _parse_row(row_html)
        if letter is not None:
            letters.append(letter)

    return letters


# ---------------------------------------------------------------------------
# Detail-view parser
# ---------------------------------------------------------------------------


_LABEL_MAP: dict[str, str] = {
    "kind": "child",
    "empfänger": "recipient",
    "empfaenger": "recipient",
    "absender": "sender",
    "weitere absender": "additional_senders",
    "versandzeitpunkt": "created_at",
}


def parse_parentletter_detail(html: str, letter: ParentLetter) -> ParentLetter:
    """Enrich a ParentLetter with data from its detail-view HTML.

    Reads the ``<div class="parent-show">`` section and populates/overrides:
    - ``subject`` from ``<h2 class="translatable-content">``
    - ``child``, ``recipient``, ``sender``, ``additional_senders``, ``created_at``
      from the metadata label-value pairs in the ``<table>`` inside ``panel-heading``
    - ``body_html`` from ``<div class="parent-letter-body …">``

    The detail page uses a ``<table>`` with ``<tr><td>Label</td><td>Value</td></tr>``
    rows (not ``<dl>``/``<dt>``/``<dd>``), so both patterns are tried.

    Args:
        html: Full HTML of ``/iserv/parentletter/parent/show/{lid}/{cid}``.
        letter: An existing ParentLetter to enrich (mutated in-place copy).

    Returns:
        A new ParentLetter with detail fields filled in.
    """
    import copy

    enriched = copy.copy(letter)

    if not html or not html.strip():
        return enriched

    # --- subject from <h2 class="translatable-content"> ---
    h2_match = re.search(
        r'<h2[^>]*class="[^"]*translatable-content[^"]*"[^>]*>(.*?)</h2>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if h2_match:
        enriched.subject = _strip_tags(h2_match.group(1))

    # --- body from <div class="parent-letter-body …"> ---
    # Use a non-greedy match that stops at the first </div> after the opening tag.
    body_match = re.search(
        r'<div[^>]*class="[^"]*parent-letter-body[^"]*"[^>]*>(.*?)</div>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if body_match:
        enriched.body_html = body_match.group(1).strip()

    # --- metadata: try <table> rows first (real iServ), fall back to <dl> ---
    # Real iServ detail page uses:
    #   <tr><td class="pr-2"><strong>Kind</strong></td><td>…value…</td></tr>
    label_value_pairs: list[tuple[str, str]] = []

    # Pattern 1: <tr> with two <td> cells
    for tr_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL | re.IGNORECASE):
        tr_inner = tr_match.group(1)
        td_matches = re.findall(r"<td[^>]*>(.*?)</td>", tr_inner, re.DOTALL | re.IGNORECASE)
        if len(td_matches) >= 2:
            label_value_pairs.append((td_matches[0], td_matches[1]))

    # Pattern 2: <dt>/<dd> pairs (used in unit-test fixtures and some iServ versions)
    for raw_label, raw_value in re.findall(
        r"<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>",
        html,
        re.DOTALL | re.IGNORECASE,
    ):
        label_value_pairs.append((raw_label, raw_value))

    for raw_label, raw_value in label_value_pairs:
        label = _strip_tags(raw_label).lower().strip().rstrip(":")
        value = _strip_tags(raw_value)
        field_name = _LABEL_MAP.get(label)
        if field_name is None:
            continue
        if field_name == "child":
            enriched.child = value
        elif field_name == "recipient":
            enriched.recipient = value
        elif field_name == "sender":
            enriched.sender = value
        elif field_name == "additional_senders":
            enriched.additional_senders = [
                s.strip() for s in value.split(",") if s.strip()
            ]
        elif field_name == "created_at":
            parsed_dt = _parse_date(value)
            if parsed_dt is not None:
                enriched.created_at = parsed_dt

    return enriched


# ---------------------------------------------------------------------------
# CSRF token extraction (needed to mark letters as read)
# ---------------------------------------------------------------------------


def extract_csrf_token(html: str) -> str | None:
    """Extract the CSRF ``_token`` value from an Elternbrief detail page.

    The mark-as-read form uses ``form[_token]`` as the field name.

    Args:
        html: HTML of the detail view containing the mark-as-read form.

    Returns:
        The CSRF token string, or None if not found.
    """
    # Real iServ form field: name="form[_token]"
    match = re.search(
        r'<input[^>]+name=["\']form\[_token\]["\'][^>]+value=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    # Reversed attribute order
    match = re.search(
        r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']form\[_token\]["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    # Fallback: plain _token (used in unit-test fixtures)
    match = re.search(
        r'<input[^>]+name=["\']_token["\'][^>]+value=["\']([^"\']+)["\']',
        html,
        re.IGNORECASE,
    )
    if match:
        return match.group(1)
    match = re.search(
        r'<input[^>]+value=["\']([^"\']+)["\'][^>]+name=["\']_token["\']',
        html,
        re.IGNORECASE,
    )
    return match.group(1) if match else None
