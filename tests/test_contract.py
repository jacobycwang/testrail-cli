"""Cross-cutting rules from the shared contract: stdout shape, offline paths, no leaks."""

import inspect
import json
import shutil
from pathlib import Path

import httpx
import pytest
import respx
import typer.main
from typer.testing import CliRunner

from tr.__main__ import app
from tr.http import APIClient, APIError

runner = CliRunner()
HOST = "https://example.testrail.io"
API_KEY = "secret-key-3391"
PROJECT = 34
CACHE_FIXTURE = Path(__file__).parent / "fixtures" / "cache"
SOURCE_DIR = Path(__file__).parent.parent / "tr"

OFFLINE_COMMANDS = [
    ["docs"],
    ["docs", "quirks"],
    ["docs", "search", "rate limit"],
    ["search", "token"],
    ["search", "token", "--failed", "--type", "Regression"],
    ["scope", "--refs", "PAY-883"],
    ["scope", "--refs", "PAY-883", "--section"],
    ["case", "get", "1042"],
]


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", API_KEY)
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", str(PROJECT))


@pytest.fixture
def cached(cache_dir):
    shutil.copytree(CACHE_FIXTURE, cache_dir, dirs_exist_ok=True)
    return cache_dir


@pytest.fixture
def no_network(monkeypatch):
    """Any real HTTP request explodes loudly instead of being caught as an APIError."""

    def explode(*args, **kwargs):
        raise RuntimeError("network call attempted")

    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", explode)


@pytest.mark.parametrize("argv", OFFLINE_COMMANDS, ids=lambda a: " ".join(a))
def test_offline_commands_make_zero_network_calls(argv, cached, no_network):
    result = runner.invoke(app, argv)
    assert result.exit_code == 0, result.output
    assert result.exception is None


@pytest.mark.parametrize("argv", OFFLINE_COMMANDS, ids=lambda a: " ".join(a))
def test_stdout_is_exactly_one_json_document(argv, cached, no_network):
    result = runner.invoke(app, ["--json", *argv])
    assert result.exit_code == 0, result.output
    json.loads(result.stdout)


def test_docs_topic_prints_raw_markdown_without_json_flag(cached, no_network):
    result = runner.invoke(app, ["docs", "quirks"])
    assert result.exit_code == 0, result.output
    assert result.stdout.startswith("# Quirks")
    assert result.stderr == ""


def test_docs_topic_with_json_flag_wraps_the_markdown(cached, no_network):
    result = runner.invoke(app, ["--json", "docs", "quirks"])
    payload = json.loads(result.stdout)
    assert payload["topic"] == "quirks"
    assert payload["content"].startswith("# Quirks")


def test_progress_hints_go_to_stderr_not_stdout(cached, no_network):
    result = runner.invoke(app, ["search", "nothing-matches-this-xyzzy"])
    assert json.loads(result.stdout) == []


def test_write_without_commit_sends_no_post(tmp_path, no_network):
    body = tmp_path / "case.json"
    body.write_text(json.dumps({"title": "Login with expired token"}))
    result = runner.invoke(app, ["api", "add_case/12", "--data", str(body)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload == {
        "dry_run": True,
        "method": "POST",
        "url": f"{HOST}/index.php?/api/v2/add_case/12",
        "body": {"title": "Login with expired token"},
    }


def test_run_add_without_commit_sends_no_post(no_network):
    result = runner.invoke(app, ["run", "add", "--case-ids", "1042,C1043", "--name", "Smoke"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["dry_run"] is True
    assert payload["method"] == "POST"
    assert payload["body"]["case_ids"] == [1042, 1043]
    assert payload["body"]["include_all"] is False


@pytest.mark.parametrize("method", ["delete_case/1042", "delete_cases/34", "delete_run/88"])
def test_delete_is_refused_even_with_commit(method, no_network):
    result = runner.invoke(app, ["api", method, "--commit"])
    assert result.exit_code == 2
    assert result.stdout == ""
    assert result.stderr.startswith("error: ")


def test_api_key_is_not_accepted_as_a_flag():
    result = runner.invoke(app, ["api", "get_case/42", "--api-key", API_KEY])
    assert result.exit_code == 2
    assert API_KEY not in result.stdout


def test_api_key_never_reaches_stdout_stderr_or_disk(cached, tmp_path, no_network):
    for argv in [*OFFLINE_COMMANDS, ["auth", "status"]]:
        result = runner.invoke(app, argv)
        assert API_KEY not in result.stdout, argv
        assert API_KEY not in result.stderr, argv
    for path in tmp_path.rglob("*"):
        if path.is_file():
            assert API_KEY.encode() not in path.read_bytes(), path


def test_auth_status_reports_the_source_and_masks_the_key(no_network):
    result = runner.invoke(app, ["auth", "status"])
    payload = json.loads(result.stdout)
    assert payload["key_source"] == "env"
    assert API_KEY not in json.dumps(payload)


@respx.mock
def test_http_errors_never_echo_request_headers(no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(401, text="Authentication failed: invalid or missing user")
    )
    result = runner.invoke(app, ["api", "get_case/42"])
    assert result.exit_code == 4
    assert result.stdout == ""
    assert API_KEY not in result.stderr
    assert "authorization" not in result.stderr.lower()


def test_transport_failure_is_a_single_error_line_not_a_traceback(no_network):
    result = runner.invoke(app, ["api", "get_case/42"])
    assert result.exit_code != 0
    assert result.stdout == ""


def test_search_and_scope_never_import_the_http_layer():
    for name in ("search.py", "scope.py"):
        source = (SOURCE_DIR / name).read_text()
        assert "tr.http" not in source, name
        assert "filter=" not in source, name


@respx.mock
def test_transport_error_becomes_exit_code_4(no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        side_effect=httpx.ConnectError("no route to host")
    )
    result = runner.invoke(app, ["api", "get_case/42"])
    assert result.exit_code == 4
    assert result.stdout == ""
    assert "error: could not reach" in result.stderr


def test_exit_code_0_on_success(cached, no_network):
    assert runner.invoke(app, ["docs"]).exit_code == 0


def test_exit_code_1_on_generic_error(no_network):
    result = runner.invoke(app, ["docs", "no-such-topic"])
    assert result.exit_code == 1
    assert result.stdout == ""


def test_exit_code_2_on_usage_error(no_network):
    assert runner.invoke(app, ["api", "get_case/1", "--query", "oops"]).exit_code == 2
    assert runner.invoke(app, ["scope"]).exit_code == 2


def test_exit_code_3_on_missing_config(monkeypatch, no_network):
    monkeypatch.delenv("TESTRAIL_HOST")
    result = runner.invoke(app, ["case", "get", "1042", "--fresh"])
    assert result.exit_code == 3
    assert result.stdout == ""


@respx.mock
def test_exit_code_4_on_api_error(no_sleep):
    respx.get(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(500, text="server error")
    )
    result = runner.invoke(app, ["api", "get_case/42"])
    assert result.exit_code == 4
    assert result.stdout == ""


def test_exit_code_5_when_the_case_is_not_cached(cached, no_network):
    result = runner.invoke(app, ["case", "get", "9999"])
    assert result.exit_code == 5
    assert result.stdout == ""


def test_paginate_hard_caps_at_50_pages_by_default(no_sleep):
    assert inspect.signature(APIClient.paginate).parameters["max_pages"].default == 50

    endless = httpx.Response(
        200,
        json={
            "size": 9999,
            "_links": {"next": "/api/v2/get_cases/34&limit=250&offset=250", "prev": None},
            "cases": [{"id": 1}],
        },
    )
    with respx.mock:
        route = respx.get(url__startswith=f"{HOST}/index.php").mock(return_value=endless)
        result = APIClient(HOST, "qa@example.com", API_KEY, sleep_s=0.0).paginate("get_cases/34")
    assert route.call_count == 50
    assert result["pages"] == 50


@pytest.mark.parametrize(
    ("retry_after", "expected"),
    [("7", 7.0), ("900", 120.0), ("not-a-number", 60.0), (None, 60.0)],
)
def test_429_honors_retry_after_capped_at_120s(retry_after, expected, no_sleep):
    headers = {} if retry_after is None else {"Retry-After": retry_after}
    with respx.mock:
        respx.get(url__startswith=f"{HOST}/index.php").mock(
            side_effect=[
                httpx.Response(429, headers=headers, text="rate limited"),
                httpx.Response(200, json={"id": 42}),
            ]
        )
        client = APIClient(HOST, "qa@example.com", API_KEY, sleep_s=0.0)
        assert client.get("get_case/42") == {"id": 42}
    assert no_sleep == [expected]


def test_api_error_message_carries_status_and_body_only():
    message = str(APIError(403, "No access to the project"))
    assert message == "TestRail returned 403: No access to the project"


@pytest.mark.parametrize(
    ("query", "topic"),
    [("TESTRAIL_HOST", "auth"), ("TR_CACHE_DIR", "auth"), ("pagination", "quirks")],
)
def test_bundled_docs_are_searchable_for_key_terms(query, topic, no_network):
    result = runner.invoke(app, ["docs", "search", query])
    assert result.exit_code == 0, result.output
    assert topic in {hit["topic"] for hit in json.loads(result.stdout)}


SKILL_MD = Path(__file__).parent.parent / "skills" / "testrail-cli" / "SKILL.md"
HELP_TARGETS = [
    ["api"],
    ["docs"],
    ["sync"],
    ["search"],
    ["scope"],
    ["case", "get"],
    ["run", "add"],
]


def _contract_block() -> str:
    return SKILL_MD.read_text().split("## Command contract")[1].split("```")[1]


def _declared_options(argv: list[str]) -> set[str]:
    command = typer.main.get_command(app)
    for name in argv:
        command = command.commands[name]
    return {opt for param in command.params for opt in param.opts if opt.startswith("--")}


@pytest.mark.parametrize("argv", HELP_TARGETS, ids=lambda a: " ".join(a))
def test_skill_md_contract_lists_every_real_option(argv):
    contract = _contract_block()
    missing = {opt for opt in _declared_options(argv) - {"--help"} if opt not in contract}
    assert not missing, f"SKILL.md contract is missing {sorted(missing)} for {' '.join(argv)}"


def test_skill_md_documents_the_refused_delete_exit_code():
    exit_codes = SKILL_MD.read_text().split("## Exit codes")[1]
    assert "delete_*" in exit_codes
    assert "2" in exit_codes
