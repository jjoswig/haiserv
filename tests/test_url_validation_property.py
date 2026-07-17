# Feature: iserv-homeassistant-integration, Property 1: URL Validation Correctness
"""Property-based test for URL validation correctness.

**Validates: Requirements 1.2**

For any string input to validate_url, the function SHALL accept the input if and only if
it begins with "https://" and forms a syntactically valid URL (contains a host component
with at least one dot or is "localhost"). All other strings SHALL be rejected.
"""

from urllib.parse import urlparse

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from custom_components.iserv.api import validate_url


def _expected_validation_result(url: str) -> bool:
    """Reference implementation: determine if a URL should be accepted by validate_url.

    Accepts iff:
    - Input is a string
    - Starts with "https://"
    - urlparse produces a non-empty hostname
    - Hostname contains at least one dot OR is "localhost"
    """
    if not isinstance(url, str):
        return False
    if not url.startswith("https://"):
        return False
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    if not parsed.hostname:
        return False
    host = parsed.hostname
    if "." not in host and host != "localhost":
        return False
    return True


# Strategy: generate valid https URLs with proper domains
_valid_https_urls = st.one_of(
    # Standard domains: https://host.tld
    st.builds(
        lambda host, tld, path: f"https://{host}.{tld}{path}",
        host=st.from_regex(r"[a-z][a-z0-9\-]{0,20}", fullmatch=True),
        tld=st.from_regex(r"[a-z]{2,6}", fullmatch=True),
        path=st.from_regex(r"(/[a-z0-9\-]{1,10}){0,3}", fullmatch=True),
    ),
    # Subdomains: https://sub.host.tld
    st.builds(
        lambda sub, host, tld: f"https://{sub}.{host}.{tld}",
        sub=st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True),
        host=st.from_regex(r"[a-z][a-z0-9]{0,10}", fullmatch=True),
        tld=st.from_regex(r"[a-z]{2,6}", fullmatch=True),
    ),
    # Localhost
    st.just("https://localhost"),
    st.builds(
        lambda port: f"https://localhost:{port}",
        port=st.integers(min_value=1, max_value=65535),
    ),
    # With port
    st.builds(
        lambda host, tld, port: f"https://{host}.{tld}:{port}",
        host=st.from_regex(r"[a-z][a-z0-9]{1,10}", fullmatch=True),
        tld=st.from_regex(r"[a-z]{2,6}", fullmatch=True),
        port=st.integers(min_value=1, max_value=65535),
    ),
)

# Strategy: generate invalid URLs (various failure modes)
_invalid_urls = st.one_of(
    # Empty string
    st.just(""),
    # HTTP (not https)
    st.builds(
        lambda host, tld: f"http://{host}.{tld}",
        host=st.from_regex(r"[a-z]{1,10}", fullmatch=True),
        tld=st.from_regex(r"[a-z]{2,6}", fullmatch=True),
    ),
    # FTP or other schemes
    st.builds(
        lambda scheme, host: f"{scheme}://{host}.com",
        scheme=st.sampled_from(["ftp", "ssh", "ws", "wss", "file"]),
        host=st.from_regex(r"[a-z]{1,10}", fullmatch=True),
    ),
    # No scheme at all
    st.from_regex(r"[a-z][a-z0-9\.]{1,30}", fullmatch=True),
    # https:// with no host (just scheme)
    st.just("https://"),
    # https:// with single-word host (no dot, not localhost)
    st.builds(
        lambda host: f"https://{host}",
        host=st.from_regex(r"[a-z]{2,15}", fullmatch=True).filter(
            lambda h: h != "localhost"
        ),
    ),
    # Random text
    st.text(min_size=0, max_size=50),
)


@given(url=_valid_https_urls)
@settings(max_examples=100)
def test_validate_url_accepts_valid_https_urls(url: str):
    """Property: validate_url accepts all well-formed https:// URLs with valid hosts.

    A valid URL starts with https://, has a hostname with at least one dot
    or is localhost.
    """
    expected = _expected_validation_result(url)
    # All URLs from our valid strategy should pass both the reference and actual impl
    assert expected is True, f"Reference rejected valid URL: {url}"
    assert validate_url(url) is True, f"validate_url rejected valid URL: {url}"


@given(url=_invalid_urls)
@settings(max_examples=100)
def test_validate_url_rejects_invalid_inputs(url: str):
    """Property: validate_url rejects all inputs that don't meet the criteria.

    Invalid inputs include: non-https schemes, missing host, single-word hosts
    (not localhost), empty strings, and random text.
    """
    # For inputs from our invalid strategy, the function should agree with reference
    expected = _expected_validation_result(url)
    result = validate_url(url)
    assert result == expected, (
        f"validate_url({url!r}) = {result}, expected {expected}"
    )


@given(url=st.text(min_size=0, max_size=200))
@settings(max_examples=200)
def test_validate_url_matches_reference_for_arbitrary_strings(url: str):
    """Property: For any arbitrary string, validate_url agrees with the reference spec.

    The reference spec accepts iff: starts with "https://", urlparse yields a hostname,
    and hostname contains a dot or is "localhost".
    """
    expected = _expected_validation_result(url)
    result = validate_url(url)
    assert result == expected, (
        f"validate_url({url!r}) = {result}, expected {expected}"
    )
