"""Community surface: CONTRIBUTING.md, README link, docs-site page.

The adoption plan (v0.2 §3 step 4) calls for a community surface so
contributors can see where to help: a CONTRIBUTING.md, a README section
pointing at it, and a docs-site page. These tests guard that the three
stay in place and stay consistent — a missing or empty contributing
guide is a broken front door, not a cosmetic gap.
"""

from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
CONTRIBUTING = REPO_ROOT / "CONTRIBUTING.md"
README = REPO_ROOT / "README.md"
DOCS_PAGE = REPO_ROOT / "docs-site" / "src" / "content" / "docs" / "reference" / "contributing.md"
ASTRO_CONFIG = REPO_ROOT / "docs-site" / "astro.config.mjs"


@pytest.fixture(scope="module")
def contributing_text():
    return CONTRIBUTING.read_text(encoding="utf-8")


def test_contributing_exists_and_is_substantive(contributing_text):
    assert CONTRIBUTING.is_file()
    assert len(contributing_text.splitlines()) >= 40


def test_contributing_documents_dev_setup(contributing_text):
    assert "uv sync" in contributing_text
    assert "pytest" in contributing_text
    assert "ruff check" in contributing_text


def test_contributing_documents_hard_gates(contributing_text):
    # The $0 default, no secrets, and the spec-as-constitution rule are
    # the gates every contribution must respect.
    assert "$0" in contributing_text
    assert "no secrets" in contributing_text.lower()
    assert "spec" in contributing_text.lower()


def test_contributing_documents_small_prs_and_readme(contributing_text):
    assert "good first issue" in contributing_text
    assert "README" in contributing_text


def test_readme_links_to_contributing():
    readme = README.read_text(encoding="utf-8")
    assert "CONTRIBUTING.md" in readme
    assert "## Contributing" in readme


def test_docs_site_has_contributing_page_and_sidebar_entry():
    assert DOCS_PAGE.is_file()
    page = DOCS_PAGE.read_text(encoding="utf-8")
    assert "CONTRIBUTING.md" in page
    config = ASTRO_CONFIG.read_text(encoding="utf-8")
    assert "reference/contributing" in config
