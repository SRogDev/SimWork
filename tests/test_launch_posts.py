"""Guards for docs/launch-posts.md — the launch drafts Roger posts.

The drafts must stay honest: install from git (PyPI is not published),
docs-site link only once it is live, no invented traction, and every
X post within the 280-character limit.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
LAUNCH_POSTS = REPO_ROOT / "docs" / "launch-posts.md"


@pytest.fixture(scope="module")
def text() -> str:
    return LAUNCH_POSTS.read_text(encoding="utf-8")


def _x_posts(text: str) -> list[str]:
    """The six X posts: text after each ``**Post N:**`` marker."""
    section = text.split("## 1. X — thread", 1)[1]
    section = section.split("## 2. Reddit", 1)[0]
    posts = []
    for chunk in re.split(r"\*\*Post \d+:\*\*\n", section)[1:]:
        paragraph = chunk.strip().split("\n\n", 1)[0].strip()
        posts.append(paragraph)
    return posts


def test_file_exists() -> None:
    assert LAUNCH_POSTS.is_file()


def test_all_four_drafts_present(text: str) -> None:
    assert "## 1. X — thread" in text
    assert "## 2. Reddit — r/LocalLLaMA" in text
    assert "## 3. Reddit — r/Python" in text
    assert "## 4. Hacker News — Show HN" in text


def test_six_x_posts(text: str) -> None:
    assert len(_x_posts(text)) == 6


def test_x_posts_within_character_limit(text: str) -> None:
    for post in _x_posts(text):
        assert len(post) <= 280, f"X post over 280 chars ({len(post)}): {post!r}"


def test_install_is_from_git_not_pypi(text: str) -> None:
    assert "pip install git+https://github.com/SRogDev/SimWork" in text
    # The only bare `pip install simwork` mention must be the honest
    # "does not resolve" note — never an install instruction.
    mentions = [line for line in text.splitlines() if "pip install simwork" in line]
    assert len(mentions) == 1
    assert "does not resolve" in mentions[0]


def test_no_docs_site_link_until_live(text: str) -> None:
    # The domain may be named in the "do not link it yet" note, but no
    # draft may link to it until the deploy is live.
    assert "https://simwork.vercel.app" not in text


def test_no_invented_traction(text: str) -> None:
    # No numeric traction claim (stars / users / downloads). The words may
    # appear in the posting notes ("do not add ... figures that do not
    # exist"), but never attached to a number.
    assert not re.search(r"\d[\d,]*\s+(stars|users|downloads)\b", text, re.IGNORECASE)
    assert "1,000 stars" not in text


def test_verified_numbers_present(text: str) -> None:
    assert "325 tests" in text
    assert "1000/1000" in text
    assert "42.6s" in text
    assert "$0" in text


def test_honest_limit_stated(text: str) -> None:
    assert "not real reasoning quality" in text


def test_repo_link_present(text: str) -> None:
    assert "https://github.com/SRogDev/SimWork" in text
