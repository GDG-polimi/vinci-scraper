from pathlib import Path

import pytest
from pydantic import ValidationError

from vinci_scraper.cli import main
from vinci_scraper.config import Config, load_config

REPO_CONFIG = Path(__file__).parent.parent / "config" / "hosts.yaml"


def make_config(**host):
    host.setdefault("allow", [{"path": "/studenti"}])
    return Config.model_validate({"hosts": {"www.polimi.it": host}})


@pytest.fixture(scope="module")
def repo_config():
    return load_config(REPO_CONFIG)


def test_repo_config_is_valid(repo_config):
    assert "www.polimi.it" in repo_config.hosts


@pytest.mark.parametrize(
    "url, frequency",
    [
        ("https://www.polimi.it/studenti", "monthly"),
        ("https://www.polimi.it/studenti/tasse-borse-e-agevolazioni/diritto-allo-studio", "weekly"),
        (
            "https://www.polimi.it/campus-e-servizi/biblioteche-e-archivi/biblioteche/news?page=2",
            "daily",
        ),
        ("https://www.polimi.it/fileadmin/user_upload/studenti/bando.pdf", "monthly"),
        ("https://www.sport.polimi.it/", "monthly"),
    ],
)
def test_repo_config_allows_tier1(repo_config, url, frequency):
    assert repo_config.frequency_for(url) == frequency


@pytest.mark.parametrize(
    "url",
    [
        "https://www.polimi.it/ricerca/progetti",  # Tier 3
        "https://www.polimi.it/typo3/login",  # robots.txt
        "https://www.polimi.it/",  # homepage itself is not a prefix
        "https://www.careerservice.polimi.it/jobs",  # disabled, pending permission
        "https://www.google.com/studenti",  # not on the allowlist
        "mailto:info@polimi.it",
    ],
)
def test_repo_config_rejects(repo_config, url):
    assert not repo_config.is_allowed(url)
    assert repo_config.frequency_for(url) is None


def test_prefix_match_is_segment_aware():
    config = make_config()
    assert config.is_allowed("https://www.polimi.it/studenti/")
    assert config.is_allowed("https://www.polimi.it/studenti/esami")
    assert not config.is_allowed("https://www.polimi.it/studenti-internazionali")


def test_host_match_is_case_insensitive_and_exact():
    config = make_config()
    assert config.is_allowed("https://WWW.POLIMI.IT/studenti")
    assert not config.is_allowed("https://polimi.it/studenti")
    assert not config.is_allowed("https://evil.www.polimi.it/studenti")


def test_deny_wins_over_allow():
    config = make_config(deny=["/studenti/privato/"])
    assert config.is_allowed("https://www.polimi.it/studenti/esami")
    assert not config.is_allowed("https://www.polimi.it/studenti/privato/x")


def test_longest_prefix_sets_frequency():
    config = make_config(
        frequency="monthly",
        allow=[{"path": "/studenti"}, {"path": "/studenti/avvisi", "frequency": "daily"}],
    )
    assert config.frequency_for("https://www.polimi.it/studenti/esami") == "monthly"
    assert config.frequency_for("https://www.polimi.it/studenti/avvisi/1") == "daily"


@pytest.mark.parametrize(
    "hosts",
    [
        {"www.polimi.it": {"allow": [{"path": "studenti"}]}},  # no leading slash
        {"www.polimi.it": {"allow": []}},  # nothing in scope
        {"www.polimi.it": {"allow": [{"path": "/"}], "frequency": "hourly"}},
        {"www.polimi.it": {"allow": [{"path": "/"}], "alow": []}},  # typo'd key
        {"https://www.polimi.it": {"allow": [{"path": "/"}]}},  # scheme in host
        {},
    ],
)
def test_invalid_config_is_rejected(hosts):
    with pytest.raises(ValidationError):
        Config.model_validate({"hosts": hosts})


def test_cli_config_check(capsys):
    url = "https://www.polimi.it/studenti/tasse-borse-e-agevolazioni"
    assert main(["config", "check", "--config", str(REPO_CONFIG), url, "https://x.org/"]) == 0
    out = capsys.readouterr().out
    assert f"ALLOW {url} (weekly)" in out
    assert "DENY  https://x.org/" in out


def test_cli_config_check_invalid(tmp_path, capsys):
    bad = tmp_path / "hosts.yaml"
    bad.write_text("hosts: {www.polimi.it: {allow: []}}\n")
    assert main(["config", "check", "--config", str(bad)]) == 1
    assert "invalid config" in capsys.readouterr().out
