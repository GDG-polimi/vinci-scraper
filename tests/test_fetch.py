import asyncio
from collections import Counter
from itertools import pairwise

import httpx

from vinci_scraper.config import Config
from vinci_scraper.fetch import Fetcher

CONFIG = Config.model_validate(
    {
        "hosts": {
            "www.polimi.it": {"allow": [{"path": "/"}]},
            "www.sport.polimi.it": {"allow": [{"path": "/"}]},
        }
    }
)
URL = "https://www.polimi.it/studenti"


def run(handler, *urls, interval=0.0, **kwargs):
    """Fetch `urls` concurrently through a mock transport and return the responses."""

    async def main():
        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        async with Fetcher(CONFIG, client, interval=interval, **kwargs) as fetcher:
            return await asyncio.gather(*(fetcher.fetch(url) for url in urls))

    return asyncio.run(main())


def test_per_host_concurrency_limit_with_hosts_in_parallel():
    active, peak = Counter(), Counter()

    async def handler(request):
        host = request.url.host
        active[host] += 1
        peak[host] = max(peak[host], active[host])
        peak["total"] = max(peak["total"], active.total())
        await asyncio.sleep(0.02)
        active[host] -= 1
        return httpx.Response(200)

    hosts = ["www.polimi.it", "www.sport.polimi.it"]
    run(handler, *(f"https://{host}/{i}" for host in hosts for i in range(5)))
    assert peak == {"www.polimi.it": 2, "www.sport.polimi.it": 2, "total": 4}


def test_request_starts_are_spaced_per_host():
    starts = []

    def handler(request):
        starts.append(asyncio.get_running_loop().time())
        return httpx.Response(200)

    run(handler, *(f"{URL}/{i}" for i in range(4)), interval=0.05)
    gaps = [b - a for a, b in pairwise(starts)]
    assert len(gaps) == 3
    assert all(gap >= 0.045 for gap in gaps)  # small margin for timer resolution
