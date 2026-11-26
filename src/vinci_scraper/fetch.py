"""Async fetcher with per-host politeness limits, retries and allowlist-checked redirects.

Every HTTP request of the crawler goes through `Fetcher.fetch()`. Per host, at most
CONCURRENCY_PER_HOST requests are in flight and request starts are at least INTERVAL
seconds apart, retries included. Hosts are independent: run one task per URL (e.g. with
asyncio.TaskGroup) to crawl several hosts in parallel.

Timeouts, network errors, 429 and 5xx are retried with exponential backoff, or after the
delay the server asks for in Retry-After. Other responses (404 included) are never retried.

Redirects are followed by hand: every hop is checked against the allowlist and waits for
its host's turn like any other request.
"""

import asyncio
import random
import sqlite3
import uuid
from collections import defaultdict
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Self
from urllib.parse import urlsplit

import httpx

from vinci_scraper.client import make_client
from vinci_scraper.config import Config

CONCURRENCY_PER_HOST = 2
INTERVAL = 1.0  # seconds between request starts on the same host
MAX_ATTEMPTS = 4
BACKOFF = 2.0  # seconds before the first retry, doubled at each further one
MAX_RETRY_AFTER = 120.0  # a longer Retry-After gives up instead of stalling the run
MAX_REDIRECTS = 5


class DisallowedURLError(ValueError):
    """The URL, or a redirect target, is outside the host allowlist (config/hosts.yaml)."""


def _retryable(status: int) -> bool:
    return status == 429 or status >= 500


def _retry_after(response: httpx.Response) -> float | None:
    """Seconds asked for by the Retry-After header (a delay or an HTTP date), if any."""
    value = response.headers.get("Retry-After", "").strip()
    if value.isdigit():
        return float(value)
    try:
        when = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if when.tzinfo is None:  # "-0000" dates parse as naive; HTTP dates are always UTC
        when = when.replace(tzinfo=UTC)
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _utc_now() -> str:
    """The current time as stored in the database, e.g. '2026-11-18T09:30:00Z'."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class _HostGate:
    """Politeness state of one host: in-flight slots and the earliest next start.

    All per-host state lives here: to share the limits across processes, replace this class.
    """

    def __init__(self, concurrency: int, interval: float):
        self.slots = asyncio.Semaphore(concurrency)
        self.interval = interval
        self._next_start = 0.0

    async def turn(self) -> None:
        """Wait for this request's start time, `interval` seconds after the previous one."""
        now = asyncio.get_running_loop().time()
        start = max(now, self._next_start)
        self._next_start = start + self.interval  # no await before this line: no lock needed
        if start > now:
            await asyncio.sleep(start - now)

    def defer(self, seconds: float) -> None:
        """Hold every request to this host for `seconds` (the server asked us to wait)."""
        now = asyncio.get_running_loop().time()
        self._next_start = max(self._next_start, now + seconds)


class Fetcher:
    """Polite HTTP fetcher. It owns its client: `async with Fetcher(config) as f: ...`.

    Given `log_db`, it logs every request to fetch_log under `run_id` (random if not given).
    """

    def __init__(
        self,
        config: Config,
        client: httpx.AsyncClient | None = None,
        *,
        concurrency: int = CONCURRENCY_PER_HOST,
        interval: float = INTERVAL,
        backoff: float = BACKOFF,
        log_db: sqlite3.Connection | None = None,
        run_id: str | None = None,
    ):
        self.config = config
        # One client for the whole run: connections are reused, and the per-host
        # semaphores keep at most `concurrency` of them busy per host.
        self._client = make_client(config) if client is None else client
        self._backoff = backoff
        self._gates: defaultdict[str, _HostGate] = defaultdict(
            lambda: _HostGate(concurrency, interval)
        )
        self._log_db = log_db
        self.run_id = run_id or uuid.uuid4().hex

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> httpx.Response:
        """GET `url`, following redirects inside the allowlist.

        Returns the last response, whatever its status, once retries are over. Raises
        DisallowedURLError for a URL or redirect outside the allowlist, httpx.TooManyRedirects,
        or the last attempt's httpx.TransportError if the host stays unreachable.
        """
        for _ in range(MAX_REDIRECTS + 1):
            if not self.config.is_allowed(url):
                raise DisallowedURLError(url)
            response = await self._get(url)
            if not response.has_redirect_location:
                return response
            url = str(response.next_request.url)  # absolute, even for a relative Location
        raise httpx.TooManyRedirects(
            f"more than {MAX_REDIRECTS} redirects", request=response.request
        )

    async def _get(self, url: str) -> httpx.Response:
        """One request, retried on timeouts, network errors, 429 and 5xx."""
        gate = self._gates[urlsplit(url).hostname]
        for attempt in range(1, MAX_ATTEMPTS + 1):
            last = attempt == MAX_ATTEMPTS
            async with gate.slots:
                await gate.turn()
                try:
                    response = await self._send(url)
                except httpx.TransportError:  # timeouts and network errors
                    if last:
                        raise
                else:
                    if last or not _retryable(response.status_code):
                        return response
                    retry_after = _retry_after(response)
                    if retry_after is not None:
                        if retry_after > MAX_RETRY_AFTER:
                            return response
                        gate.defer(retry_after)  # next attempt waits for its turn
                        continue
            # Back off outside the slot, so the other URLs of this host keep going.
            await asyncio.sleep(self._backoff * 2 ** (attempt - 1) + random.random())

    async def _send(self, url: str) -> httpx.Response:
        """The single place where a request leaves the crawler (hook for SCR-06 and SCR-07)."""
        try:
            response = await self._client.get(url, follow_redirects=False)
        except httpx.RequestError as exc:  # network errors, or a body that can't be decoded
            self._log(url, error=f"{type(exc).__name__}: {exc}")
            raise
        self._log(url, response=response)
        return response

    def _log(
        self, url: str, *, response: httpx.Response | None = None, error: str | None = None
    ) -> None:
        """Add one fetch_log row, if the fetcher has a database."""
        if self._log_db is None:
            return
        status = size = None
        if response is not None:
            status = response.status_code
            size = len(response.content)
        self._log_db.execute(
            "INSERT INTO fetch_log (run_id, url, status, error, bytes, fetched_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (self.run_id, url, status, error, size, _utc_now()),
        )
        self._log_db.commit()
