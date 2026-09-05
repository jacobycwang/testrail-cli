# Tests

A test is one case inside one run (the executable instance).
Call only via `tr api`. See `tr docs quirks`.

## GET get_tests/{run_id}

Required: `run_id` (int). Paginated `{offset,limit,size,_links,tests}`.
`limit` max 250.

Query: `status_id` int list (comma-separated), `limit` int, `offset` int.

```json
{
  "offset": 0,
  "limit": 250,
  "size": 2,
  "_links": { "next": null, "prev": null },
  "tests": [
    {
      "id": 501,
      "run_id": 88,
      "case_id": 1042,
      "status_id": 5,
      "title": "Login with expired token"
    },
    {
      "id": 502,
      "run_id": 88,
      "case_id": 1048,
      "status_id": 1,
      "title": "Login with valid token"
    }
  ]
}
```

    tr api get_tests/88 --query status_id=4,5,limit=250 --paginate

## GET get_test/{test_id}

Required: `test_id` (int). One test; may include case custom fields.

```json
{
  "id": 501,
  "run_id": 88,
  "case_id": 1042,
  "status_id": 5,
  "title": "Login with expired token",
  "assignedto_id": 5,
  "priority_id": 3,
  "type_id": 1,
  "refs": "PAY-883"
}
```

    tr api get_test/501

## GET get_statuses

No path params. System + custom result statuses (not paginated).

System IDs:

- 1 passed
- 2 blocked
- 3 untested (cannot be submitted as a new result)
- 4 retest
- 5 failed

Custom status IDs are >= 6.

```json
[
  { "id": 1, "name": "passed", "label": "Passed", "is_system": true },
  { "id": 5, "name": "failed", "label": "Failed", "is_system": true },
  { "id": 6, "name": "custom_status1", "label": "Skipped", "is_system": false }
]
```

    tr api get_statuses
