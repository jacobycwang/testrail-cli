import json
import re
import shutil
import subprocess
from datetime import datetime
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


def fixture(name: str) -> dict | list:
    return json.loads((FIXTURES / f"{name}.json").read_text())


@pytest.fixture(autouse=True)
def creds(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", HOST)
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")


@pytest.fixture
def testrail(no_sleep):
    """Serve the sync fixtures and record every request URL."""
    urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        urls.append(url)
        return httpx.Response(200, json=_payload_for(url))

    with respx.mock:
        respx.get(url__startswith=f"{HOST}/index.php").mock(side_effect=handler)
        yield urls


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


def run_sync(*args: str):
    return runner.invoke(app, ["sync", "--project", str(PROJECT), "--sleep", "0", *args])


def front_matter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n")[1])


def body_of(path: Path) -> str:
    return path.read_text().split("---\n", 2)[2]


def cases_urls(urls: list[str]) -> list[str]:
    """Only the first page per suite; follow-up pages reuse the server's _links.next."""
    return [u for u in urls if f"get_cases/{PROJECT}" in u and "offset=" not in u]


def test_full_sync_writes_the_cache_layout(testrail, cache_dir):
    result = run_sync()
    assert result.exit_code == 0, result.output

    out = json.loads(result.stdout)
    project = cache_dir / str(PROJECT)
    assert out["project_id"] == PROJECT
    assert out["cases_written"] == 4
    assert out["sections"] == 3
    assert out["shared_steps"] == 1
    assert out["runs_scanned"] == 2
    assert Path(out["dir"]) == project

    assert (project / "cases" / "C1042.md").is_file()
    assert (project / "cases" / "C1043.md").is_file()
    assert (project / "cases" / "C1044.md").is_file()
    assert (project / "cases" / "C1045.md").is_file()
    assert (project / "shared_steps" / "S5.json").is_file()
    assert [s["id"] for s in json.loads((project / "sections.json").read_text())] == [10, 11, 12]

    meta = json.loads((project / "meta.json").read_text())
    assert meta["project_id"] == PROJECT
    assert meta["suites"] == {"2": "Master"}
    assert meta["sections"]["11"]["path"] == "Auth/Token"
    assert meta["sections"]["10"]["path"] == "Auth"
    assert meta["types"]["3"] == "Regression"
    assert meta["priorities"]["4"] == "High"
    assert meta["statuses"]["5"] == "failed"
    assert meta["last_sync"] == out["last_sync"]


def test_case_front_matter_matches_the_contract(testrail, cache_dir):
    assert run_sync().exit_code == 0
    meta = front_matter(cache_dir / str(PROJECT) / "cases" / "C1042.md")
    assert meta == {
        "id": 1042,
        "title": "Login with an expired refresh token",
        "section": "Auth/Token",
        "suite_id": 2,
        "type": "Regression",
        "priority": "High",
        "refs": ["PAY-883", "PAY-900"],
        "labels": [],
        "last_status": "failed",
        "updated_on": "2026-09-01T00:00:00Z",
    }


def test_shared_step_content_is_inlined(testrail, cache_dir):
    assert run_sync().exit_code == 0
    body = body_of(cache_dir / str(PROJECT) / "cases" / "C1042.md")
    assert "Open /login in a clean session" in body
    assert "Submit the seeded QA credentials" in body
    assert "Expected: The dashboard loads" in body
    assert "shared_step_id" not in body
    assert "\r" not in body
    assert "# Preconditions" in body
    assert "The refresh token is already expired" in body


def test_missing_shared_step_and_additional_info(testrail, cache_dir):
    assert run_sync().exit_code == 0
    path = cache_dir / str(PROJECT) / "cases" / "C1044.md"
    meta = front_matter(path)
    assert meta["labels"] == ["smoke"]
    assert meta["refs"] == []
    assert meta["last_status"] == "passed"
    assert meta["section"] == "Auth"
    body = body_of(path)
    assert "Info: Device B polls the session endpoint every 30s" in body
    assert "[shared step 77 not synced]" in body


def test_free_text_case_renders_steps_and_expected(testrail, cache_dir):
    assert run_sync().exit_code == 0
    path = cache_dir / str(PROJECT) / "cases" / "C1043.md"
    assert front_matter(path)["last_status"] is None
    body = body_of(path)
    assert "Open the deposit in the host portal, hit Refund, and confirm." in body
    assert "# Expected\nThe refund lands back on the original card within 5 minutes." in body


def test_runs_latest_keeps_the_newest_run_per_case(testrail, cache_dir):
    assert run_sync().exit_code == 0
    latest = json.loads((cache_dir / str(PROJECT) / "runs" / "latest.json").read_text())
    assert latest["1042"] == {"last_status": "failed", "last_run_id": 900, "last_test_id": 5001}
    assert latest["1044"] == {"last_status": "passed", "last_run_id": 880, "last_test_id": 4002}
    assert "1043" not in latest


def test_pagination_follows_the_next_link(testrail, cache_dir):
    assert run_sync().exit_code == 0
    assert any(f"get_cases/{PROJECT}" in url and "offset=2" in url for url in testrail)
    assert (cache_dir / str(PROJECT) / "cases" / "C1044.md").is_file()


def test_incremental_sync_sends_updated_after_and_keeps_old_files(testrail, cache_dir):
    assert run_sync().exit_code == 0
    project = cache_dir / str(PROJECT)
    last_sync = json.loads((project / "meta.json").read_text())["last_sync"]
    stale = project / "cases" / "C9999.md"
    stale.write_text("---\nid: 9999\n---\nold case kept by an incremental sync\n")
    testrail.clear()

    assert run_sync().exit_code == 0
    expected = int(datetime.fromisoformat(last_sync.replace("Z", "+00:00")).timestamp())
    urls = cases_urls(testrail)
    assert urls == [
        f"{HOST}/index.php?/api/v2/get_cases/34&suite_id=2&limit=250&updated_after={expected}"
    ]
    assert stale.is_file()


def test_since_overrides_the_stored_last_sync(testrail, cache_dir):
    assert run_sync().exit_code == 0
    testrail.clear()
    assert run_sync("--since", "2026-08-01T00:00:00Z").exit_code == 0
    assert all("updated_after=1785542400" in url for url in cases_urls(testrail))


def test_full_flag_drops_updated_after(testrail, cache_dir):
    assert run_sync().exit_code == 0
    testrail.clear()
    assert run_sync("--full").exit_code == 0
    assert all("updated_after" not in url for url in cases_urls(testrail))


def test_runs_zero_skips_run_requests(testrail, cache_dir):
    result = run_sync("--runs", "0")
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["runs_scanned"] == 0
    assert not any("get_runs" in url or "get_tests" in url for url in testrail)
    assert front_matter(cache_dir / str(PROJECT) / "cases" / "C1042.md")["last_status"] is None


def test_rg_finds_a_word_that_only_appears_in_a_step(testrail, cache_dir):
    if shutil.which("rg") is None:
        pytest.skip("ripgrep is not installed")
    assert run_sync().exit_code == 0
    cases = cache_dir / str(PROJECT) / "cases"
    found = subprocess.run(
        ["rg", "--files-with-matches", "invalid_grant", str(cases)],
        capture_output=True,
        text=True,
    )
    assert found.returncode == 0, found.stderr
    assert found.stdout.strip().endswith("C1042.md")
    assert "invalid_grant" not in front_matter(cases / "C1042.md")["title"]


def test_html_rich_text_is_flattened_into_the_markdown_body(testrail, cache_dir):
    assert run_sync().exit_code == 0
    body = body_of(cache_dir / str(PROJECT) / "cases" / "C1045.md")
    assert "A retired company id 4821 exists & is soft-deleted" in body
    assert "1. Request an inline API ... (e.g. GET /companies/{companyId})" in body
    assert "2. Check the resonpse http status" in body
    assert "- Status is 404" in body
    assert "Body carries company_retired" in body
    assert "# Expected\nNo stale company payload leaks to the caller" in body


def test_no_written_file_keeps_html_markup(testrail, cache_dir):
    assert run_sync().exit_code == 0
    for path in (cache_dir / str(PROJECT)).rglob("*"):
        if path.is_file():
            assert "<p>" not in path.read_text(), path


def test_rg_finds_a_word_from_inside_an_html_paragraph(testrail, cache_dir):
    if shutil.which("rg") is None:
        pytest.skip("ripgrep is not installed")
    assert run_sync().exit_code == 0
    cases = cache_dir / str(PROJECT) / "cases"
    found = subprocess.run(
        ["rg", "--files-with-matches", "companyId", str(cases)],
        capture_output=True,
        text=True,
    )
    assert found.returncode == 0, found.stderr
    assert found.stdout.strip().endswith("C1045.md")


ARCHIVED = re.compile(r"/55(&|$)")


def test_single_project_sync_never_lists_the_instance(testrail):
    assert run_sync().exit_code == 0
    assert not any("get_projects" in url for url in testrail)


def test_no_project_syncs_every_active_project(testrail, cache_dir):
    result = runner.invoke(app, ["sync", "--sleep", "0"])
    assert result.exit_code == 0, result.output

    out = json.loads(result.stdout)
    assert Path(out["dir"]) == cache_dir
    assert out["cases_written"] == 4
    assert [p["project_id"] for p in out["projects"]] == [PROJECT]
    assert out["projects"][0]["name"] == "Booking Core"
    assert out["projects"][0]["cases_written"] == 4
    assert Path(out["projects"][0]["dir"]) == cache_dir / str(PROJECT)
    assert json.loads((cache_dir / str(PROJECT) / "meta.json").read_text())["project_name"] == (
        "Booking Core"
    )


def test_completed_projects_are_never_fetched(testrail, cache_dir):
    assert runner.invoke(app, ["sync", "--sleep", "0"]).exit_code == 0
    assert not (cache_dir / "55").exists()
    assert not [url for url in testrail if ARCHIVED.search(url)]


def test_env_project_id_narrows_the_sync(testrail, cache_dir, monkeypatch):
    monkeypatch.setenv("TESTRAIL_PROJECT_ID", str(PROJECT))
    result = runner.invoke(app, ["sync", "--sleep", "0"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["project_id"] == PROJECT
    assert not any("get_projects" in url for url in testrail)


def test_config_project_id_does_not_narrow_the_sync(testrail, cache_dir, tmp_path, monkeypatch):
    config = tmp_path / "config.yml"
    config.write_text(f"host: {HOST}\nemail: qa@example.com\nproject_id: {PROJECT}\n")
    monkeypatch.setenv("TR_CONFIG", str(config))
    result = runner.invoke(app, ["sync", "--sleep", "0"])
    assert result.exit_code == 0, result.output
    assert "projects" in json.loads(result.stdout)


def test_single_project_sync_stores_the_project_name(testrail, cache_dir):
    assert run_sync().exit_code == 0
    meta = json.loads((cache_dir / str(PROJECT) / "meta.json").read_text())
    assert meta["project_name"] == "Fixture Project"
