import re
from typing import Any

from tr.http import APIClient

CASE_ID_SEPARATORS = re.compile(r"[,\s]+")
CASE_ID_PREFIX = "Cc"


def parse_case_id(raw: str) -> int:
    digits = raw.strip().lstrip(CASE_ID_PREFIX)
    if not digits.isdigit():
        raise ValueError(f"bad case id {raw!r}; expected an integer like 1042 or C1042")
    return int(digits)


def parse_case_ids(raw: str) -> list[int]:
    return [parse_case_id(item) for item in CASE_ID_SEPARATORS.split(raw.strip()) if item]


def build_run_payload(
    name: str,
    case_ids: list[int],
    suite_id: int | None = None,
    description: str | None = None,
    milestone_id: int | None = None,
    refs: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if suite_id is not None:
        payload["suite_id"] = suite_id
    payload["name"] = name
    optional = (("description", description), ("milestone_id", milestone_id), ("refs", refs))
    payload.update({key: value for key, value in optional if value is not None})
    payload["include_all"] = False
    payload["case_ids"] = list(case_ids)
    return payload


def add_run(client: APIClient, project_id: int | str, payload: dict[str, Any]) -> Any:
    return client.post(f"add_run/{project_id}", payload)


def add_results_for_cases(
    client: APIClient, run_id: int | str, results: list[dict[str, Any]]
) -> Any:
    return client.post(f"add_results_for_cases/{run_id}", {"results": list(results)})


def run_view_url(host: str, run_id: int | str) -> str:
    return f"{host.rstrip('/')}/index.php?/runs/view/{run_id}"
