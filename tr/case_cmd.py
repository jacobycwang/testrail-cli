import typer

from tr.auth import get_api_key
from tr.cache import case_path, project_dir, read_case_md
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


def _client(cfg: Config) -> APIClient:
    if not cfg.host:
        fail("no TestRail host configured; run `testrail auth login` or set TESTRAIL_HOST", 3)
    if not cfg.email:
        fail("no TestRail email configured; run `testrail auth login` or set TESTRAIL_EMAIL", 3)
    return APIClient(cfg.host, cfg.email, get_api_key(cfg))


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
