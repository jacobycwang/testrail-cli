"""Batch-edit test cases through a reviewed change file.

`snapshot` writes the live cases to a JSON file: `before` holds what TestRail has now,
`fields` starts as a copy for the agent or human to edit. `apply` sends only the fields
that differ from `before`, in batches, after checking nobody changed the case meanwhile.
"""

import difflib
import re
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from tr.cache import dump_json
from tr.http import APIClient, APIError

BATCH_SIZE = 10
TEXT_TEMPLATE_ID = 1
STEPS_TEMPLATE_ID = 2
TEXT_FIELDS = ("custom_preconds", "custom_steps", "custom_expected")
STEPS_FIELD = "custom_steps_separated"
STEPS_FIELDS = ("custom_preconds", STEPS_FIELD)
STEP_KEYS = ("content", "expected", "additional_info", "refs", "shared_step_id")
ANY_TEMPLATE_FIELDS = ("title",)
ADD_REQUIRED = frozenset({"title", "template_id", "type_id", "priority_id", *TEXT_FIELDS})
DIFF_SPLIT = re.compile(r"\n|(?=<li>|</?[ou]l>)")


def editable_fields(template_id: Any) -> tuple[str, ...]:
    """Steps and expected live in different fields per template. Only TestRail's built-in
    Text (1) and Steps (2) templates are verified; custom ones stay title-only. Template 2
    leaves out custom_steps/custom_expected: those hold stale text from a Text -> Steps switch."""
    if template_id == TEXT_TEMPLATE_ID:
        return ANY_TEMPLATE_FIELDS + TEXT_FIELDS
    if template_id == STEPS_TEMPLATE_ID:
        return ANY_TEMPLATE_FIELDS + STEPS_FIELDS
    return ANY_TEMPLATE_FIELDS


def step_key(step: Any) -> tuple:
    """What counts as a step's content: markdown_editor_id is ignored, null equals ""."""
    if not isinstance(step, dict):
        return (repr(step),)
    return tuple("" if step.get(name) is None else step.get(name) for name in STEP_KEYS)


def steps_key(steps: Any) -> tuple:
    return tuple(step_key(step) for step in steps or [])


def same_value(name: str, a: Any, b: Any) -> bool:
    if name == STEPS_FIELD:
        return steps_key(a) == steps_key(b)
    return a == b


def steps_problem(steps: Any, live_steps: Any) -> str:
    """Why a new steps array cannot be sent, or "" if it can. Shared steps may move but must
    come back exactly as TestRail returned them; this tool never edits a shared step."""
    if not isinstance(steps, list) or not all(isinstance(step, dict) for step in steps):
        return f"{STEPS_FIELD} must be a list of step objects"

    def shared(items: Any) -> Counter:
        return Counter(
            step_key(s) for s in items or [] if isinstance(s, dict) and s.get("shared_step_id")
        )

    want, have = shared(live_steps), shared(steps)
    if want == have:
        return ""
    changed = sorted({key[-1] for key in (want - have) + (have - want)})
    return f"shared steps {changed} were edited, removed or added; leave shared steps as they are"


def _items(payload: Any, key: str) -> list[dict]:
    return payload if isinstance(payload, list) else (payload or {}).get(key) or []


# --- snapshot -----------------------------------------------------------------------


def snapshot_entry(case: dict) -> dict:
    names = editable_fields(case.get("template_id"))
    before = {name: case.get(name) for name in names}
    entry = {
        "case_id": case["id"],
        "section_id": case.get("section_id"),
        "template_id": case.get("template_id"),
        "priority_id": case.get("priority_id"),
        "base_version": case.get("version"),
        "base_updated_on": case.get("updated_on"),
        "before": before,
        "fields": dict(before),
    }
    if case.get("template_id") not in (TEXT_TEMPLATE_ID, STEPS_TEMPLATE_ID):
        entry["note"] = f"template {case.get('template_id')}: only the title is editable"
    return entry


def section_tree(client: APIClient, section_id: int) -> tuple[int, int, list[dict]]:
    """Return (project_id, suite_id, [section and every descendant, parents first])."""
    root = client.get(f"get_section/{section_id}")
    suite_id = root["suite_id"]
    project_id = client.get(f"get_suite/{suite_id}")["project_id"]
    sections = _items(
        client.paginate(f"get_sections/{project_id}", {"suite_id": suite_id}), "sections"
    )
    children: dict[Any, list[dict]] = {}
    for section in sorted(sections, key=lambda s: s.get("display_order") or 0):
        children.setdefault(section.get("parent_id"), []).append(section)
    ordered: list[dict] = []
    stack = [root]
    while stack:
        current = stack.pop()
        ordered.append(current)
        stack.extend(reversed(children.get(current["id"], [])))
    return project_id, suite_id, ordered


def section_cases(client: APIClient, project_id: int, suite_id: int, section_id: int) -> list:
    params = {"suite_id": suite_id, "section_id": section_id, "limit": 250}
    return _items(client.paginate(f"get_cases/{project_id}", params), "cases")


def snapshot_section(client: APIClient, section_id: int) -> tuple[int, list[dict], list[dict]]:
    project_id, suite_id, sections = section_tree(client, section_id)
    cases: list[dict] = []
    summary: list[dict] = []
    for section in sections:
        found = section_cases(client, project_id, suite_id, section["id"])
        cases.extend(found)
        summary.append(
            {
                "id": section["id"],
                "name": section.get("name"),
                "depth": section.get("depth"),
                "cases": len(found),
            }
        )
    return project_id, cases, summary


def snapshot_ids(client: APIClient, case_ids: list[int]) -> tuple[int | None, list[dict]]:
    cases = [client.get(f"get_case/{case_id}") for case_id in case_ids]
    projects = {
        client.get(f"get_suite/{suite_id}")["project_id"]
        for suite_id in {case.get("suite_id") for case in cases}
        if suite_id
    }
    return (projects.pop() if len(projects) == 1 else None), cases


# --- apply --------------------------------------------------------------------------


@dataclass
class Item:
    kind: str
    key: str
    status: str
    change: dict
    body: dict = field(default_factory=dict)
    live: dict | None = None
    note: str = ""
    priority_id: int = 0


def edited_fields(change: dict) -> dict:
    before = change.get("before") or {}
    return {
        name: value
        for name, value in (change.get("fields") or {}).items()
        if name not in before or not same_value(name, before[name], value)
    }


def check_update(change: dict, client: APIClient) -> Item:
    key = f"C{change['case_id']}"
    body = edited_fields(change)
    item = Item("update", key, "ready", change, body, priority_id=change.get("priority_id") or 0)
    if not body:
        item.status, item.note = "unchanged", "no field differs from before"
        return item
    try:
        live = client.get(f"get_case/{change['case_id']}")
    except APIError as exc:
        item.status, item.note = "failed", str(exc)
        return item

    item.live = live
    item.priority_id = live.get("priority_id") or 0
    allowed = editable_fields(live.get("template_id"))
    extra = sorted(set(body) - set(allowed))
    problem = steps_problem(body[STEPS_FIELD], live.get(STEPS_FIELD)) if STEPS_FIELD in body else ""
    if extra:
        item.status = "unsupported"
        item.note = f"template {live.get('template_id')} cannot take {extra}"
    elif problem:
        item.status, item.note = "unsupported", problem
    elif all(same_value(name, live.get(name), value) for name, value in body.items()):
        item.status, item.note = "unchanged", "TestRail already has this content"
    elif (live.get("version"), live.get("updated_on")) != (
        change.get("base_version"),
        change.get("base_updated_on"),
    ):
        item.status = "conflict"
        item.note = (
            f"changed in TestRail since the snapshot "
            f"(version {change.get('base_version')} -> {live.get('version')}); snapshot again"
        )
    return item


class SectionLookup:
    """Caches section -> (project, suite) so several adds cost one lookup each."""

    def __init__(self, client: APIClient) -> None:
        self.client = client
        self.found: dict[int, tuple[int, int]] = {}

    def __call__(self, section_id: int) -> tuple[int, int]:
        if section_id not in self.found:
            suite_id = self.client.get(f"get_section/{section_id}")["suite_id"]
            project_id = self.client.get(f"get_suite/{suite_id}")["project_id"]
            self.found[section_id] = (project_id, suite_id)
        return self.found[section_id]


def same_title_ids(client: APIClient, lookup: SectionLookup, section_id: int, title: str) -> list:
    project_id, suite_id = lookup(section_id)
    cases = section_cases(client, project_id, suite_id, section_id)
    return [case.get("id") for case in cases if case.get("title") == title]


def check_add(change: dict, index: int, client: APIClient, lookup: SectionLookup) -> Item:
    body = change.get("fields") or {}
    item = Item("add", f"A{index}", "ready", change, body, priority_id=body.get("priority_id") or 0)
    missing = sorted(ADD_REQUIRED - set(body))
    if missing or not change.get("section_id"):
        item.status, item.note = "invalid", f"missing {missing or ['section_id']}"
    elif body["template_id"] != TEXT_TEMPLATE_ID:
        item.status, item.note = "unsupported", "only template 1 can be added this way"
    else:
        try:
            if same_title_ids(client, lookup, change["section_id"], body["title"]):
                item.status, item.note = "duplicate", "the section already has this title"
        except (APIError, KeyError) as exc:
            item.status, item.note = "failed", str(exc)
    return item


def build_items(changes: dict, client: APIClient) -> list[Item]:
    lookup = SectionLookup(client)
    items = [check_update(change, client) for change in changes.get("updates") or []]
    adds = [
        check_add(change, index, client, lookup)
        for index, change in enumerate(changes.get("adds") or [], start=1)
    ]
    block_repeated_adds(adds)
    return sorted(items + adds, key=lambda item: item.priority_id, reverse=True)


def block_repeated_adds(adds: list[Item]) -> None:
    first_key: dict[tuple, str] = {}
    for item in adds:
        if item.status != "ready":
            continue
        target = (item.change["section_id"], item.body["title"])
        if target in first_key:
            item.status, item.note = "duplicate", f"same title as {first_key[target]} in this file"
        else:
            first_key[target] = item.key


def next_batch(items: list[Item], skip: set[str], size: int = BATCH_SIZE) -> list[Item]:
    """The next cases to write: ready and not skipped. Written cases read back as unchanged,
    so running apply again always picks up where the last commit stopped."""
    return [item for item in items if item.status == "ready" and item.key not in skip][:size]


def field_diff(before: Any, after: Any) -> list[str]:
    lines = difflib.unified_diff(
        [part for part in DIFF_SPLIT.split(str(before or "")) if part],
        [part for part in DIFF_SPLIT.split(str(after or "")) if part],
        lineterm="",
        n=0,
    )
    return [line for line in lines if not line.startswith(("---", "+++", "@@"))]


def _step_lines(label: str, step: dict, sign: str) -> list[str]:
    lines = [f"{label} ({'added' if sign == '+' else 'removed'})"]
    for name in STEP_KEYS:
        if step.get(name) not in (None, ""):
            before, after = (None, step[name]) if sign == "+" else (step[name], None)
            lines += [f"{label} {name}: {line}" for line in field_diff(before, after)]
    return lines


def steps_diff(before: Any, after: Any) -> list[str]:
    """Step-by-step diff: `step 3 expected: -old`, `step 5 (added)`, `step 2 (removed)`.
    Added and changed steps are numbered as in the new list, removed ones as in the old."""
    old, new = list(before or []), list(after or [])
    matcher = difflib.SequenceMatcher(a=steps_key(old), b=steps_key(new), autojunk=False)
    out: list[str] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            continue
        pairs = min(i2 - i1, j2 - j1) if tag == "replace" else 0
        for offset in range(pairs):
            a, b = old[i1 + offset], new[j1 + offset]
            for name in STEP_KEYS:
                if step_key({name: a.get(name)}) != step_key({name: b.get(name)}):
                    label = f"step {j1 + offset + 1} {name}"
                    out += [f"{label}: {line}" for line in field_diff(a.get(name), b.get(name))]
        for index in range(i1 + pairs, i2):
            out += _step_lines(f"step {index + 1}", old[index], "-")
        for index in range(j1 + pairs, j2):
            out += _step_lines(f"step {index + 1}", new[index], "+")
    return out


def describe(item: Item) -> dict:
    before = item.change.get("before") or {}
    title = (item.live or {}).get("title") or before.get("title") or item.body.get("title") or ""
    out: dict[str, Any] = {"key": item.key, "kind": item.kind, "status": item.status}
    if title:
        out["title"] = title
    if item.kind == "add":
        out["section_id"] = item.change.get("section_id")
    if item.note:
        out["note"] = item.note
    if item.status == "ready":
        live = item.live or {}
        out["diff"] = {
            name: (steps_diff if name == STEPS_FIELD else field_diff)(live.get(name), value)
            for name, value in item.body.items()
        }
    return out


def write_backup(path: Path, items: list[Item]) -> Path | None:
    updates = [item for item in items if item.kind == "update"]
    if not updates:
        return None
    target = path.with_name(f"{path.name}.backup-{time.strftime('%Y%m%d-%H%M%S')}.json")
    dump_json(
        target,
        [
            {
                "case_id": item.change["case_id"],
                "version": item.live.get("version"),
                "updated_on": item.live.get("updated_on"),
                "before": {name: item.live.get(name) for name in item.body},
            }
            for item in updates
        ],
    )
    return target


def write_update(item: Item, client: APIClient) -> str:
    case_id = item.change["case_id"]
    client.post(f"update_case/{case_id}", item.body)
    saved = client.get(f"get_case/{case_id}")
    differs = [
        name for name, value in item.body.items() if not same_value(name, saved.get(name), value)
    ]
    if differs:
        raise APIError(0, f"read back differs from what was sent: {differs}")
    return ""


def write_add(item: Item, client: APIClient, lookup: SectionLookup) -> str:
    """The HTTP client retries POST on 5xx, so count same-title cases after adding."""
    section_id = item.change["section_id"]
    created = client.post(f"add_case/{section_id}", item.body)
    ids = same_title_ids(client, lookup, section_id, item.body["title"])
    if len(ids) != 1:
        raise APIError(0, f"{len(ids)} cases now share this title: {ids}; remove the extras")
    return f"created C{created.get('id')}"


def apply_items(ready: list[Item], client: APIClient, path: Path) -> tuple[list[dict], Path | None]:
    backup = write_backup(path, ready)
    lookup = SectionLookup(client)
    results = []
    for item in ready:
        try:
            if item.kind == "update":
                note = write_update(item, client)
            else:
                note = write_add(item, client, lookup)
            results.append({"key": item.key, "status": "ok", **({"note": note} if note else {})})
        except (APIError, KeyError) as exc:
            results.append({"key": item.key, "status": "failed", "note": str(exc)})
    return results, backup
