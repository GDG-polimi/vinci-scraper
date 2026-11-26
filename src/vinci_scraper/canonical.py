"""URL canonicalization (SCR-11): give each page one standard URL, to avoid duplicates.

`canonical_url()` is the URL to download and to store in `documents.url`.
`dedup_key()` also drops cHash: use it only to tell whether a page was already seen.
`canonical_from_html()` reads the URL a page declares in <link rel="canonical">: if any, use it.
"""

from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit, urlunsplit

# Tracking parameters do not change the page itself, so we remove them
# and duplicate URLs of the same page become a single canonical URL.
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = {"fbclid", "gclid"}


def _is_tracking(name: str) -> bool:
    return name.startswith(TRACKING_PREFIXES) or name in TRACKING_PARAMS


def _clean(url: str, drop: set[str]) -> str:
    """Remove tracking params, `drop` names, empty pairs and #fragment; lowercase the host."""
    parts = urlsplit(url)
    kept = []
    for pair in parts.query.split("&"):
        name = pair.partition("=")[0]
        if pair and not (_is_tracking(name) or name in drop):
            kept.append(pair)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "&".join(kept), ""))


def canonical_url(url: str) -> str:
    """The cleaned URL to download. Keeps cHash: TYPO3 may answer 404 without it."""
    return _clean(url, drop=set())


def dedup_key(url: str) -> str:
    """The key to compare URLs: same key = same page. Also drops cHash."""
    return _clean(url, drop={"cHash"})


class _CanonicalLink(HTMLParser):
    """Keeps the href of the first <link rel="canonical">."""

    href: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = dict(attrs)
        rel = (a.get("rel") or "").lower().split()
        if tag == "link" and "canonical" in rel and self.href is None:
            self.href = a.get("href")


def canonical_from_html(html: str, page_url: str) -> str | None:
    """The page's <link rel="canonical"> passed through canonical_url(), or None if missing.

    A relative href is resolved against `page_url`, the URL the HTML came from (after
    redirects). The link may point anywhere: check it with Config.is_allowed() before use.
    """
    parser = _CanonicalLink()
    parser.feed(html)
    return canonical_url(urljoin(page_url, parser.href)) if parser.href else None
