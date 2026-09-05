import json
from pathlib import Path

import httpx
import pytest
import respx

from tr.http import APIClient
from tr.write import (
    add_results_for_cases,
    add_run,
    build_run_payload,
    parse_case_id,
    parse_case_ids,
    run_view_url,
)

HOST = "https://example.testrail.io"


def json_body(request: httpx.Request) -> object:
    return json.loads(request.read().decode())


def client() -> APIClient:
    return APIClient(HOST, "qa@example.com", "secret-key-3391")


def test_parse_case_ids_accepts_prefixes_and_separators():
    assert parse_case_ids("C1103, 2044  C77") == [1103, 2044, 77]


def test_parse_case_ids_on_blank_input_is_empty():
    assert parse_case_ids("  ") == []


@pytest.mark.parametrize("raw", ["abc", "C", "10.5", "-42"])
def test_parse_case_id_rejects_non_integers(raw):
    with pytest.raises(ValueError):
        parse_case_id(raw)


def test_build_run_payload_omits_missing_fields():
    payload = build_run_payload("Sprint 41 regression", [1103, 2044])
    assert payload == {
        "name": "Sprint 41 regression",
        "include_all": False,
        "case_ids": [1103, 2044],
    }


def test_build_run_payload_keeps_provided_fields():
    payload = build_run_payload(
        "Payments smoke",
        [881, 902],
        suite_id=7,
        description="deposit refund sweep",
        milestone_id=12,
        refs="PAY-883",
    )
    assert payload == {
        "suite_id": 7,
        "name": "Payments smoke",
        "description": "deposit refund sweep",
        "milestone_id": 12,
        "refs": "PAY-883",
        "include_all": False,
        "case_ids": [881, 902],
    }


@respx.mock
def test_add_run_posts_payload_to_project():
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json={"id": 903})
    )
    payload = build_run_payload("Sprint 41 regression", [1103, 2044], suite_id=7)
    assert add_run(client(), 34, payload) == {"id": 903}
    request = route.calls[0].request
    assert "/api/v2/add_run/34" in str(request.url)
    assert json_body(request) == payload


@respx.mock
def test_add_results_for_cases_wraps_results():
    route = respx.post(url__startswith=f"{HOST}/index.php").mock(
        return_value=httpx.Response(200, json=[{"id": 5501}])
    )
    results = [
        {"case_id": 1103, "status_id": 5, "comment": "timeout on refund"},
        {"case_id": 2044, "status_id": 1},
    ]
    assert add_results_for_cases(client(), 812, results) == [{"id": 5501}]
    request = route.calls[0].request
    assert "/api/v2/add_results_for_cases/812" in str(request.url)
    assert json_body(request) == {"results": results}


def test_run_view_url_uses_host():
    assert run_view_url(HOST, 903) == f"{HOST}/index.php?/runs/view/903"


@pytest.mark.parametrize("module", ["tr/write.py", "tr/case_cmd.py"])
def test_modules_never_mention_deletion(module):
    assert "delete" not in Path(module).read_text().lower()
