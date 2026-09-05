# Results

A result is a status (plus comment/elapsed/defects) recorded on a test.
Call only via `testrail api`. See `testrail docs quirks`.
Writes without `--commit` dry-run. `elapsed` is a timespan like `1m 30s`.

## GET get_results/{test_id}

Required: `test_id` (int). Paginated `{offset,limit,size,_links,results}`.
`limit` max 250. Query: `limit` int, `offset` int, `status_id` int list.

```json
{
  "offset": 0,
  "limit": 250,
  "size": 1,
  "_links": { "next": null, "prev": null },
  "results": [
    {
      "id": 9001,
      "test_id": 501,
      "status_id": 5,
      "comment": "Got 500 instead of 401",
      "elapsed": "1m 30s",
      "defects": "PAY-910",
      "version": "1.4.2",
      "assignedto_id": null,
      "created_on": 1693612800
    }
  ]
}
```

    testrail api get_results/501 --paginate

## GET get_results_for_case/{run_id}/{case_id}

Required: `run_id` (int), `case_id` (int). Same paginated `results`
shape as `get_results` (the test instance of that case in that run).

    testrail api get_results_for_case/88/1042 --paginate

## GET get_results_for_run/{run_id}

Required: `run_id` (int). All results in the run. Paginated `results`.
Query: `limit` int, `offset` int, `status_id` int list,
`created_after` unix.

    testrail api get_results_for_run/88 --query status_id=5 --paginate

## POST add_result/{test_id}

Required: `test_id` (int). Status 3 (untested) is not allowed.

```json
{
  "status_id": 5,
  "comment": "Got 500 instead of 401",
  "version": "1.4.2",
  "elapsed": "1m 30s",
  "defects": "PAY-910",
  "assignedto_id": 5
}
```

Response: one result object (same fields as above).

    testrail api add_result/501 --data body.json --commit

## POST add_result_for_case/{run_id}/{case_id}

Required: `run_id` (int), `case_id` (int). Same body as `add_result`,
keyed by run+case instead of test id.

    testrail api add_result_for_case/88/1042 --data body.json --commit

## POST add_results_for_cases/{run_id}

Required: `run_id` (int). Bulk add. Each item needs `case_id` plus at
least one of `status_id`, `comment`, `assignedto_id`.

```json
{
  "results": [
    {
      "case_id": 1042,
      "status_id": 5,
      "comment": "Got 500 instead of 401",
      "version": "1.4.2",
      "elapsed": "1m 30s",
      "defects": "PAY-910",
      "assignedto_id": 5,
      "custom_step_results": [
        {
          "content": "POST /login with expired token",
          "expected": "401 Unauthorized",
          "actual": "500 Internal Server Error",
          "status_id": 5
        }
      ]
    }
  ]
}
```

Response: unpaginated array of the new result objects.

    testrail api add_results_for_cases/88 --data body.json --commit
