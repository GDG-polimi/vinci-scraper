import pytest

from vinci_scraper.canonical import canonical_url, dedup_key


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        (
            "https://www.polimi.it/news?utm_source=ig&utm_medium=social",
            "https://www.polimi.it/news",
        ),
        ("https://www.polimi.it/news?fbclid=AbC123", "https://www.polimi.it/news"),
        ("https://www.polimi.it/news?gclid=xyz", "https://www.polimi.it/news"),
    ],
)
def test_tracking_parameters_are_removed(url, expected):
    assert canonical_url(url) == expected


@pytest.mark.parametrize(
    "url",
    [
        "https://www.polimi.it/news?page=2",
        "https://www.polimi.it/studenti?L=1",
        "https://www.polimi.it/news?id=4",
        "https://www.polimi.it/cerca?q=tasse%20universitarie",
        "https://www.polimi.it/x?path=/a/b",
    ],
)
def test_content_parameters_are_kept(url):
    assert canonical_url(url) == url


def test_host_is_lowercased_but_not_the_path():
    assert canonical_url("HTTPS://WWW.Polimi.it/Studenti") == "https://www.polimi.it/Studenti"


def test_fragment_is_removed():
    assert canonical_url("https://www.polimi.it/studenti#tasse") == "https://www.polimi.it/studenti"


def test_blank_parameters_are_kept():
    assert canonical_url("https://www.polimi.it/cerca?q=") == "https://www.polimi.it/cerca?q="


def test_empty_pairs_are_dropped():
    url = "https://www.polimi.it/news?id=4&utm_source=ig&"
    assert dedup_key(url) == "https://www.polimi.it/news?id=4"


def test_chash_is_kept_for_fetching_but_not_for_dedup():
    url = "https://www.polimi.it/news?id=4&cHash=ab12"
    assert canonical_url(url) == url
    assert dedup_key(url) == "https://www.polimi.it/news?id=4"


def test_variants_of_the_same_page_share_one_key():
    variants = [
        "https://www.polimi.it/news?id=4",
        "https://www.polimi.it/news?id=4&cHash=ab12",
        "https://www.polimi.it/news?id=4&utm_source=ig#top",
        "HTTPS://WWW.POLIMI.IT/news?id=4&fbclid=AbC123",
    ]
    assert len({dedup_key(u) for u in variants}) == 1


def test_different_pages_keep_different_keys():
    assert dedup_key("https://www.polimi.it/news?page=1") != dedup_key(
        "https://www.polimi.it/news?page=2"
    )
