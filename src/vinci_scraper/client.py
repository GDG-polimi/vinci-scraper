"""HTTP client setup: an identifiable User-Agent with a contact.

If Polimi notices our traffic, the User-Agent must tell them who we are and how to
reach us, so they can write to us instead of blocking us. Every request goes
through `make_client()`. Retries and rate limiting come in SCR-05.
"""

import os

import httpx

from vinci_scraper import __version__
from vinci_scraper.config import Config

BOT_NAME = "VINCI-bot"
REPO_URL = "https://github.com/GDG-polimi/vinci-scraper"
CONTACT_ENV = "VINCI_CONTACT"
PLACEHOLDER = "CHANGE_ME"


class MissingContactError(RuntimeError):
    pass


def resolve_contact(config: Config) -> str:
    """The contact to advertise: $VINCI_CONTACT if set, else `crawler.contact`."""
    contact = (os.environ.get(CONTACT_ENV) or config.crawler.contact).strip()
    if not contact or contact == PLACEHOLDER:
        raise MissingContactError(
            f"no crawler contact set: put an email or URL in crawler.contact "
            f"(config/hosts.yaml) or in ${CONTACT_ENV}"
        )
    return contact


def user_agent(contact: str) -> str:
    """e.g. 'VINCI-bot/0.1.0 (+https://github.com/GDG-polimi/vinci-scraper; vinci@example.org)'."""
    return f"{BOT_NAME}/{__version__} (+{REPO_URL}; {contact})"


def make_client(config: Config, **kwargs) -> httpx.AsyncClient:
    """An AsyncClient that always sends our User-Agent. Extra kwargs go to httpx."""
    headers = {**kwargs.pop("headers", {}), "User-Agent": user_agent(resolve_contact(config))}
    kwargs.setdefault("timeout", 30.0)
    kwargs.setdefault("follow_redirects", True)
    return httpx.AsyncClient(headers=headers, **kwargs)
