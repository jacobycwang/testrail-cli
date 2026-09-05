# Runs

A run is a set of tests (instances of cases) for execution.
Call only via `tr api`. See `tr docs quirks`.
Writes without `--commit` dry-run.

## GET get_run/{run_id}

Required: `run_id` (int). One run. Tests are not inlined; use `get_tests`.

```json
{
  "id": 88,
  "name": "PAY-883 regression",
  "description": null,
  "suite_id": 2,
  "project_id": 1,
  "plan_id": null,
  "milestone_id": null,
  "assignedto_id": 5,
  "include_all": false,
  "is_completed": false,
  "completed_on": null,
  "passed_count": 0,
  "blocked_count": 0,
  "untested_count": 3,
  "retest_count": 0,
  "failed_count": 0,
  "created_on": 1693526400,
  "updated_on": 1693526400,
  "refs": "PAY-883"
}
```

    tr api get_run/88

## GET get_runs/{project_id}

Required: `project_id` (int). Standalone runs only (not plan runs).
Paginated `{offset,limit,size,_links,runs}`. `limit` max 250.

Query: `is_completed` 0|1 (0 active, 1 closed), `limit` int,
`offset` int, `created_after` unix, `suite_id` int list.

```json
{
  "offset": 0,
  "limit": 250,
  "size": 1,
  "_links": { "next": null, "prev": null },
  "runs": [{ "id": 88, "name": "PAY-883 regression", "is_completed": false }]
}
```

    tr api get_runs/1 --query is_completed=0,limit=250 --paginate

## POST add_run/{project_id}

Required: `project_id` (int). `suite_id` required in multi-suite mode.
`include_all: true` ignores `case_ids` (see quirks). Prefer false.

```json
{
  "suite_id": 2,
  "name": "PAY-883 regression",
  "description": "Cases for PAY-883",
  "milestone_id": null,
  "assignedto_id": 5,
  "include_all": false,
  "case_ids": [1042, 1048, 1101],
  "refs": "PAY-883"
}
```

Response: same shape as `get_run`. Prefer `tr run add --case-ids ...`.

    tr api add_run/1 --data body.json --commit

## POST update_run/{run_id}

Required: `run_id` (int). Partial update. Same fields as add_run
except `suite_id` cannot change.

```json
{
  "description": "Updated description",
  "include_all": false,
  "case_ids": [1042, 1048]
}
```

    tr api update_run/88 --data body.json --commit

## POST close_run/{run_id}

Required: `run_id` (int). No body. Irreversible: archives tests
and results; no further results can be added.

Response: the closed run (`is_completed: true`, `completed_on` set).

    tr api close_run/88 --commit

## Plans (brief)

`GET get_plans/{project_id}` — paginated `plans`.
`GET get_plan/{plan_id}` — one plan with nested entry runs.
`get_runs` omits runs that belong to a plan; use these instead.

    tr api get_plans/1 --paginate
