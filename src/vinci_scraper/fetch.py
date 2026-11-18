"""Async fetcher with per-host politeness limits and retries.

Every HTTP request of the crawler goes through `Fetcher.fetch()`. Per host, at most
CONCURRENCY_PER_HOST requests are in flight and request starts are at least INTERVAL
seconds apart, retries included. Hosts are independent: run one task per URL (e.g. with
asyncio.TaskGroup) to crawl several hosts in parallel.

Timeouts, network errors, 429 and 5xx are retried with exponential backoff, or after the
delay the server asks for in Retry-After. Other responses (404 included) are never retried.
"""

import asyncio
import random
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
    """Polite HTTP fetcher. It owns its client: `async with Fetcher(config) as f: ...`."""

    def __init__(
        self,
        config: Config,
        client: httpx.AsyncClient | None = None,
        *,
        concurrency: int = CONCURRENCY_PER_HOST,
        interval: float = INTERVAL,
        backoff: float = BACKOFF,
    ):
        self.config = config
        # One client for the whole run: connections are reused, and the per-host
        # semaphores keep at most `concurrency` of them busy per host.
        self._client = make_client(config) if client is None else client
        self._backoff = backoff
        self._gates: defaultdict[str, _HostGate] = defaultdict(
            lambda: _HostGate(concurrency, interval)
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> httpx.Response:
        """GET `url`. Returns the last response, whatever its status, once retries are over.

        Raises the last attempt's httpx.TransportError if the host stays unreachable.
        """
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
        return await self._client.get(url)
