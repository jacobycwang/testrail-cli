import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import typer

from tr.cache import cached_project_dirs, project_dir, project_name, read_case_md
from tr.config import Config, load_config
from tr.output import emit, fail, hint, set_json

DEFAULT_LIMIT = 30
MAX_TEXT = 200
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
UNRANKED_PRIORITY = 3


def resolve_project(cfg: Config, project: int | None) -> int | None:
    """`--project` wins, then TESTRAIL_PROJECT_ID, else None meaning every cached project.

    config.yml `project_id` is deliberately ignored here: sync/search/scope are instance-wide.
    """
    return project if project is not None else cfg.env_project_id


def require_cases_dir(cfg: Config, project_id: int) -> Path:
    directory = project_dir(cfg, project_id) / "cases"
    if not directory.is_dir():
        hint("run `testrail sync` first to populate the local case cache")
        fail(f"no cached cases for project {project_id}", 5)
    return directory


def cases_dirs_for(cfg: Config, project: int | None) -> list[Path]:
    """The `cases/` dirs a read command should scan: one project, or all of them."""
    narrowed = resolve_project(cfg, project)
    if narrowed is not None:
        return [require_cases_dir(cfg, narrowed)]
    dirs = [directory / "cases" for directory in cached_project_dirs(cfg)]
    if not dirs:
        hint("run `testrail sync` first to populate the local case cache")
        fail(f"no cached projects under {cfg.cache_dir}", 5)
    return dirs


def case_project(path: Path | str) -> int:
    return int(Path(path).parent.parent.name)


def rg_hits(
    pattern: str, cases_dirs: Sequence[Path], whole_word: bool = False
) -> dict[str, list[dict]]:
    """Map case file path -> deduplicated {line, text} hits for pattern, across every dir."""
    cmd = ["rg", "--json", "-i", "-g", "C*.md"]
    if whole_word:
        cmd.append("-w")
    cmd += ["--", pattern, *(str(directory) for directory in cases_dirs)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        fail("ripgrep (rg) is not on PATH; install it to use `testrail search`", 1)
    if proc.returncode not in (0, 1):
        fail(f"rg failed: {proc.stderr.strip()}", 1)

    hits: dict[str, list[dict]] = {}
    seen: dict[str, set[int]] = {}
    for raw in proc.stdout.splitlines():
        try:
            event = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        data = event["data"]
        path = data.get("path", {}).get("text")
        line_number = data.get("line_number")
        if not path or line_number is None:
            continue
        if line_number in seen.setdefault(path, set()):
            continue
        seen[path].add(line_number)
        text = data.get("lines", {}).get("text", "").strip()[:MAX_TEXT]
        hits.setdefault(path, []).append({"line": line_number, "text": text})
    return hits


def case_record(path: str, hits: list[dict], names: dict[str, str | None]) -> dict | None:
    meta, _ = read_case_md(Path(path))
    if not meta:
        return None
    home = Path(path).parent.parent
    if str(home) not in names:
        names[str(home)] = project_name(home)
    return {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "section": meta.get("section"),
        "type": meta.get("type"),
        "priority": meta.get("priority"),
        "refs": meta.get("refs") or [],
        "last_status": meta.get("last_status"),
        "path": path,
        "project": case_project(path),
        "project_name": names[str(home)],
        "hits": hits,
    }


def split_keys(raw: str | None) -> set[str]:
    if not raw:
        return set()
    return {part.strip().lower() for part in raw.split(",") if part.strip()}


def keep_record(record: dict, case_type: str | None, refs: set[str], failed_only: bool) -> bool:
    if case_type and str(record["type"] or "").lower() != case_type.strip().lower():
        return False
    if refs and not {str(ref).lower() for ref in record["refs"]} & refs:
        return False
    if failed_only and record["last_status"] != "failed":
        return False
    return True


def rank_key(record: dict) -> tuple[int, int, int, int]:
    failed = 0 if record["last_status"] == "failed" else 1
    priority = PRIORITY_ORDER.get(str(record["priority"] or "").lower(), UNRANKED_PRIORITY)
    return failed, priority, record["project"], int(record["id"] or 0)


def search_cases(
    query: str,
    cases_dirs: Sequence[Path],
    case_type: str | None = None,
    refs: set[str] | None = None,
    failed_only: bool = False,
) -> list[dict]:
    records = []
    names: dict[str, str | None] = {}
    for path, hits in rg_hits(query, cases_dirs).items():
        record = case_record(path, hits, names)
        if record and keep_record(record, case_type, refs or set(), failed_only):
            records.append(record)
    records.sort(key=rank_key)
    return records


def search(
    query: str = typer.Argument(..., help="Regex matched against cached case files"),
    case_type: str | None = typer.Option(None, "--type", help="Keep only this case type"),
    refs: str | None = typer.Option(None, "--refs", help="Comma-separated ticket keys"),
    failed: bool = typer.Option(False, "--failed", help="Keep only cases whose last run failed"),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Maximum results"),
    project: int | None = typer.Option(
        None, "--project", help="Narrow to one project; default is every cached project"
    ),
    json_output: bool = typer.Option(False, "--json", help="Force JSON output (already default)"),
) -> None:
    """Search the synced case cache with ripgrep (offline)."""
    set_json(json_output)
    cfg = load_config()
    records = search_cases(
        query, cases_dirs_for(cfg, project), case_type, split_keys(refs), failed
    )
    emit(records[:limit])
