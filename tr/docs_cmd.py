import json
import os
import subprocess
from pathlib import Path

import typer

from tr.output import emit, fail, hint, json_mode

DOCS_ENV = "TR_DOCS_DIR"
MAX_HITS = 50
SEARCH_KEYWORD = "search"


def docs_dir() -> Path | None:
    override = os.environ.get(DOCS_ENV)
    if override:
        return Path(override).expanduser()
    for candidate in (Path(__file__).parent.parent / "docs", Path(__file__).parent / "docs"):
        if candidate.is_dir():
            return candidate
    return None


def topics() -> list[dict[str, str]]:
    directory = docs_dir()
    if not directory or not directory.is_dir():
        return []
    return [
        {"topic": path.stem, "path": str(path)}
        for path in sorted(directory.glob("*.md"))
    ]


def search(query: str) -> list[dict[str, object]]:
    directory = docs_dir()
    if not directory or not directory.is_dir():
        return []
    try:
        proc = subprocess.run(
            ["rg", "--json", "-i", "--", query, str(directory)],
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError:
        fail("ripgrep (rg) is not on PATH; install it to use `tr docs search`", 1)
    if proc.returncode not in (0, 1):
        fail(f"rg failed: {proc.stderr.strip()}", 1)

    hits: list[dict[str, object]] = []
    for line in proc.stdout.splitlines():
        if len(hits) >= MAX_HITS:
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") != "match":
            continue
        payload = event["data"]
        hits.append(
            {
                "topic": Path(payload["path"]["text"]).stem,
                "line": payload["line_number"],
                "text": payload["lines"]["text"].rstrip("\n"),
            }
        )
    return hits


def docs(
    topic: str | None = typer.Argument(None, help="Topic name, or 'search'"),
    query: str | None = typer.Argument(None, help="Query when topic is 'search'"),
) -> None:
    """List bundled docs, print one topic, or `tr docs search QUERY`."""
    if topic == SEARCH_KEYWORD:
        if not query:
            fail("usage: tr docs search QUERY", 2)
        emit(search(query))
        return
    if topic is None:
        emit(topics())
        return

    available = topics()
    match = next((t for t in available if t["topic"] == topic), None)
    if match is None:
        hint(json.dumps(available, ensure_ascii=False))
        fail(f"unknown docs topic {topic!r}", 1)

    content = Path(match["path"]).read_text()
    if json_mode():
        emit({"topic": topic, "content": content})
    else:
        typer.echo(content, nl=False)
