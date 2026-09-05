"""One pass through the real pipeline: sync writes the cache, search/scope/case get read it."""

import json
from pathlib import Path

import httpx
import pytest
import respx
import yaml
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()
HOST = "https://example.testrail.io"
FIXTURES = Path(__file__).parent / "fixtures" / "sync"
PROJECT = 34
FRONT_MATTER_KEYS = [
    "id",
    "title",
    "section",
    "suite_id",
    "type",
    "priority",
    "refs",
    "labels",
    "last_status",
    "updated_on",
]


def fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / f"{name}.json").read_text())


def _payload_for(url: str) -> dict | list:
    if "get_projects" in url:
        return fixture("projects")
    if f"get_project/{PROJECT}" in url:
        return {"id": PROJECT, "name": "Fixture Project", "is_completed": False}
    if f"get_suites/{PROJECT}" in url:
        return fixture("suites")
    if "get_case_types" in url:
        return fixture("case_types")
    if "get_priorities" in url:
        return fixture("priorities")
    if "get_statuses" in url:
        return fixture("statuses")
    if f"get_sections/{PROJECT}" in url:
        return fixture("sections")
    if f"get_shared_steps/{PROJECT}" in url:
        return fixture("shared_steps")
    if f"get_runs/{PROJECT}" in url:
        return fixture("runs_open" if "is_completed=0" in url else "runs_completed")
    if "get_tests/900" in url:
        return fixture("tests_run900")
    if "get_tests/880" in url:
        return fixture("tests_run880")
    if f"get_cases/{PROJECT}" in url:
        return fixture("cases_page2" if "offset=2" in url else "cases_page1")
    raise AssertionError(f"unmocked request: {url}")


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", str(PROJECT))


@pytest.fixture
def synced(cache_dir, monkeypatch, no_sleep):
    """Run a real `testrail sync` against mocked endpoints, then forbid any further network call."""
    with respx.mock:
        respx.get(url__startswith=f"{HOST}/index.php").mock(
            side_effect=lambda request: httpx.Response(200, json=_payload_for(str(request.url)))
        )
        result = runner.invoke(app, ["sync", "--project", str(PROJECT), "--sleep", "0"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["cases_written"] == 4

    def explode(*args, **kwargs):
        raise RuntimeError("network call attempted after sync")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", explode)
    return cache_dir / str(PROJECT)


def invoke(*argv: str) -> dict | list:
    result = runner.invoke(app, list(argv))
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_sync_writes_the_front_matter_keys_the_readers_expect(synced):
    for case_id in (1042, 1043, 1044):
        text = (synced / "cases" / f"C{case_id}.md").read_text()
        meta = yaml.safe_load(text.split("---\n")[1])
        assert list(meta) == FRONT_MATTER_KEYS, case_id


def test_search_reads_what_sync_wrote(synced):
    hits = invoke("search", "refresh token")
    assert [hit["id"] for hit in hits] == [1042]
    assert hits[0] == {
        "id": 1042,
        "title": "Login with an expired refresh token",
        "section": "Auth/Token",
        "type": "Regression",
        "priority": "High",
        "refs": ["PAY-883", "PAY-900"],
        "last_status": "failed",
        "path": str(synced / "cases" / "C1042.md"),
        "project": PROJECT,
        "project_name": "Fixture Project",
        "hits": hits[0]["hits"],
    }
    assert hits[0]["hits"]


def test_search_without_a_project_still_finds_the_synced_one(synced, monkeypatch):
    monkeypatch.delenv("TESTRAIL_PROJECT_ID")
    hits = invoke("search", "refresh token")
    assert [hit["id"] for hit in hits] == [1042]
    assert hits[0]["project"] == PROJECT


def test_search_filters_agree_with_the_synced_metadata(synced):
    assert [hit["id"] for hit in invoke("search", "the", "--type", "Regression")] == [1042]
    assert [hit["id"] for hit in invoke("search", "the", "--failed")] == [1042]
    assert [hit["id"] for hit in invoke("search", "the", "--refs", "pay-900")] == [1042]


def test_scope_reads_what_sync_wrote(synced):
    result = invoke("scope", "--refs", "PAY-883")
    assert result["case_ids"] == [1042]
    assert result["reasons"] == {"1042": ["ref:PAY-883", "failed"]}
    assert result["refs"] == ["PAY-883"]


def test_scope_section_expansion_uses_the_synced_section_paths(synced):
    result = invoke("scope", "--refs", "PAY-883", "--section")
    assert result["case_ids"] == [1042]
    assert result["reasons"]["1042"] == ["ref:PAY-883", "section:Auth/Token", "failed"]


def test_case_get_reads_what_sync_wrote(synced):
    case = invoke("case", "get", "C1042")
    assert case["source"] == "cache"
    assert case["id"] == 1042
    assert case["section"] == "Auth/Token"
    assert case["suite_id"] == 2
    assert case["type"] == "Regression"
    assert case["priority"] == "High"
    assert case["refs"] == ["PAY-883", "PAY-900"]
    assert case["labels"] == []
    assert case["last_status"] == "failed"
    assert case["updated_on"].endswith("Z")
    assert "Open /login in a clean session" in case["body"]


def test_unrun_and_passed_cases_carry_the_status_sync_derived(synced):
    assert invoke("case", "get", "1043")["last_status"] is None
    passed = invoke("case", "get", "1044")
    assert passed["last_status"] == "passed"
    assert passed["labels"] == ["smoke"]
