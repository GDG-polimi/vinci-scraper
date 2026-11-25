"""URL canonicalization (SCR-11): give each page one standard URL, to avoid duplicates."""

from urllib.parse import urlsplit, urlunsplit

# Tracking parameters do not change the page itself, so we remove them
# and duplicate URLs of the same page become a single canonical URL.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid"}


def _is_tracking(name: str) -> bool:
    return name.startswith(TRACKING_PREFIXES) or name in TRACKING_PARAMS


def _clean(url: str, drop: set[str]) -> str:
    """Splits the URL, keeps only the query pairs that are not tracking and not in `drop`,
    then rebuilds it with a lowercase host and no #fragment.
    """
    parts = urlsplit(url)
    kept = []
    for pair in parts.query.split("&"):
        name = pair.partition("=")[0]
        if not (_is_tracking(name) or name in drop):
            kept.append(pair)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "&".join(kept), ""))


def fetch_url(url: str) -> str:
    """The cleaned URL to download. Keeps cHash: TYPO3 may answer 404 without it."""
    return _clean(url, drop=set())


def dedup_key(url: str) -> str:
    """The key to compare URLs: same key = same page.
    Also drops cHash, which doesn't change the page.
    """
    return _clean(url, drop={"cHash"})
