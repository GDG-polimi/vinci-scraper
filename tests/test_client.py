import asyncio

import httpx
import pytest

from vinci_scraper import __version__
from vinci_scraper.client import (
    CONTACT_ENV,
    MissingContactError,
    make_client,
    resolve_contact,
    user_agent,
)
from vinci_scraper.config import Config


def make_config(contact=None):
    data = {"hosts": {"www.polimi.it": {"allow": [{"path": "/"}]}}}
    if contact is not None:
        data["crawler"] = {"contact": contact}
    return Config.model_validate(data)


@pytest.fixture(autouse=True)
def no_env_contact(monkeypatch):
    monkeypatch.delenv(CONTACT_ENV, raising=False)


def test_user_agent_format():
    assert user_agent("vinci@example.org") == (
        f"VINCI-bot/{__version__} (+https://github.com/GDG-polimi/vinci-scraper; vinci@example.org)"
    )


@pytest.mark.parametrize("contact", [None, "CHANGE_ME", "", "  "])
def test_missing_contact_is_refused(contact):
    with pytest.raises(MissingContactError):
        resolve_contact(make_config(contact))
    with pytest.raises(MissingContactError):
        make_client(make_config(contact))


def test_env_overrides_config(monkeypatch):
    monkeypatch.setenv(CONTACT_ENV, "env@example.org")
    assert resolve_contact(make_config("cfg@example.org")) == "env@example.org"
    assert resolve_contact(make_config()) == "env@example.org"


def test_client_sends_user_agent():
    seen = {}

    def handler(request):
        seen["ua"] = request.headers["User-Agent"]
        return httpx.Response(200)

    async def fetch():
        client = make_client(
            make_config("vinci@example.org"),
            transport=httpx.MockTransport(handler),
            headers={"User-Agent": "something-else"},
        )
        async with client:
            await client.get("https://www.polimi.it/")

    asyncio.run(fetch())
    assert seen["ua"] == user_agent("vinci@example.org")
