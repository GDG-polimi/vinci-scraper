"""URL canonicalization (SCR-11): give each page one standard URL, to avoid duplicates."""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# Tracking parameters do not change the page itself, so we remove them
# and duplicate URLs of the same page become a single canonical URL.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid"}


# Checks one query parameter name: True if it starts with "utm_" or is in TRACKING_PARAMS.
def _is_tracking(name: str) -> bool:
    return name.startswith(TRACKING_PREFIXES) or name in TRACKING_PARAMS


# Splits the URL, keeps only the query pairs that are not tracking and not in `drop`,
# then rebuilds it with a lowercase host and no #fragment.
def _clean(url: str, drop: set[str]) -> str:
    parts = urlsplit(url)
    kept = []
    for name, value in parse_qsl(parts.query, keep_blank_values=True):
        if not (_is_tracking(name) or name in drop):
            kept.append((name, value))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, urlencode(kept), ""))


# The cleaned URL to download. Keeps cHash: TYPO3 may answer 404 without it.
def fetch_url(url: str) -> str:
    return _clean(url, drop=set())


# The key to compare URLs: same key = same page. Also drops cHash, which doesn't change the page.
def dedup_key(url: str) -> str:
    return _clean(url, drop={"cHash"})
