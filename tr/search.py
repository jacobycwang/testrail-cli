import json
import subprocess
from pathlib import Path

import typer

from tr.cache import project_dir, read_case_md
from tr.config import Config, load_config
from tr.output import emit, fail, hint, set_json

DEFAULT_LIMIT = 30
MAX_TEXT = 200
PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}
UNRANKED_PRIORITY = 3


def resolve_project(cfg: Config, project: int | None) -> int:
    project_id = project if project is not None else cfg.project_id
    if project_id is None:
        fail("no project id; set project_id in config or pass --project", 3)
    return project_id


def require_cases_dir(cfg: Config, project_id: int) -> Path:
    directory = project_dir(cfg, project_id) / "cases"
    if not directory.is_dir():
        hint("run `tr sync` first to populate the local case cache")
        fail(f"no cached cases for project {project_id}", 5)
    return directory


def rg_hits(pattern: str, cases_dir: Path, whole_word: bool = False) -> dict[str, list[dict]]:
    """Map case file path -> deduplicated {line, text} hits for pattern."""
    cmd = ["rg", "--json", "-i", "-g", "C*.md"]
    if whole_word:
        cmd.append("-w")
    cmd += ["--", pattern, str(cases_dir)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        fail("ripgrep (rg) is not on PATH; install it to use `tr search`", 1)
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


def case_record(path: str, hits: list[dict]) -> dict | None:
    meta, _ = read_case_md(Path(path))
    if not meta:
        return None
    return {
        "id": meta.get("id"),
        "title": meta.get("title"),
        "section": meta.get("section"),
        "type": meta.get("type"),
        "priority": meta.get("priority"),
        "refs": meta.get("refs") or [],
        "last_status": meta.get("last_status"),
        "path": path,
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


def rank_key(record: dict) -> tuple[int, int, int]:
    failed = 0 if record["last_status"] == "failed" else 1
    priority = PRIORITY_ORDER.get(str(record["priority"] or "").lower(), UNRANKED_PRIORITY)
    return failed, priority, int(record["id"] or 0)


def search_cases(
    query: str,
    cases_dir: Path,
    case_type: str | None = None,
    refs: set[str] | None = None,
    failed_only: bool = False,
) -> list[dict]:
    records = []
    for path, hits in rg_hits(query, cases_dir).items():
        record = case_record(path, hits)
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
    project: int | None = typer.Option(None, "--project", help="Project id override"),
    json_output: bool = typer.Option(False, "--json", help="Force JSON output (already default)"),
) -> None:
    """Search the synced case cache with ripgrep. Never touches the network."""
    set_json(json_output)
    cfg = load_config()
    cases_dir = require_cases_dir(cfg, resolve_project(cfg, project))
    records = search_cases(query, cases_dir, case_type, split_keys(refs), failed)
    emit(records[:limit])
