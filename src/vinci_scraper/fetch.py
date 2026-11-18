"""Async fetcher with per-host politeness limits.

Every HTTP request of the crawler goes through `Fetcher.fetch()`. Per host, at most
CONCURRENCY_PER_HOST requests are in flight and request starts are at least INTERVAL
seconds apart. Hosts are independent: run one task per URL (e.g. with asyncio.TaskGroup)
to crawl several hosts in parallel.
"""

import asyncio
from collections import defaultdict
from typing import Self
from urllib.parse import urlsplit

import httpx

from vinci_scraper.client import make_client
from vinci_scraper.config import Config

CONCURRENCY_PER_HOST = 2
INTERVAL = 1.0  # seconds between request starts on the same host


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


class Fetcher:
    """Polite HTTP fetcher. It owns its client: `async with Fetcher(config) as f: ...`."""

    def __init__(
        self,
        config: Config,
        client: httpx.AsyncClient | None = None,
        *,
        concurrency: int = CONCURRENCY_PER_HOST,
        interval: float = INTERVAL,
    ):
        self.config = config
        # One client for the whole run: connections are reused, and the per-host
        # semaphores keep at most `concurrency` of them busy per host.
        self._client = make_client(config) if client is None else client
        self._gates: defaultdict[str, _HostGate] = defaultdict(
            lambda: _HostGate(concurrency, interval)
        )

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info) -> None:
        await self._client.aclose()

    async def fetch(self, url: str) -> httpx.Response:
        gate = self._gates[urlsplit(url).hostname]
        async with gate.slots:
            await gate.turn()
            return await self._send(url)

    async def _send(self, url: str) -> httpx.Response:
        """The single place where a request leaves the crawler (hook for SCR-06 and SCR-07)."""
        return await self._client.get(url)
