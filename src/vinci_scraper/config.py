"""Per-host crawl configuration, loaded from YAML (config/hosts.yaml).

The listed hosts form the global allowlist: `Config.is_allowed()` is the single
check every component must call before following a link.
"""

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import yaml
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator

DEFAULT_CONFIG = Path("config/hosts.yaml")

Frequency = Literal["daily", "weekly", "monthly"]


class _Model(BaseModel):
    # Reject unknown keys so a typo in the YAML fails loudly instead of being ignored.
    model_config = ConfigDict(extra="forbid", frozen=True)


def _normalize_path(path: str) -> str:
    if not path.startswith("/"):
        raise ValueError(f"path prefix must start with '/': {path!r}")
    return path.rstrip("/") or "/"


def _path_matches(path: str, prefix: str) -> bool:
    """Segment-aware prefix match: /studenti matches /studenti/esami, not /studenti-x."""
    return prefix == "/" or path == prefix or path.startswith(prefix + "/")


class Prefix(_Model):
    path: str
    frequency: Frequency | None = None  # None: use the host default

    _check_path = field_validator("path")(_normalize_path)


class HostConfig(_Model):
    enabled: bool = True
    render: Literal["http", "browser"] = "http"
    sitemaps: list[HttpUrl] = []
    content_selector: str | None = None
    frequency: Frequency = "monthly"
    allow: list[Prefix] = Field(min_length=1)
    deny: list[str] = []

    @field_validator("deny")
    @classmethod
    def _check_deny(cls, value: list[str]) -> list[str]:
        return [_normalize_path(p) for p in value]

    def match(self, path: str) -> Prefix | None:
        """The longest allowed prefix covering `path`, or None if out of scope or denied."""
        path = path or "/"
        if any(_path_matches(path, d) for d in self.deny):
            return None
        candidates = [p for p in self.allow if _path_matches(path, p.path)]
        return max(candidates, key=lambda p: len(p.path), default=None)


class CrawlerConfig(_Model):
    # Shown in the User-Agent so Polimi can reach us instead of blocking us (SCR-03).
    # Can be overridden with the VINCI_CONTACT environment variable.
    contact: str = "CHANGE_ME"


class Config(_Model):
    crawler: CrawlerConfig = CrawlerConfig()
    hosts: dict[str, HostConfig] = Field(min_length=1)

    @field_validator("hosts")
    @classmethod
    def _check_hosts(cls, value: dict[str, HostConfig]) -> dict[str, HostConfig]:
        for name in value:
            if name != name.lower() or "/" in name or ":" in name:
                raise ValueError(f"host must be a bare lowercase hostname: {name!r}")
        return value

    def _resolve(self, url: str) -> tuple[HostConfig, Prefix] | None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return None
        host = self.hosts.get(parts.hostname)
        if host is None or not host.enabled:
            return None
        prefix = host.match(parts.path)
        return (host, prefix) if prefix else None

    def is_allowed(self, url: str) -> bool:
        """True if `url` is on an enabled allowlisted host and inside an allowed prefix."""
        return self._resolve(url) is not None

    def frequency_for(self, url: str) -> Frequency | None:
        """Re-crawl frequency for `url`, or None if it is not allowed."""
        resolved = self._resolve(url)
        if resolved is None:
            return None
        host, prefix = resolved
        return prefix.frequency or host.frequency


def load_config(path: str | Path = DEFAULT_CONFIG) -> Config:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return Config.model_validate(data)
