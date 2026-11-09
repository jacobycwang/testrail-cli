import json

import httpx
import pytest
import respx
from typer.testing import CliRunner

from tr.__main__ import app

runner = CliRunner()
HOST = "https://example.testrail.io"
API = f"{HOST}/index.php?/api/v2/"


@pytest.fixture(autouse=True)
def creds(monkeypatch, no_sleep):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")


def live_case(**overrides):
    case = {
        "id": 1042,
        "title": "Login with expired token",
        "section_id": 12,
        "template_id": 1,
        "priority_id": 2,
        "version": 3,
        "updated_on": 100,
        "custom_preconds": "<p>User exists.</p>",
        "custom_steps": "<ol><li>Open login</li></ol>",
        "custom_expected": "<ol><li>old</li></ol>",
        "suite_id": 5,
    }
    return {**case, **overrides}


def route_get(name, payload):
    return respx.get(url__startswith=f"{API}{name}").mock(
        return_value=httpx.Response(200, json=payload)
    )


def snapshot_to(path, *args):
    route_get("get_suite/5", {"id": 5, "project_id": 15})
    result = runner.invoke(app, ["case", "snapshot", *args, "-o", str(path)])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout), json.loads(path.read_text())


def edit(path, case_index=0, **fields):
    changes = json.loads(path.read_text())
    changes["updates"][case_index]["fields"].update(fields)
    path.write_text(json.dumps(changes))


def apply(path, *args):
    return runner.invoke(app, ["case", "apply", str(path), *args])


@respx.mock
def test_snapshot_ids_keeps_before_and_an_editable_copy(tmp_path):
    route_get("get_case/1042", live_case())
    report, changes = snapshot_to(tmp_path / "c.json", "C1042")
    entry = changes["updates"][0]
    assert report["cases"] == 1 and changes["project_id"] == 15
    assert entry["base_version"] == 3 and entry["base_updated_on"] == 100
    assert entry["before"] == entry["fields"]
    assert entry["before"]["custom_expected"] == "<ol><li>old</li></ol>"


@respx.mock
def test_snapshot_limits_other_templates_to_the_title(tmp_path):
    route_get("get_case/7", live_case(id=7, template_id=7))
    report, changes = snapshot_to(tmp_path / "c.json", "7")
    assert list(changes["updates"][0]["fields"]) == ["title"]
    assert report["title_only"] == [7]


@respx.mock
def test_snapshot_section_walks_subsections_and_counts_them(tmp_path):
    route_get("get_section/10", {"id": 10, "suite_id": 5, "name": "Root", "depth": 1})
    route_get("get_suite/5", {"id": 5, "project_id": 15})
    route_get(
        "get_sections/15",
        {
            "sections": [
                {"id": 9, "parent_id": None, "name": "Other", "depth": 0},
                {"id": 10, "parent_id": 9, "name": "Root", "depth": 1},
                {"id": 11, "parent_id": 10, "name": "Child", "depth": 2},
            ]
        },
    )
    respx.get(url__regex=r".*get_cases/15.*section_id=10").mock(
        return_value=httpx.Response(200, json={"cases": [live_case(id=1)]})
    )
    respx.get(url__regex=r".*get_cases/15.*section_id=11").mock(
        return_value=httpx.Response(200, json={"cases": [live_case(id=2), live_case(id=3)]})
    )
    report, changes = snapshot_to(tmp_path / "c.json", "--section", "10")
    assert [s["cases"] for s in report["sections"]] == [1, 2]
    assert [u["case_id"] for u in changes["updates"]] == [1, 2, 3]


def test_snapshot_refuses_to_overwrite_edits(tmp_path):
    path = tmp_path / "c.json"
    path.write_text("{}")
    result = runner.invoke(app, ["case", "snapshot", "1", "-o", str(path)])
    assert result.exit_code == 2
    assert path.read_text() == "{}"


@respx.mock
def test_apply_dry_run_sends_only_edited_fields_and_writes_nothing(tmp_path):
    path = tmp_path / "c.json"
    route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    edit(path, custom_expected="<ol><li>new</li></ol>")
    result = apply(path)
    assert result.exit_code == 0, result.output
    item = json.loads(result.stdout)["items"][0]
    assert item["status"] == "ready"
    assert list(item["diff"]) == ["custom_expected"]
    assert item["diff"]["custom_expected"] == ["-<li>old</li>", "+<li>new</li>"]
    assert all(call.request.method == "GET" for call in respx.calls)


@respx.mock
def test_apply_unedited_case_is_unchanged_without_a_request(tmp_path):
    path = tmp_path / "c.json"
    route = route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    calls = route.call_count
    out = json.loads(apply(path).stdout)
    assert out["unchanged"] == ["C1042"] and out["items"] == [] and out["remaining"] == 0
    assert route.call_count == calls


@respx.mock
def test_apply_blocks_a_case_changed_since_the_snapshot(tmp_path):
    path = tmp_path / "c.json"
    route = route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    edit(path, custom_expected="new")
    route.mock(return_value=httpx.Response(200, json=live_case(version=4, updated_on=200)))
    out = json.loads(apply(path).stdout)
    assert out["items"] == [] and out["remaining"] == 0
    assert out["blocked"][0]["status"] == "conflict"


@respx.mock
def test_apply_rerun_after_write_is_unchanged_not_conflict(tmp_path):
    path = tmp_path / "c.json"
    route = route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    edit(path, custom_expected="new")
    route.mock(
        return_value=httpx.Response(
            200, json=live_case(version=4, updated_on=200, custom_expected="new")
        )
    )
    assert json.loads(apply(path).stdout)["unchanged"] == ["C1042"]


@respx.mock
def test_apply_commit_backs_up_writes_and_verifies(tmp_path):
    path = tmp_path / "c.json"
    route = route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    edit(path, custom_expected="new")
    post = respx.post(url__startswith=f"{API}update_case/1042").mock(
        return_value=httpx.Response(200, json=live_case(custom_expected="new"))
    )
    route.mock(
        side_effect=[
            httpx.Response(200, json=live_case()),
            httpx.Response(200, json=live_case(version=4, custom_expected="new")),
        ]
    )
    result = apply(path, "--commit")
    assert result.exit_code == 0, result.output
    out = json.loads(result.stdout)
    assert out["results"] == [{"key": "C1042", "status": "ok"}]
    assert json.loads(post.calls[0].request.read()) == {"custom_expected": "new"}
    backup = json.loads(open(out["backup"]).read())
    assert backup[0]["before"] == {"custom_expected": "<ol><li>old</li></ol>"}
    assert "testrail sync --project 15 --runs 0" in result.stderr


@respx.mock
def test_apply_skip_leaves_the_case_alone(tmp_path):
    path = tmp_path / "c.json"
    route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    edit(path, custom_expected="new")
    post = respx.post(url__startswith=API).mock(return_value=httpx.Response(200, json={}))
    out = json.loads(apply(path, "--commit", "--skip", "C1042").stdout)
    assert out["skipped"] == ["C1042"] and out["results"] == []
    assert post.call_count == 0
    assert "backup" not in out


@respx.mock
def test_apply_batches_ten_with_critical_first(tmp_path):
    path = tmp_path / "c.json"
    updates = []
    for case_id in range(1, 13):
        priority = 4 if case_id == 12 else 2
        case = live_case(id=case_id, priority_id=priority)
        respx.get(url=f"{API}get_case/{case_id}").mock(
            return_value=httpx.Response(200, json=case)
        )
        updates.append(
            {
                "case_id": case_id,
                "base_version": 3,
                "base_updated_on": 100,
                "before": {"title": case["title"]},
                "fields": {"title": f"New {case_id}"},
            }
        )
    path.write_text(json.dumps({"updates": updates, "adds": []}))
    first = json.loads(apply(path).stdout)
    assert first["batches"] == 2 and first["remaining"] == 12 and len(first["items"]) == 10
    assert first["items"][0]["key"] == "C12"
    for item in first["items"]:
        case_id = int(item["key"][1:])
        written = live_case(id=case_id, title=f"New {case_id}", version=4, updated_on=200)
        respx.get(url=f"{API}get_case/{case_id}").mock(
            return_value=httpx.Response(200, json=written)
        )
    second = json.loads(apply(path).stdout)
    assert second["remaining"] == 2 and second["batches"] == 1
    assert sorted(item["key"] for item in second["items"]) == ["C10", "C11"]


def add_change(**overrides):
    fields = {
        "title": "New case",
        "template_id": 1,
        "type_id": 6,
        "priority_id": 2,
        "custom_preconds": "p",
        "custom_steps": "s",
        "custom_expected": "e",
    }
    return {"section_id": 12, "fields": {**fields, **overrides}}


def mock_section(cases_after_add):
    route_get("get_section/12", {"id": 12, "suite_id": 5})
    route_get("get_suite/5", {"id": 5, "project_id": 15})
    return respx.get(url__startswith=f"{API}get_cases/15").mock(
        side_effect=[httpx.Response(200, json={"cases": c}) for c in cases_after_add]
    )


@respx.mock
def test_apply_add_blocks_a_duplicate_title(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"updates": [], "adds": [add_change()]}))
    mock_section([[{"id": 5, "title": "New case"}]])
    item = json.loads(apply(path).stdout)["blocked"][0]
    assert item["key"] == "A1" and item["status"] == "duplicate"


@respx.mock
def test_apply_add_reports_duplicates_created_by_a_retry(tmp_path):
    path = tmp_path / "c.json"
    path.write_text(json.dumps({"updates": [], "adds": [add_change()]}))
    mock_section([[], [{"id": 900, "title": "New case"}, {"id": 901, "title": "New case"}]])
    respx.post(url__startswith=f"{API}add_case/12").mock(
        return_value=httpx.Response(200, json={"id": 900})
    )
    result = apply(path, "--commit")
    assert result.exit_code == 1
    note = json.loads(result.stdout)["results"][0]["note"]
    assert "900" in note and "901" in note


@respx.mock
def test_apply_add_missing_field_is_invalid(tmp_path):
    path = tmp_path / "c.json"
    change = add_change()
    del change["fields"]["custom_steps"]
    path.write_text(json.dumps({"updates": [], "adds": [change]}))
    assert json.loads(apply(path).stdout)["blocked"][0]["status"] == "invalid"


@respx.mock
def test_apply_commit_reports_unchanged_cases_as_unchanged(tmp_path):
    path = tmp_path / "c.json"
    route_get("get_case/1042", live_case())
    snapshot_to(path, "1042")
    out = json.loads(apply(path, "--commit").stdout)
    assert out["results"] == [] and out["unchanged"] == ["C1042"]


@respx.mock
def test_apply_batches_count_only_cases_to_write(tmp_path):
    path = tmp_path / "c.json"
    updates = []
    for case_id in range(1, 16):
        case = live_case(id=case_id)
        respx.get(url=f"{API}get_case/{case_id}").mock(return_value=httpx.Response(200, json=case))
        edited = case["title"] if case_id > 3 else f"New {case_id}"
        updates.append(
            {
                "case_id": case_id,
                "base_version": 3,
                "base_updated_on": 100,
                "before": {"title": case["title"]},
                "fields": {"title": edited},
            }
        )
    path.write_text(json.dumps({"updates": updates, "adds": []}))
    out = json.loads(apply(path).stdout)
    assert out["batches"] == 1 and out["remaining"] == 3
    assert len(out["unchanged"]) == 12


@respx.mock
def test_apply_skipped_case_does_not_take_a_batch_slot(tmp_path):
    path = tmp_path / "c.json"
    updates = []
    for case_id in range(1, 12):
        respx.get(url=f"{API}get_case/{case_id}").mock(
            return_value=httpx.Response(200, json=live_case(id=case_id))
        )
        updates.append(
            {
                "case_id": case_id,
                "base_version": 3,
                "base_updated_on": 100,
                "before": {"title": "Login with expired token"},
                "fields": {"title": f"New {case_id}"},
            }
        )
    path.write_text(json.dumps({"updates": updates, "adds": []}))
    out = json.loads(apply(path, "--skip", "C1").stdout)
    assert out["skipped"] == ["C1"] and out["remaining"] == 10
    assert "C1" not in [item["key"] for item in out["items"]] and len(out["items"]) == 10


@respx.mock
def test_apply_add_blocks_a_title_repeated_within_the_file(tmp_path):
    path = tmp_path / "c.json"
    adds = [
        add_change(title="Refund after partial capture", priority_id=3),
        add_change(title="Refund after partial capture", priority_id=2),
        add_change(title="Void before settlement"),
    ]
    path.write_text(json.dumps({"updates": [], "adds": adds}))
    mock_section([[{"id": 77, "title": "Older case"}]] * 3)
    out = json.loads(apply(path).stdout)
    assert [item["key"] for item in out["items"]] == ["A1", "A3"]
    assert [(item["key"], item["status"]) for item in out["blocked"]] == [("A2", "duplicate")]
    assert "A1" in out["blocked"][0]["note"]


@respx.mock
def test_apply_network_error_mid_batch_keeps_earlier_results(tmp_path):
    path = tmp_path / "c.json"
    updates = []
    for case_id in (2207, 3318):
        case = live_case(id=case_id)
        respx.get(url=f"{API}get_case/{case_id}").mock(
            side_effect=[
                httpx.Response(200, json=case),
                httpx.Response(200, json=live_case(id=case_id, title=f"Renamed {case_id}")),
            ]
        )
        updates.append(
            {
                "case_id": case_id,
                "base_version": 3,
                "base_updated_on": 100,
                "before": {"title": case["title"]},
                "fields": {"title": f"Renamed {case_id}"},
            }
        )
    path.write_text(json.dumps({"updates": updates, "adds": []}))
    respx.post(url=f"{API}update_case/2207").mock(return_value=httpx.Response(200, json={}))
    respx.post(url=f"{API}update_case/3318").mock(side_effect=httpx.ConnectError("reset"))
    result = apply(path, "--commit")
    assert result.exit_code == 1
    out = json.loads(result.stdout)
    assert [(r["key"], r["status"]) for r in out["results"]] == [
        ("C2207", "ok"),
        ("C3318", "failed"),
    ]
    assert out["backup"]
