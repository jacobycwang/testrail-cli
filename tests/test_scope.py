import json
from pathlib import Path

import httpx
import pytest
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()

FIXTURE_CACHE = Path(__file__).parent / "fixtures" / "cache"
SAMPLE_DIFF = Path(__file__).parent / "fixtures" / "diff" / "sample.diff"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("scope must not touch the network")

    monkeypatch.setattr(httpx.Client, "send", boom)


@pytest.fixture(autouse=True)
def fixture_cache(monkeypatch):
    monkeypatch.setenv("TR_CACHE_DIR", str(FIXTURE_CACHE))
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", "34")


def run(*args, **kwargs):
    return runner.invoke(app, ["scope", *args], **kwargs)


def test_refs_collect_every_case_carrying_the_ticket():
    result = run("--refs", "PAY-883")
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["case_ids"] == [1042, 2201]
    assert payload["refs"] == ["PAY-883"]
    assert payload["terms"] == []
    assert payload["reasons"]["2201"] == ["ref:PAY-883"]


def test_failed_case_is_ranked_first():
    payload = json.loads(run("--refs", "PAY-883").stdout)
    assert payload["case_ids"][0] == 1042
    assert payload["reasons"]["1042"] == ["ref:PAY-883", "failed"]


def test_refs_are_matched_case_insensitively():
    payload = json.loads(run("--refs", "pay-900").stdout)
    assert payload["case_ids"] == [1043]


def test_diff_yields_path_function_and_ticket_terms():
    result = run("--diff", str(SAMPLE_DIFF))
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["terms"] == ["token_service", "refresh_token", "rotate"]
    assert payload["refs"] == ["PAY-900"]
    assert payload["case_ids"] == [1043, 1044]
    assert payload["reasons"]["1044"] == ["term:refresh_token", "term:token_service"]
    assert payload["reasons"]["1043"] == ["ref:PAY-900"]


def test_diff_can_be_read_from_stdin():
    payload = json.loads(run("--diff", "-", input=SAMPLE_DIFF.read_text()).stdout)
    assert payload["case_ids"] == [1043, 1044]


def test_section_expands_to_sibling_cases():
    payload = json.loads(run("--refs", "PAY-883", "--section").stdout)
    assert payload["case_ids"] == [1042, 2201, 1043, 2202, 1044, 2203]
    assert payload["reasons"]["1042"] == [
        "ref:PAY-883",
        "section:Auth/Token",
        "failed",
    ]
    assert payload["reasons"]["2203"] == ["section:Payments/Refund"]


def test_failed_flag_drops_everything_that_did_not_fail():
    payload = json.loads(run("--refs", "PAY-883", "--section", "--failed").stdout)
    assert payload["case_ids"] == [1042]


def test_limit_truncates_after_ranking():
    payload = json.loads(run("--refs", "PAY-883", "--section", "--limit", "2").stdout)
    assert payload["case_ids"] == [1042, 2201]
    assert set(payload["reasons"]) == {"1042", "2201"}


def test_common_words_are_ignored_and_terms_are_capped(tmp_path):
    lines = ["--- a/src/main.py", "+++ b/src/main.py"]
    lines += ["+    import utils  # index test"]
    lines += [f"+    identifier_{n:03d} = 1" for n in range(60)]
    diff = tmp_path / "big.diff"
    diff.write_text("\n".join(lines) + "\n")
    payload = json.loads(run("--diff", str(diff)).stdout)
    assert len(payload["terms"]) == 40
    assert "main" not in payload["terms"]
    assert "utils" not in payload["terms"]
    assert "index" not in payload["terms"]
    assert "test" not in payload["terms"]


def test_without_diff_or_refs_is_a_usage_error():
    result = run()
    assert result.exit_code == 2
    assert result.stdout == ""
    assert "--diff" in result.stderr


def test_missing_cache_exits_5_with_a_sync_hint(tmp_path, monkeypatch):
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "empty"))
    result = run("--refs", "PAY-883", "--project", "99")
    assert result.exit_code == 5
    assert result.stdout == ""
    assert "testrail sync" in result.stderr


def test_unknown_ticket_returns_empty_scope():
    payload = json.loads(run("--refs", "NOPE-1").stdout)
    assert payload["case_ids"] == []
    assert payload["reasons"] == {}
