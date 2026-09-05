import json
import sys
from pathlib import Path

import typer

from tr.auth import get_api_key
from tr.config import Config, load_config
from tr.http import APIClient, APIError, build_url
from tr.output import emit, emit_capped, fail

REFUSED_PREFIX = "delete"


def parse_query(pairs: list[str] | None) -> dict[str, str]:
    """k=v[,k2=v2]; a comma piece without '=' extends the previous value (status_id=4,5)."""
    params: dict[str, str] = {}
    last_key: str | None = None
    for chunk in pairs or []:
        for item in chunk.split(","):
            item = item.strip()
            if not item:
                continue
            if "=" not in item:
                if last_key is None:
                    fail(f"bad --query item {item!r}; expected k=v", 2)
                params[last_key] += f",{item}"
                continue
            key, _, value = item.partition("=")
            last_key = key.strip()
            params[last_key] = value
    return params


def load_body(source: str) -> object:
    raw = sys.stdin.read() if source == "-" else _read_file(source)
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        fail(f"--data is not valid JSON: {exc}", 2)


def _read_file(source: str) -> str:
    path = Path(source).expanduser()
    if not path.is_file():
        fail(f"--data file not found: {path}", 2)
    return path.read_text()


def _client(cfg: Config, sleep: float) -> APIClient:
    if not cfg.host:
        fail("no TestRail host configured; run `tr auth login` or set TESTRAIL_HOST", 3)
    if not cfg.email:
        fail("no TestRail email configured; run `tr auth login` or set TESTRAIL_EMAIL", 3)
    return APIClient(cfg.host, cfg.email, get_api_key(cfg), sleep_s=sleep)


def api(
    method: str = typer.Argument(..., metavar="METHOD", help="Raw API uri, e.g. get_case/42"),
    query: list[str] = typer.Option(None, "--query", "-q", help="k=v[,k=v] query params"),
    data: str | None = typer.Option(None, "--data", help="JSON body file, or - for stdin"),
    paginate: bool = typer.Option(False, "--paginate", help="Follow _links.next (get_* only)"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the request, send nothing"),
    commit: bool = typer.Option(False, "--commit", help="Actually send a write request"),
    sleep: float = typer.Option(0.0, "--sleep", help="Seconds to wait between requests"),
) -> None:
    """Call any TestRail API v2 method (writes need --commit)."""
    cfg = load_config()
    uri = method.lstrip("/")
    name = uri.split("/")[0]

    if name.startswith(REFUSED_PREFIX):
        fail(f"refusing to run {name}; tr never deletes TestRail data", 2)

    is_get = name.startswith("get_")
    if paginate and not is_get:
        fail("--paginate only works with get_* methods", 2)

    params = parse_query(query)
    body = load_body(data) if data else None
    url = build_url(cfg.host, uri, params)

    if not is_get and not commit:
        emit({"dry_run": True, "method": "POST", "url": url, "body": body})
        return
    if dry_run:
        emit(
            {
                "dry_run": True,
                "method": "GET" if is_get else "POST",
                "url": url,
                "body": body,
            }
        )
        return

    client = _client(cfg, sleep)
    try:
        if paginate:
            result = client.paginate(uri, params, sleep_s=sleep)
        elif is_get:
            result = client.get(uri, params)
        else:
            result = client.post(uri, body)
    except APIError as exc:
        fail(str(exc), 4)
    except OSError as exc:
        fail(f"network error: {exc}", 4)
    finally:
        client.close()

    emit_capped(result, cfg)
