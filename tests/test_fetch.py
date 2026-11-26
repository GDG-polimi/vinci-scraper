import asyncio
from collections import Counter
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from itertools import pairwise

import httpx
import pytest

from vinci_scraper import db
from vinci_scraper.client import make_client
from vinci_scraper.config import Config
from vinci_scraper.fetch import BACKOFF, MAX_ATTEMPTS, MAX_REDIRECTS, DisallowedURLError, Fetcher

CONFIG = Config.model_validate(
    {
        "crawler": {"contact": "vinci@example.org"},
        "hosts": {
            "www.polimi.it": {"allow": [{"path": "/"}]},
            "www.sport.polimi.it": {"allow": [{"path": "/"}]},
        },
    }
)
URL = "https://www.polimi.it/studenti"


def run(handler, *urls, interval=0.0, **kwargs):
    """Fetch `urls` concurrently through a mock transport and return the responses."""

    async def main():
        # The production client (it follows redirects by default), on a mock transport.
        client = make_client(CONFIG, transport=httpx.MockTransport(handler))
        async with Fetcher(CONFIG, client, interval=interval, **kwargs) as fetcher:
            return await asyncio.gather(*(fetcher.fetch(url) for url in urls))

    return asyncio.run(main())


def replay(*answers):
    """A handler answering with `answers` in order: status codes, responses or exceptions."""
    answers = list(answers)

    def handler(request):
        handler.requests.append(request)
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer) if isinstance(answer, int) else answer

    handler.requests = []
    return handler


@pytest.fixture
def sleeps(monkeypatch):
    """Record the waits instead of sleeping, so retry tests take no time."""
    waits = []

    async def fake_sleep(seconds):
        waits.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    return waits


@pytest.fixture
def conn():
    """In-memory database with the schema applied."""
    conn = db.connect(":memory:")
    db.migrate(conn)
    yield conn
    conn.close()


def test_5xx_is_retried_after_backoff(sleeps):
    handler = replay(503, 200)
    (response,) = run(handler, URL)
    assert response.status_code == 200
    assert len(handler.requests) == 2
    assert BACKOFF <= sleeps[0] < BACKOFF + 1  # base delay + jitter


def test_gives_up_after_max_attempts_with_exponential_backoff(sleeps):
    handler = replay(*[500] * MAX_ATTEMPTS)
    (response,) = run(handler, URL)
    assert response.status_code == 500
    assert len(handler.requests) == MAX_ATTEMPTS
    assert [int(s) for s in sleeps] == [2, 4, 8]


@pytest.mark.parametrize("status", [200, 403, 404])
def test_other_statuses_are_not_retried(sleeps, status):
    handler = replay(status)
    (response,) = run(handler, URL)
    assert response.status_code == status
    assert len(handler.requests) == 1


def test_transport_errors_are_retried_then_raised(sleeps):
    handler = replay(*[httpx.ConnectTimeout("timed out")] * MAX_ATTEMPTS)
    with pytest.raises(httpx.ConnectTimeout):
        run(handler, URL)
    assert len(handler.requests) == MAX_ATTEMPTS


@pytest.mark.parametrize("as_date", [False, True], ids=["seconds", "http-date"])
def test_retry_after_is_honored(sleeps, as_date):
    later = datetime.now(UTC) + timedelta(seconds=8)
    value = format_datetime(later, usegmt=True) if as_date else "7"
    handler = replay(httpx.Response(429, headers={"Retry-After": value}), 200)
    (response,) = run(handler, URL)
    assert response.status_code == 200
    assert len(sleeps) == 1  # the host's turn is pushed back: no backoff on top
    assert 6 < sleeps[0] <= 8


def test_too_long_retry_after_gives_up(sleeps):
    handler = replay(httpx.Response(503, headers={"Retry-After": "300"}))
    (response,) = run(handler, URL)
    assert response.status_code == 503
    assert len(handler.requests) == 1
    assert sleeps == []


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


def test_redirects_are_followed_inside_the_allowlist():
    def handler(request):
        if request.url.path == "/old":
            return httpx.Response(301, headers={"Location": "/new"})
        return httpx.Response(200)

    (response,) = run(handler, "https://www.polimi.it/old")
    assert response.status_code == 200
    assert response.url == "https://www.polimi.it/new"


def test_redirect_outside_the_allowlist_is_never_requested():
    target = "https://www.careerservice.polimi.it/jobs"
    handler = replay(httpx.Response(302, headers={"Location": target}))
    with pytest.raises(DisallowedURLError):
        run(handler, URL)
    assert [str(request.url) for request in handler.requests] == [URL]


def test_disallowed_url_is_never_requested():
    handler = replay()
    with pytest.raises(DisallowedURLError):
        run(handler, "https://example.org/")
    assert handler.requests == []


def test_redirect_loop_stops():
    loop = httpx.Response(302, headers={"Location": "/loop"})
    handler = replay(*[loop] * (MAX_REDIRECTS + 1))
    with pytest.raises(httpx.TooManyRedirects):
        run(handler, URL)
    assert len(handler.requests) == MAX_REDIRECTS + 1


def test_responses_are_logged(conn):
    run(replay(httpx.Response(200, content=b"ciao")), URL, log_db=conn, run_id="r1")
    row = conn.execute("SELECT * FROM fetch_log").fetchone()
    assert (row["run_id"], row["url"], row["status"], row["bytes"]) == ("r1", URL, 200, 4)
    fetched_at = datetime.strptime(row["fetched_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    assert abs(datetime.now(UTC) - fetched_at) < timedelta(minutes=1)


def test_retries_and_redirects_are_logged(sleeps, conn):
    moved = httpx.Response(301, headers={"Location": "/new"})
    run(replay(503, moved, 200), URL, log_db=conn)
    rows = conn.execute("SELECT url, status FROM fetch_log ORDER BY id").fetchall()
    assert [(row["url"], row["status"]) for row in rows] == [
        (URL, 503),
        (URL, 301),
        ("https://www.polimi.it/new", 200),
    ]
