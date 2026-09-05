import re
import sys
from collections.abc import Sequence
from pathlib import Path

import typer

from tr.cache import read_case_md
from tr.config import load_config
from tr.output import emit, fail
from tr.search import case_project, cases_dirs_for, rg_hits, split_keys

DEFAULT_LIMIT = 50
MAX_TERMS = 40
MIN_WORD_LENGTH = 6

DIFF_PATH_RE = re.compile(r"^(?:\+\+\+|---)\s+(?:[ab]/)?(\S+)")
DEFINITION_RE = re.compile(r"\b(?:def|function|class|const|func)\s+([A-Za-z_][A-Za-z0-9_]*)")
WORD_RE = re.compile(rf"\b[A-Za-z][A-Za-z0-9_]{{{MIN_WORD_LENGTH - 1},}}\b")
TICKET_RE = re.compile(r"\b[A-Z][A-Z0-9]+-\d+\b")

STOPWORDS = {
    "assert", "boolean", "branch", "class", "common", "config", "console", "const",
    "create", "default", "delete", "double", "elif", "else", "except", "export",
    "extends", "false", "float", "function", "handler", "helper", "helpers", "import",
    "index", "insert", "integer", "interface", "lambda", "license", "main", "makefile",
    "module", "none", "number", "object", "package", "print", "private", "public",
    "readme", "requires", "return", "script", "self", "spec", "static", "string",
    "struct", "switch", "test", "tests", "throws", "true", "typedef", "update",
    "utils", "value", "values", "while", "yield",
}

REASON_ORDER = {"ref": 0, "term": 1, "section": 2, "failed": 3}


def read_diff(source: str) -> str:
    if source == "-":
        return sys.stdin.read()
    path = Path(source).expanduser()
    if not path.is_file():
        fail(f"diff file not found: {source}", 2)
    return path.read_text()


def changed_lines(text: str) -> list[str]:
    return [
        line[1:]
        for line in text.splitlines()
        if line[:1] in ("+", "-") and not line.startswith(("+++", "---"))
    ]


def extract_terms(text: str) -> list[str]:
    """Path stems, defined names, then long identifiers from added/removed lines."""
    terms: list[str] = []
    seen: set[str] = set()

    def add(candidate: str) -> None:
        key = candidate.lower()
        if key in seen or key in STOPWORDS or len(candidate) < 3 or len(terms) >= MAX_TERMS:
            return
        seen.add(key)
        terms.append(candidate)

    for line in text.splitlines():
        match = DIFF_PATH_RE.match(line)
        if match and match.group(1) != "/dev/null":
            add(Path(match.group(1)).stem)

    lines = changed_lines(text)
    for line in lines:
        for name in DEFINITION_RE.findall(line):
            add(name)
    for line in lines:
        for word in WORD_RE.findall(line):
            add(word)
    return terms


def extract_tickets(text: str) -> list[str]:
    tickets: list[str] = []
    for ticket in TICKET_RE.findall(text):
        if ticket not in tickets:
            tickets.append(ticket)
    return tickets


def load_cases(cases_dirs: Sequence[Path]) -> dict[str, dict]:
    """Case file path -> front matter record; the path keeps same-named cases apart."""
    cases: dict[str, dict] = {}
    for cases_dir in cases_dirs:
        for path in sorted(cases_dir.glob("C*.md")):
            meta, _ = read_case_md(path)
            if meta.get("id") is None:
                continue
            cases[str(path)] = {
                "id": int(meta["id"]),
                "project": case_project(path),
                "section": meta.get("section"),
                "type": meta.get("type"),
                "priority": meta.get("priority"),
                "refs": meta.get("refs") or [],
                "last_status": meta.get("last_status"),
                "path": str(path),
            }
    return cases


def sort_reasons(reasons: set[str]) -> list[str]:
    return sorted(reasons, key=lambda reason: (REASON_ORDER.get(reason.split(":")[0], 9), reason))


def rank_key(record: dict, reasons: set[str]) -> tuple[int, int, int, int, int]:
    failed = 0 if record["last_status"] == "failed" else 1
    high = 0 if str(record["priority"] or "").lower() == "high" else 1
    regression = 0 if str(record["type"] or "").lower() == "regression" else 1
    return failed, high, regression, -len(reasons), record["id"]


def build_scope(
    cases_dirs: Sequence[Path],
    terms: list[str],
    refs: list[str],
    with_sections: bool,
    failed_only: bool,
) -> dict:
    cases = load_cases(cases_dirs)
    wanted_refs = {ref.lower() for ref in refs}
    reasons: dict[str, set[str]] = {}

    for term in terms:
        for path in rg_hits(term, cases_dirs, whole_word=True):
            if path in cases:
                reasons.setdefault(path, set()).add(f"term:{term}")

    for path, record in cases.items():
        matched = [ref for ref in record["refs"] if str(ref).lower() in wanted_refs]
        for ref in matched:
            reasons.setdefault(path, set()).add(f"ref:{ref}")

    if with_sections:
        seeded = {
            (cases[path]["project"], cases[path]["section"])
            for path in reasons
            if cases[path]["section"]
        }
        for path, record in cases.items():
            if (record["project"], record["section"]) in seeded:
                reasons.setdefault(path, set()).add(f"section:{record['section']}")

    for path in list(reasons):
        if cases[path]["last_status"] == "failed":
            reasons[path].add("failed")

    selected = [
        (cases[path], why)
        for path, why in reasons.items()
        if not failed_only or cases[path]["last_status"] == "failed"
    ]
    selected.sort(key=lambda pair: rank_key(*pair))
    return {
        "case_ids": [record["id"] for record, _ in selected],
        "reasons": {str(record["id"]): sort_reasons(why) for record, why in selected},
        "projects": {str(record["id"]): record["project"] for record, _ in selected},
        "terms": terms,
        "refs": [ref.upper() for ref in refs],
    }


def scope(
    diff: str | None = typer.Option(None, "--diff", help="Unified diff file, or '-' for stdin"),
    refs: str | None = typer.Option(None, "--refs", help="Comma-separated ticket keys"),
    failed: bool = typer.Option(False, "--failed", help="Keep only cases whose last run failed"),
    section: bool = typer.Option(False, "--section", help="Expand to sibling cases per section"),
    limit: int = typer.Option(DEFAULT_LIMIT, "--limit", help="Maximum cases"),
    project: int | None = typer.Option(
        None, "--project", help="Narrow to one project; default is every cached project"
    ),
) -> None:
    """Build a regression scope from a diff and/or ticket keys (offline)."""
    if not diff and not refs:
        fail("usage: testrail scope [--diff PATH] [--refs KEYS] (at least one required)", 2)

    cfg = load_config()
    cases_dirs = cases_dirs_for(cfg, project)

    terms: list[str] = []
    ticket_keys = [key.upper() for key in sorted(split_keys(refs))]
    if diff:
        text = read_diff(diff)
        terms = extract_terms(text)
        for ticket in extract_tickets(text):
            if ticket not in ticket_keys:
                ticket_keys.append(ticket)

    result = build_scope(cases_dirs, terms, ticket_keys, section, failed)
    result["case_ids"] = result["case_ids"][:limit]
    keep = {str(case_id) for case_id in result["case_ids"]}
    result["reasons"] = {k: v for k, v in result["reasons"].items() if k in keep}
    result["projects"] = {k: v for k, v in result["projects"].items() if k in keep}
    emit(result)
