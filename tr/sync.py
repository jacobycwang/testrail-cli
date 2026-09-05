import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import typer

from tr import cache
from tr.auth import get_api_key
from tr.config import Config, load_config
from tr.http import APIClient, APIError
from tr.output import emit, fail, hint
from tr.textutil import html_to_text

DEFAULT_SLEEP = 0.35
DEFAULT_RUNS = 5
CASE_PAGE_SIZE = 250
# sync must walk whole collections; the CLI default cap exists for ad-hoc `api` calls
SYNC_MAX_PAGES = 100_000
UNTESTED = "untested"
LIST_META_KEYS = frozenset({"_links", "offset", "limit", "size", "pages"})
REFS_SPLIT = re.compile(r"[,\s]+")
MISSING_SHARED_STEP = "[shared step {id} not synced]"


def sync(
    project: int | None = typer.Option(
        None, "--project", help="Narrow to one project; default is every active project"
    ),
    since: str | None = typer.Option(None, "--since", help="ISO 8601 lower bound for case updates"),
    runs: int = typer.Option(DEFAULT_RUNS, "--runs", help="Recent runs to scan for statuses"),
    sleep: float = typer.Option(DEFAULT_SLEEP, "--sleep", help="Seconds to wait between requests"),
    full: bool = typer.Option(False, "--full", help="Ignore the stored last_sync and refetch all"),
) -> None:
    """Flatten TestRail into the local markdown cache; every active project unless narrowed."""
    started = datetime.now(UTC).replace(microsecond=0)
    cfg = load_config()
    only = project if project is not None else cfg.env_project_id

    client = _client(cfg, sleep)
    summaries: list[dict] = []
    try:
        if only is not None:
            name = _project_name(client, only)
            summaries.append(_sync_project(client, cfg, only, name, started, since, runs, full))
        else:
            targets = _active_projects(client)
            for index, (project_id, name) in enumerate(targets, start=1):
                hint(f"[{index}/{len(targets)}] project {project_id} {name or ''}".rstrip())
                summary = _sync_project(client, cfg, project_id, name, started, since, runs, full)
                summaries.append({**summary, "name": name})
    except APIError as exc:
        fail(str(exc), 4)
    except OSError as exc:
        fail(f"network error: {exc}", 4)
    finally:
        client.close()

    if only is not None:
        emit(summaries[0])
        return
    emit(
        {
            "projects": summaries,
            "cases_written": sum(summary["cases_written"] for summary in summaries),
            "dir": str(cfg.cache_dir),
        }
    )


def _project_name(client: APIClient, project_id: int) -> str | None:
    project = client.get(f"get_project/{project_id}")
    return project.get("name") if isinstance(project, dict) else None


def _active_projects(client: APIClient) -> list[tuple[int, str | None]]:
    """Every project TestRail has not marked completed, oldest id first."""
    projects = _items(client.paginate("get_projects", max_pages=SYNC_MAX_PAGES), "projects")
    active = [p for p in projects if p.get("id") is not None and not p.get("is_completed")]
    hint(f"{len(active)} active projects of {len(projects)}")
    return [(int(p["id"]), p.get("name")) for p in active]


def _sync_project(
    client: APIClient,
    cfg: Config,
    project_id: int,
    name: str | None,
    started: datetime,
    since: str | None,
    runs: int,
    full: bool,
) -> dict:
    out_dir = cache.project_dir(cfg, project_id)
    previous = cache.load_json(out_dir / "meta.json") or {}
    updated_after = _updated_after(since, previous.get("last_sync"), full)

    meta = _reference_data(client, project_id, out_dir)
    suite_ids = [int(sid) for sid in meta["suites"]] or [None]
    cases = _fetch_cases(client, project_id, suite_ids, updated_after)
    shared_steps = _fetch_shared_steps(client, project_id, out_dir)
    latest, runs_scanned = _fetch_runs(client, project_id, runs, meta["statuses"], out_dir)

    for case in cases:
        _write_case(out_dir, case, meta, shared_steps, latest)
    hint(f"wrote {len(cases)} cases to {out_dir / 'cases'}")

    meta["last_sync"] = _iso(started)
    meta["project_id"] = project_id
    meta["project_name"] = name if name is not None else previous.get("project_name")
    cache.dump_json(out_dir / "meta.json", meta)

    return {
        "project_id": project_id,
        "cases_written": len(cases),
        "sections": len(meta["sections"]),
        "shared_steps": len(shared_steps),
        "runs_scanned": runs_scanned,
        "last_sync": meta["last_sync"],
        "dir": str(out_dir),
    }


def _client(cfg: Config, sleep: float) -> APIClient:
    if not cfg.host:
        fail("no TestRail host configured; run `testrail auth login` or set TESTRAIL_HOST", 3)
    if not cfg.email:
        fail("no TestRail email configured; run `testrail auth login` or set TESTRAIL_EMAIL", 3)
    return APIClient(cfg.host, cfg.email, get_api_key(cfg), sleep_s=sleep)


def _updated_after(since: str | None, last_sync: str | None, full: bool) -> int | None:
    if since:
        return int(_parse_iso(since).timestamp())
    if full or not last_sync:
        return None
    return int(_parse_iso(last_sync).timestamp())


def _parse_iso(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        fail(f"not an ISO 8601 timestamp: {value!r}", 2)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _iso(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso_from_epoch(value: Any) -> str | None:
    try:
        return _iso(datetime.fromtimestamp(int(value), UTC))
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _items(payload: Any, key: str) -> list[dict]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    value = payload.get(key)
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    for name, other in payload.items():
        if name not in LIST_META_KEYS and isinstance(other, list):
            return [item for item in other if isinstance(item, dict)]
    return []


def _named(payload: Any, key: str) -> dict[str, str]:
    return {str(item["id"]): item.get("name") for item in _items(payload, key) if "id" in item}


def _reference_data(client: APIClient, project_id: int, out_dir: Path) -> dict:
    suites = _items(client.get(f"get_suites/{project_id}"), "suites")
    types = _named(client.get("get_case_types"), "case_types")
    priorities = _named(client.get("get_priorities"), "priorities")
    statuses = _named(client.get("get_statuses"), "statuses")

    # Multi-suite-mode projects reject get_sections without suite_id even when
    # they hold a single suite, so always scope by suite when one exists.
    sections: list[dict] = []
    if suites:
        for suite in suites:
            sections += _items(
                client.paginate(
                    f"get_sections/{project_id}",
                    {"suite_id": suite["id"]},
                    max_pages=SYNC_MAX_PAGES,
                ),
                "sections",
            )
    else:
        sections = _items(
            client.paginate(f"get_sections/{project_id}", max_pages=SYNC_MAX_PAGES), "sections"
        )

    cache.dump_json(out_dir / "sections.json", sections)
    hint(f"{len(suites)} suites, {len(sections)} sections")
    return {
        "project_id": project_id,
        "suites": {str(s["id"]): s.get("name") for s in suites if "id" in s},
        "sections": _section_map(sections),
        "types": types,
        "priorities": priorities,
        "statuses": statuses,
    }


def _section_map(sections: list[dict]) -> dict[str, dict]:
    by_id = {str(s["id"]): s for s in sections if "id" in s}
    mapped: dict[str, dict] = {}
    for key, section in by_id.items():
        mapped[key] = {
            "name": section.get("name"),
            "parent_id": section.get("parent_id"),
            "suite_id": section.get("suite_id"),
            "path": _section_path(key, by_id),
        }
    return mapped


def _section_path(section_id: str, by_id: dict[str, dict]) -> str:
    names: list[str] = []
    seen: set[str] = set()
    current: str | None = section_id
    while current and current in by_id and current not in seen:
        seen.add(current)
        names.append(str(by_id[current].get("name") or current))
        parent = by_id[current].get("parent_id")
        current = str(parent) if parent is not None else None
    return "/".join(reversed(names))


def _fetch_cases(
    client: APIClient, project_id: int, suite_ids: list[int | None], updated_after: int | None
) -> list[dict]:
    cases: list[dict] = []
    for suite_id in suite_ids:
        params: dict[str, Any] = {"limit": CASE_PAGE_SIZE}
        if suite_id is not None:
            params = {"suite_id": suite_id, **params}
        if updated_after is not None:
            params["updated_after"] = updated_after
        cases += _items(
            client.paginate(f"get_cases/{project_id}", params, max_pages=SYNC_MAX_PAGES), "cases"
        )
    hint(f"fetched {len(cases)} cases")
    return cases


def _fetch_shared_steps(client: APIClient, project_id: int, out_dir: Path) -> dict[int, dict]:
    steps = _items(
        client.paginate(f"get_shared_steps/{project_id}", max_pages=SYNC_MAX_PAGES), "shared_steps"
    )
    shared = {}
    for step in steps:
        step_id = step.get("id")
        if step_id is None:
            continue
        shared[int(step_id)] = step
        cache.dump_json(out_dir / "shared_steps" / f"S{step_id}.json", step)
    hint(f"fetched {len(shared)} shared steps")
    return shared


def _fetch_runs(
    client: APIClient, project_id: int, limit: int, statuses: dict[str, str], out_dir: Path
) -> tuple[dict, int]:
    latest_path = out_dir / "runs" / "latest.json"
    if limit <= 0:
        return cache.load_json(latest_path) or {}, 0

    runs = _items(
        client.paginate(f"get_runs/{project_id}", {"is_completed": 0}, max_pages=SYNC_MAX_PAGES),
        "runs",
    )
    runs += _items(
        client.paginate(f"get_runs/{project_id}", {"is_completed": 1}, max_pages=SYNC_MAX_PAGES),
        "runs",
    )
    runs.sort(key=lambda run: run.get("created_on") or 0, reverse=True)
    recent = runs[:limit]

    latest: dict[str, dict] = {}
    for run in recent:
        run_id = run.get("id")
        for test in _items(
            client.paginate(f"get_tests/{run_id}", max_pages=SYNC_MAX_PAGES), "tests"
        ):
            case_id = test.get("case_id")
            status = statuses.get(str(test.get("status_id")))
            if case_id is None or not status or status == UNTESTED or str(case_id) in latest:
                continue
            latest[str(case_id)] = {
                "last_status": status,
                "last_run_id": run_id,
                "last_test_id": test.get("id"),
            }

    cache.dump_json(latest_path, latest)
    hint(f"scanned {len(recent)} runs, {len(latest)} cases with a status")
    return latest, len(recent)


def _write_case(
    out_dir: Path, case: dict, meta: dict, shared_steps: dict[int, dict], latest: dict
) -> None:
    case_id = case.get("id")
    if case_id is None:
        return
    section = meta["sections"].get(str(case.get("section_id"))) or {}
    status = latest.get(str(case_id)) or {}
    front = {
        "id": case_id,
        "title": _text(case.get("title")),
        "section": section.get("path"),
        "suite_id": case.get("suite_id"),
        "type": meta["types"].get(str(case.get("type_id"))),
        "priority": meta["priorities"].get(str(case.get("priority_id"))),
        "refs": _split_refs(case.get("refs")),
        "labels": _labels(case.get("labels")),
        "last_status": status.get("last_status"),
        "updated_on": _iso_from_epoch(case.get("updated_on")),
    }
    cache.write_case_md(cache.case_path(out_dir, case_id), front, _render_body(case, shared_steps))


def _text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).replace("\r\n", "\n").replace("\r", "\n")


def _rich(value: Any) -> str:
    """Rich-text fields arrive as HTML on newer cases and as plain text on older ones."""
    return html_to_text(_text(value))


def _split_refs(refs: Any) -> list[str]:
    return [ref for ref in REFS_SPLIT.split(_text(refs).strip()) if ref]


def _labels(labels: Any) -> list[str]:
    if not isinstance(labels, list):
        return []
    return [str(item.get("title") if isinstance(item, dict) else item) for item in labels]


def _render_body(case: dict, shared_steps: dict[int, dict]) -> str:
    body = f"# Preconditions\n{_rich(case.get('custom_preconds')).strip()}\n\n# Steps\n"
    steps = _expand_steps(case.get("custom_steps_separated"), shared_steps)
    if steps:
        body += "".join(_step_block(n, step) for n, step in enumerate(steps, start=1))
    else:
        free_text = _rich(case.get("custom_steps")).strip()
        if free_text:
            body += f"{free_text}\n"
    expected = _rich(case.get("custom_expected")).strip()
    if expected:
        body += f"\n# Expected\n{expected}\n"
    return body


def _expand_steps(raw: Any, shared_steps: dict[int, dict]) -> list[dict]:
    if not isinstance(raw, list):
        return []
    steps: list[dict] = []
    for step in raw:
        if not isinstance(step, dict):
            continue
        shared_id = step.get("shared_step_id")
        if shared_id is None:
            steps.append(step)
            continue
        shared = shared_steps.get(int(shared_id))
        nested = shared.get("custom_steps_separated") if isinstance(shared, dict) else None
        if isinstance(nested, list) and nested:
            steps += [item for item in nested if isinstance(item, dict)]
        else:
            steps.append({"content": MISSING_SHARED_STEP.format(id=shared_id)})
    return steps


def _step_block(index: int, step: dict) -> str:
    block = f"{index}. {_rich(step.get('content')).strip()}\n"
    expected = _rich(step.get("expected")).strip()
    if expected:
        block += f"   Expected: {expected}\n"
    info = _rich(step.get("additional_info")).strip()
    if info:
        block += f"   Info: {info}\n"
    return block
