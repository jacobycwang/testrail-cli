import json
from pathlib import Path

import httpx
import pytest
import respx
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()
HOST = "https://example.testrail.io"


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")


@respx.mock
def test_get_case_performs_request_and_prints_json():
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 42, "title": "Expired token"})
    )
    result = runner.invoke(app, ["api", "get_case/42"])
    assert result.exit_code == 0, result.output
    assert route.called
    assert json.loads(result.stdout) == {"id": 42, "title": "Expired token"}
    assert "/api/v2/get_case/42" in str(route.calls[0].request.url)


@respx.mock
def test_get_with_query_flag_appends_params():
    route = respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json=[])
    )
    result = runner.invoke(app, ["api", "get_cases/34", "--query", "suite_id=7,limit=250"])
    assert result.exit_code == 0, result.output
    url = str(route.calls[0].request.url)
    assert "suite_id=7" in url
    assert "limit=250" in url


@respx.mock
def test_write_without_commit_makes_no_request(tmp_path):
    payload = tmp_path / "run.json"
    payload.write_text(json.dumps({"name": "regression sweep", "case_ids": [11, 12]}))
    result = runner.invoke(app, ["api", "add_run/1", "--data", str(payload)])
    assert result.exit_code == 0, result.output
    assert respx.calls.call_count == 0
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["method"] == "POST"
    assert out["body"] == {"name": "regression sweep", "case_ids": [11, 12]}
    assert "add_run/1" in out["url"]


@respx.mock
def test_write_with_commit_posts(tmp_path):
    payload = tmp_path / "run.json"
    payload.write_text(json.dumps({"name": "regression sweep"}))
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 903})
    )
    result = runner.invoke(app, ["api", "add_run/1", "--data", str(payload), "--commit"])
    assert result.exit_code == 0, result.output
    assert route.called
    assert json.loads(result.stdout) == {"id": 903}


@respx.mock
def test_delete_method_is_refused_with_exit_2():
    result = runner.invoke(app, ["api", "delete_case/1", "--commit"])
    assert result.exit_code == 2
    assert respx.calls.call_count == 0
    assert result.stdout == ""


@respx.mock
def test_get_dry_run_makes_no_request():
    result = runner.invoke(app, ["api", "get_case/1", "--dry-run"])
    assert result.exit_code == 0, result.output
    assert respx.calls.call_count == 0
    out = json.loads(result.stdout)
    assert out["dry_run"] is True
    assert out["method"] == "GET"


@respx.mock
def test_large_response_spills_to_last_json(tmp_path, monkeypatch):
    cache = tmp_path / "spill-cache"
    monkeypatch.setenv("TR_CACHE_DIR", str(cache))
    big = [{"id": i, "title": "x" * 200} for i in range(700)]
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json=big)
    )
    result = runner.invoke(app, ["api", "get_cases/34"])
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["truncated"] is True
    assert out["bytes"] > 64 * 1024
    spilled = Path(out["path"])
    assert spilled == cache / "last.json"
    assert json.loads(spilled.read_text()) == big


@respx.mock
def test_paginate_on_write_method_is_usage_error():
    result = runner.invoke(app, ["api", "add_run/1", "--paginate", "--commit"])
    assert result.exit_code == 2
    assert respx.calls.call_count == 0


@respx.mock
def test_api_error_maps_to_exit_4(no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(400, text="Field :case_id is not a valid test case.")
    )
    result = runner.invoke(app, ["api", "get_case/999999"])
    assert result.exit_code == 4
    assert result.stdout == ""


@respx.mock
def test_data_from_stdin(tmp_path):
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 5})
    )
    result = runner.invoke(
        app,
        ["api", "add_run/1", "--data", "-", "--commit"],
        input=json.dumps({"name": "from stdin"}),
    )
    assert result.exit_code == 0, result.output
    assert json.loads(route.calls[0].request.content) == {"name": "from stdin"}
