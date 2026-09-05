# Cases

TestRail API v2. Call only via `tr api`. See `tr docs quirks`.
delete_case/delete_cases are intentionally not exposed by tr.

## GET get_case/{case_id}

Required: `case_id` (int). Returns one case.

```json
{
  "id": 1042, "title": "Login with expired token",
  "section_id": 12, "suite_id": 2, "type_id": 1, "priority_id": 3,
  "refs": "PAY-883, PAY-900",
  "created_on": 1693526400, "updated_on": 1693612800,
  "custom_preconds": "User exists.",
  "custom_steps": null, "custom_expected": null,
  "custom_steps_separated": [{
    "content": "POST /login with expired token",
    "expected": "401 Unauthorized",
    "additional_info": null, "shared_step_id": null
  }]
}
```

    tr api get_case/1042

## GET get_cases/{project_id}

Required: `project_id` (int). Paginated `{offset,limit,size,_links,cases}`.
`limit` max 250. `suite_id` required in multi-suite mode.

Query: `suite_id` int, `section_id` int, `limit` int, `offset` int,
`updated_after` unix, `updated_before` unix, `created_after` unix,
`filter` string (TITLE ONLY), `priority_id` int list, `type_id` int list,
`refs` string (ONE reference ID per request).

```json
{
  "offset": 0, "limit": 250, "size": 250,
  "_links": {"next": "/api/v2/get_cases/1&limit=250&offset=250", "prev": null},
  "cases": [{ "id": 1042, "title": "Login with expired token" }]
}
```

    tr api get_cases/1 --query suite_id=2,limit=250 --paginate

## POST add_case/{section_id}

Required: `section_id` (int). Body `title` required.

```json
{
  "title": "Login with expired token",
  "type_id": 1, "priority_id": 3, "refs": "PAY-883",
  "custom_preconds": "User exists.",
  "custom_steps_separated": [
    {"content": "POST /login with expired token", "expected": "401"},
    {"shared_step_id": 7}
  ]
}
```

Response: same shape as `get_case`.

    tr api add_case/12 --data body.json --commit

## POST update_case/{case_id}

Required: `case_id` (int). Partial update; same fields as add_case.

```json
{ "priority_id": 1, "refs": "PAY-883, PAY-900" }
```

    tr api update_case/1042 --data body.json --commit

## GET get_case_types

No path params. Array of `{id, name, is_default}`.

    tr api get_case_types

## GET get_priorities

No path params. Array of `{id, name, short_name, is_default, priority}`.

    tr api get_priorities

## GET get_case_fields

No path params. Custom fields appear on cases as `custom_*`.
Defaults: `custom_preconds` (text), `custom_steps` (text),
`custom_expected` (text), `custom_steps_separated` (steps list).
Each separated step: `{content, expected, additional_info, shared_step_id}`.
Free-text cases use `custom_steps` + `custom_expected` instead.

```json
[{"id": 1, "name": "preconds", "system_name": "custom_preconds",
  "label": "Preconditions", "type_id": 3}]
```

    tr api get_case_fields

## Shared steps

`GET get_shared_steps/{project_id}` — paginated `{offset,limit,size,_links,shared_steps}`.
`GET get_shared_step/{shared_step_id}` — one set.
Cases may store only `{shared_step_id}` in `custom_steps_separated`.
Step text lives on the shared-step object:

```json
{"id": 7, "title": "Default login",
 "custom_steps_separated": [
   {"content": "Open /login", "expected": "Form shown"}]}
```

    tr api get_shared_step/7
