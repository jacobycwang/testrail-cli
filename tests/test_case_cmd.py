import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from tr.__main__ import app
from tr.cache import case_path, project_dir, write_case_md
from tr.config import load_config

runner = CliRunner()
HOST = "https://example.testrail.io"
PROJECT = 34
CASE_ID = 1042


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", str(PROJECT))


@pytest.fixture
def cached_case():
    path = case_path(project_dir(load_config(), PROJECT), CASE_ID)
    write_case_md(
        path,
        {
            "id": CASE_ID,
            "title": "Login with expired token",
            "section": "Auth/Token",
            "suite_id": 7,
            "refs": ["PAY-883", "PAY-900"],
            "last_status": "failed",
        },
        "# Steps\n1. open the login page\n   Expected: 401 with a renew hint\n",
    )
    return path


@respx.mock
def test_case_get_reads_cache_without_network(cached_case):
    result = runner.invoke(app, ["case", "get", str(CASE_ID)])
    assert result.exit_code == 0, result.output
    assert respx.calls.call_count == 0
    out = json.loads(result.stdout)
    assert out["source"] == "cache"
    assert out["id"] == CASE_ID
    assert out["title"] == "Login with expired token"
    assert out["section"] == "Auth/Token"
    assert out["refs"] == ["PAY-883", "PAY-900"]
    assert out["last_status"] == "failed"
    assert "Expected: 401 with a renew hint" in out["body"]
    assert out["path"] == str(cached_case)


@respx.mock
def test_case_get_accepts_c_prefix(cached_case):
    result = runner.invoke(app, ["case", "get", f"C{CASE_ID}"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["id"] == CASE_ID


@respx.mock
def test_case_get_missing_from_cache_exits_5():
    result = runner.invoke(app, ["case", "get", "9977"])
    assert result.exit_code == 5
    assert result.stdout == ""
    assert respx.calls.call_count == 0
    assert "tr sync" in result.stderr


@respx.mock
def test_case_get_fresh_hits_the_api_and_leaves_cache_alone():
    payload = {"id": CASE_ID, "title": "Login with expired token", "priority_id": 4}
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json=payload)
    )
    result = runner.invoke(app, ["case", "get", str(CASE_ID), "--fresh"])
    assert result.exit_code == 0, result.output
    assert f"/api/v2/get_case/{CASE_ID}" in str(route.calls[0].request.url)
    assert json.loads(result.stdout) == {"source": "api", "case": payload}
    assert not case_path(project_dir(load_config(), PROJECT), CASE_ID).exists()


@respx.mock
def test_case_get_rejects_a_non_numeric_id():
    result = runner.invoke(app, ["case", "get", "auth-token"])
    assert result.exit_code == 2
    assert respx.calls.call_count == 0
    assert "auth-token" in result.stderr


@respx.mock
def test_run_add_without_commit_sends_nothing():
    result = runner.invoke(
        app, ["run", "add", "--case-ids", "C1, 2", "--name", "Sprint 41 regression"]
    )
    assert result.exit_code == 0, result.output
    assert respx.calls.call_count == 0
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["method"] == "POST"
    assert out["url"] == f"{HOST}/index.php?/api/v2/add_run/{PROJECT}"
    assert out["body"] == {
        "name": "Sprint 41 regression",
        "include_all": False,
        "case_ids": [1, 2],
    }


@respx.mock
def test_run_add_dry_run_carries_optional_fields():
    result = runner.invoke(
        app,
        [
            "run",
            "add",
            "--case-ids",
            "1103,2044",
            "--name",
            "Payments smoke",
            "--project",
            "58",
            "--suite",
            "7",
            "--description",
            "deposit refund sweep",
            "--milestone",
            "12",
            "--refs",
            "PAY-883",
        ],
    )
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["url"].endswith("/api/v2/add_run/58")
    assert out["body"] == {
        "suite_id": 7,
        "name": "Payments smoke",
        "description": "deposit refund sweep",
        "milestone_id": 12,
        "refs": "PAY-883",
        "include_all": False,
        "case_ids": [1103, 2044],
    }


@respx.mock
def test_run_add_with_commit_posts_the_exact_body():
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 903, "name": "Sprint 41 regression"})
    )
    result = runner.invoke(
        app,
        [
            "run",
            "add",
            "--case-ids",
            "C1103, 2044",
            "--name",
            "Sprint 41 regression",
            "--suite",
            "7",
            "--commit",
        ],
    )
    assert result.exit_code == 0, result.output
    request = route.calls[0].request
    assert f"/api/v2/add_run/{PROJECT}" in str(request.url)
    assert json.loads(request.read().decode()) == {
        "suite_id": 7,
        "name": "Sprint 41 regression",
        "include_all": False,
        "case_ids": [1103, 2044],
    }
    assert json.loads(result.stdout) == {
        "dry_run": False,
        "run": {"id": 903, "name": "Sprint 41 regression"},
    }
    assert f"{HOST}/index.php?/runs/view/903" in result.stderr


@respx.mock
def test_run_add_with_empty_case_ids_is_a_usage_error():
    result = runner.invoke(app, ["run", "add", "--case-ids", "", "--name", "Empty sweep"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert respx.calls.call_count == 0
    assert "no case ids" in result.stderr.lower()


@respx.mock
def test_run_add_with_a_bad_case_id_is_a_usage_error():
    result = runner.invoke(
        app, ["run", "add", "--case-ids", "1103,PAY-883", "--name", "Bad ids"]
    )
    assert result.exit_code == 2
    assert respx.calls.call_count == 0
    assert "PAY-883" in result.stderr


@respx.mock
def test_run_add_api_error_maps_to_exit_4(no_sleep):
    respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(400, text="Field :case_ids is not a valid test case.")
    )
    result = runner.invoke(
        app, ["run", "add", "--case-ids", "1103", "--name", "Broken", "--commit"]
    )
    assert result.exit_code == 4
    assert result.stdout == ""
