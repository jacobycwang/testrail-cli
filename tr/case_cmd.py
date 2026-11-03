import json
import time
from pathlib import Path

import typer

from tr import case_edit
from tr.auth import get_api_key
from tr.cache import case_path, dump_json, project_dir, read_case_md
from tr.config import Config, load_config
from tr.http import APIClient, APIError, build_url
from tr.output import emit, emit_capped, fail, hint
from tr.write import add_run, build_run_payload, parse_case_id, parse_case_ids, run_view_url

case_app = typer.Typer(no_args_is_help=True, help="Read test cases from the cache or the API.")
run_app = typer.Typer(no_args_is_help=True, help="Create test runs (dry-run unless --commit).")


def _project(cfg: Config, override: int | None) -> int:
    project_id = override or cfg.project_id
    if not project_id:
        fail("no project id; pass --project or set project_id in the config", 3)
    return project_id


def _client(cfg: Config, sleep: float = 0.0) -> APIClient:
    if not cfg.host:
        fail("no TestRail host configured; run `testrail auth login` or set TESTRAIL_HOST", 3)
    if not cfg.email:
        fail("no TestRail email configured; run `testrail auth login` or set TESTRAIL_EMAIL", 3)
    return APIClient(cfg.host, cfg.email, get_api_key(cfg), sleep_s=sleep)


@case_app.command("get")
def case_get(
    case_id: str = typer.Argument(..., metavar="ID", help="Case id, e.g. 1042 or C1042"),
    fresh: bool = typer.Option(False, "--fresh", help="Read from the API instead of the cache"),
    project: int | None = typer.Option(None, "--project", help="Project id override"),
) -> None:
    """Show one test case; the cache path makes zero network calls."""
    cfg = load_config()
    try:
        ident = parse_case_id(case_id)
    except ValueError as exc:
        fail(str(exc), 2)

    if fresh:
        client = _client(cfg)
        try:
            case = client.get(f"get_case/{ident}")
        except APIError as exc:
            fail(str(exc), 4)
        except OSError as exc:
            fail(f"network error: {exc}", 4)
        finally:
            client.close()
        emit_capped({"source": "api", "case": case}, cfg)
        return

    path = case_path(project_dir(cfg, _project(cfg, project)), ident)
    if not path.is_file():
        fail(f"C{ident} is not in the cache ({path}); run `testrail sync` or retry with --fresh", 5)
    meta, body = read_case_md(path)
    emit_capped({"source": "cache", **meta, "id": ident, "body": body, "path": str(path)}, cfg)


@run_app.command("add")
def run_add(
    case_ids: str = typer.Option(..., "--case-ids", help="Case ids, e.g. 1042,C1043"),
    name: str = typer.Option(..., "--name", help="Run name"),
    project: int | None = typer.Option(None, "--project", help="Project id override"),
    suite: int | None = typer.Option(None, "--suite", help="Suite id (multi-suite projects)"),
    description: str | None = typer.Option(None, "--description", help="Run description"),
    milestone: int | None = typer.Option(None, "--milestone", help="Milestone id"),
    refs: str | None = typer.Option(None, "--refs", help="Reference keys, e.g. PAY-883"),
    commit: bool = typer.Option(False, "--commit", help="Actually create the run"),
) -> None:
    """Create a run over the given cases; prints the request unless --commit."""
    cfg = load_config()
    try:
        ids = parse_case_ids(case_ids)
    except ValueError as exc:
        fail(str(exc), 2)
    if not ids:
        fail("no case ids given; pass --case-ids 1042,1043", 2)

    project_id = _project(cfg, project)
    payload = build_run_payload(name, ids, suite, description, milestone, refs)
    uri = f"add_run/{project_id}"

    if not commit:
        emit({"dry_run": True, "method": "POST", "url": build_url(cfg.host, uri), "body": payload})
        return

    client = _client(cfg)
    try:
        run = add_run(client, project_id, payload)
    except APIError as exc:
        fail(str(exc), 4)
    except OSError as exc:
        fail(f"network error: {exc}", 4)
    finally:
        client.close()

    if isinstance(run, dict) and run.get("id"):
        hint(f"created run {run['id']}: {run_view_url(cfg.host or '', run['id'])}")
    emit_capped({"dry_run": False, "run": run}, cfg)


EDIT_SLEEP = 0.35


@case_app.command("snapshot")
def case_snapshot(
    case_ids: str | None = typer.Argument(None, metavar="[IDS]", help="Case ids, e.g. C1,C2"),
    section: int | None = typer.Option(
        None, "--section", help="Section id; takes every case in it and its subsections"
    ),
    out: Path = typer.Option(..., "--out", "-o", help="Change file to write"),
    force: bool = typer.Option(False, "--force", help="Overwrite an existing change file"),
    sleep: float = typer.Option(EDIT_SLEEP, "--sleep", help="Seconds to wait between requests"),
) -> None:
    """Write live cases to a change file; edit its `fields`, then run `case apply`."""
    if bool(case_ids) == bool(section):
        fail("pass case ids or --section, not both and not neither", 2)
    if out.exists() and not force:
        fail(f"{out} exists; it may hold unsent edits. Pick another path or pass --force", 2)
    try:
        ids = case_edit_ids(case_ids) if case_ids else []
    except ValueError as exc:
        fail(str(exc), 2)

    cfg = load_config()
    client = _client(cfg, sleep)
    summary: list[dict] = []
    try:
        if section:
            project_id, cases, summary = case_edit.snapshot_section(client, section)
        else:
            project_id, cases = case_edit.snapshot_ids(client, ids)
    except APIError as exc:
        fail(str(exc), 4)
    except OSError as exc:
        fail(f"network error: {exc}", 4)
    finally:
        client.close()

    updates = [case_edit.snapshot_entry(case) for case in cases]
    dump_json(
        out,
        {
            "snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "project_id": project_id,
            "updates": updates,
            "adds": [],
        },
    )
    report: dict = {"path": str(out), "project_id": project_id, "cases": len(updates)}
    if summary:
        report["sections"] = summary
    title_only = [entry["case_id"] for entry in updates if "note" in entry]
    if title_only:
        report["title_only"] = title_only
    emit(report)


def case_edit_ids(raw: str) -> list[int]:
    ids = parse_case_ids(raw)
    if not ids:
        raise ValueError("no case ids given")
    return ids


@case_app.command("apply")
def case_apply(
    path: Path = typer.Argument(..., metavar="FILE", help="Change file from `case snapshot`"),
    batch: int = typer.Option(1, "--batch", min=1, help="Which batch of 10 cases to write, from 1"),
    skip: str = typer.Option("", "--skip", help="Keys to leave out, e.g. C1042,A2"),
    commit: bool = typer.Option(False, "--commit", help="Actually write this batch"),
    sleep: float = typer.Option(EDIT_SLEEP, "--sleep", help="Seconds to wait between requests"),
) -> None:
    """Check a change file against TestRail and write one batch (dry-run unless --commit)."""
    if not path.is_file():
        fail(f"change file not found: {path}", 2)
    try:
        changes = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        fail(f"{path} is not valid JSON: {exc}", 2)

    cfg = load_config()
    client = _client(cfg, sleep)
    try:
        items = case_edit.build_items(changes, client)
        pending = [item for item in items if item.status != "unchanged"]
        chosen = case_edit.pick_batch(pending, batch)
        total = len(pending)
        report: dict = {
            "dry_run": not commit,
            "batch": batch,
            "batches": max(1, -(-total // case_edit.BATCH_SIZE)),
            "total": total,
            "unchanged": [item.key for item in items if item.status == "unchanged"],
        }
        if not commit:
            report["items"] = [case_edit.describe(item) for item in chosen]
            emit_capped(report, cfg)
            return
        keys = {value.strip() for value in skip.split(",") if value.strip()}
        results, backup = case_edit.apply_items(chosen, client, path, keys)
    except APIError as exc:
        fail(str(exc), 4)
    except OSError as exc:
        fail(f"network error: {exc}", 4)
    finally:
        client.close()

    report["results"] = results
    if backup:
        report["backup"] = str(backup)
    emit(report)
    if any(result["status"] == "ok" for result in results):
        project = changes.get("project_id")
        target = f"--project {project} --runs 0" if project else "--runs 0"
        hint(f"run `testrail sync {target}` to refresh the local cache")
    if any(result["status"] == "failed" for result in results):
        raise SystemExit(1)
