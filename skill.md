---
name: testrail-cli
description: Use the `tr` CLI to read/search TestRail cases, build regression scope, and open runs. Use whenever a task mentions TestRail, test cases, regression scope, or test runs.
---

## Hard rules
- Unsure about an endpoint/param -> `tr docs TOPIC` or `tr docs search QUERY`; read `tr docs quirks` first.
- Talk to TestRail ONLY via `tr api`. Never curl. Never pass the API key as a flag or put it in a file; it comes from `TESTRAIL_API_KEY` env or the keyring via `tr auth login`.
- Finding related cases / building scope -> `tr search` and `tr scope` (local, need `tr sync` first). Never use `get_cases?filter=` for content search (title-only).
- Opening a run -> `tr run add ...` and inspect the dry-run payload; add `--commit` only when the user confirmed.
- Any `tr api` write (add_/update_/close_) is dry-run unless `--commit`. `delete_*` is not available.
- stdout is JSON; large responses land in `~/.cache/tr/last.json` and stdout gives the path.

## Quick recipes
- auth status: `tr auth status`
- get one case (cache vs --fresh): `tr case get 42` | `tr case get 42 --fresh`
- sync a project: `tr sync --project 1`
- search a word in steps with filters: `tr search "payment" --type Regression --refs PAY-883`
- scope from a diff file and from refs: `tr scope --diff changes.diff --refs PAY-883`
- open a run dry-run then commit: `tr run add --case-ids 1,2 --name "Smoke"` | `tr run add --case-ids 1,2 --name "Smoke" --commit`
- raw api GET with --query and --paginate: `tr api get_cases/1 --query suite_id=2,limit=250 --paginate`
- multi-value param (one param, comma list): `tr api get_tests/88 --query status_id=4,5`
- api dry-run POST with --data: `tr api add_case/2 --data case.json`

## Command contract
```
tr auth login | status | logout
tr api METHOD[/id] [--query k=v,k2=v2] [--data FILE] [--paginate] [--dry-run] [--commit] [--sleep S]
tr docs [TOPIC] | tr docs search QUERY
tr sync [--project ID] [--since ISO] [--runs N] [--sleep SECONDS] [--full]
tr search QUERY [--type T] [--refs KEY] [--failed] [--limit N] [--project ID] [--json]
tr scope [--diff PATH] [--refs KEYS] [--failed] [--section] [--limit N] [--project ID]
tr case get ID [--fresh] [--project ID]
tr run add --case-ids 1,2 --name "..." [--project ID] [--suite ID] [--description D]
            [--milestone ID] [--refs KEYS] [--commit]
```

## Exit codes
0 ok, 1 error, 2 usage, 3 auth/config, 4 HTTP/API, 5 not in cache (run tr sync).
