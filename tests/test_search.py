import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()

FIXTURE_CACHE = Path(__file__).parent / "fixtures" / "cache"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("search must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", boom)


@pytest.fixture(autouse=True)
def fixture_cache(monkeypatch):
    monkeypatch.setenv("TR_CACHE_DIR", str(FIXTURE_CACHE))
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", "34")


def run(*args):
    result = runner.invoke(app, ["search", *args])
    return result


def ids(payload):
    return [row["id"] for row in payload]


def test_matches_a_word_that_only_appears_in_a_step():
    result = run("invalid_grant")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert ids(payload) == [1042, 1043]

    step_only = payload[0]
    assert step_only["title"] == "Login with expired token"
    assert "invalid_grant" not in step_only["title"]
    assert step_only["section"] == "Auth/Token"
    assert step_only["last_status"] == "failed"
    assert step_only["refs"] == ["PAY-883"]
    assert step_only["path"].endswith("C1042.md")
    assert [hit["line"] for hit in step_only["hits"]] == [17]
    assert step_only["hits"][0]["text"] == (
        "Expected: the response body carries error invalid_grant"
    )


def test_results_are_sorted_failed_then_priority_then_id():
    result = run("refund")
    assert result.exit_code == 0, result.output
    assert ids(json.loads(result.stdout)) == [2201, 2203, 2202]


def test_failed_case_outranks_a_high_priority_passing_case():
    result = run("token|refund")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload[0]["id"] == 1042
    assert payload[1]["id"] == 2201


def test_type_filter_is_case_insensitive():
    result = run("refund", "--type", "smoke")
    assert result.exit_code == 0, result.output
    assert ids(json.loads(result.stdout)) == [2203]


def test_refs_filter_accepts_comma_separated_keys():
    result = run(".", "--refs", "pay-883,PAY-900")
    assert result.exit_code == 0, result.output
    assert ids(json.loads(result.stdout)) == [1042, 2201, 1043]


def test_failed_filter_keeps_only_failed_cases():
    result = run(".", "--failed")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert ids(payload) == [1042]
    assert payload[0]["last_status"] == "failed"


def test_limit_truncates_after_sorting():
    result = run(".", "--limit", "2")
    assert result.exit_code == 0, result.output
    assert ids(json.loads(result.stdout)) == [1042, 2201]


def test_hits_are_deduplicated_and_text_is_capped(tmp_path, monkeypatch):
    long_line = "padding " * 60 + "needle"
    cases = tmp_path / "77" / "cases"
    cases.mkdir(parents=True)
    (cases / "C9001.md").write_text(
        "---\nid: 9001\ntitle: needle in the title\nsection: Ops/Long\n"
        "type: Smoke\npriority: Low\nrefs: []\nlast_status: null\n---\n"
        f"# Steps\n1. {long_line}\n"
    )
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path))
    result = runner.invoke(app, ["search", "needle", "--project", "77"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert len(payload) == 1
    hits = payload[0]["hits"]
    assert [hit["line"] for hit in hits] == [3, 11]
    assert len(hits[1]["text"]) == 200


def test_missing_cache_exits_5_with_a_sync_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "empty"))
    result = runner.invoke(app, ["search", "anything", "--project", "99"])
    assert result.exit_code == 5
    assert result.stdout == ""
    assert "tr sync" in result.stderr


def test_no_matches_returns_an_empty_list():
    result = run("zzz_no_such_token_zzz")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == []


def test_source_does_not_use_the_testrail_case_api():
    source = (Path(__file__).parent.parent / "tr" / "search.py").read_text()
    assert "get_cases" not in source
    assert "filter=" not in source
