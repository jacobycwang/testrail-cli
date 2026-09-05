import json

import httpx
import pytest
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()

QUIRKS = """# Quirks

TestRail returns `custom_steps_separated` for structured cases.
Pagination caps at 250 rows per page.
"""

SEARCHING = """# Searching

Use ripgrep for local lookups.
"""


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("docs commands must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", boom)


@pytest.fixture
def docs_dir(tmp_path, monkeypatch):
    d = tmp_path / "docs"
    d.mkdir()
    (d / "quirks.md").write_text(QUIRKS)
    (d / "searching.md").write_text(SEARCHING)
    monkeypatch.setenv("TR_DOCS_DIR", str(d))
    return d


def test_list_topics(docs_dir):
    result = runner.invoke(app, ["docs"])
    assert result.exit_code == 0, result.output
    topics = json.loads(result.stdout)
    assert [t["topic"] for t in topics] == ["quirks", "searching"]
    assert topics[0]["path"].endswith("quirks.md")


def test_list_topics_empty_when_docs_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DOCS_DIR", str(tmp_path / "absent"))
    result = runner.invoke(app, ["docs"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_topic_prints_raw_markdown(docs_dir):
    result = runner.invoke(app, ["docs", "quirks"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Quirks")
    assert "custom_steps_separated" in result.stdout


def test_topic_as_json(docs_dir):
    result = runner.invoke(app, ["--json", "docs", "quirks"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["topic"] == "quirks"
    assert payload["content"] == QUIRKS


def test_unknown_topic_exits_1(docs_dir):
    result = runner.invoke(app, ["docs", "nope"])
    assert result.exit_code == 1
    assert result.stdout == ""


def test_search_returns_hits(docs_dir):
    result = runner.invoke(app, ["docs", "search", "ripgrep"])
    assert result.exit_code == 0, result.output
    hits = json.loads(result.stdout)
    assert len(hits) == 1
    assert hits[0]["topic"] == "searching"
    assert hits[0]["line"] == 3
    assert "ripgrep" in hits[0]["text"]


def test_search_is_case_insensitive(docs_dir):
    result = runner.invoke(app, ["docs", "search", "PAGINATION"])
    assert result.exit_code == 0, result.output
    hits = json.loads(result.stdout)
    assert [h["topic"] for h in hits] == ["quirks"]


def test_search_without_query_is_usage_error(docs_dir):
    result = runner.invoke(app, ["docs", "search"])
    assert result.exit_code == 2


def test_search_empty_when_docs_dir_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_DOCS_DIR", str(tmp_path / "absent"))
    result = runner.invoke(app, ["docs", "search", "anything"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []
