---
name: testrail-cli
description: Use the `testrail` CLI to read and search TestRail cases, build a regression scope from a diff or ticket keys, and open test runs. Use whenever a task mentions TestRail, test cases, regression scope, or test runs.
---

## Setup check (run first)
```bash
testrail auth status || uv tool install git+ssh://git@github.com/jacobycwang/testrail-cli
```
- `configured: false` in the output -> stop and ask the user to run `testrail auth login` (or set `TESTRAIL_HOST`, `TESTRAIL_EMAIL`, `TESTRAIL_API_KEY` in CI). Never ask for the key in chat.
- `project_id: null` -> pass `--project ID` to every command, or ask the user which project.

## Hard rules
- Unsure about an endpoint/param -> `testrail docs TOPIC` or `testrail docs search QUERY`; read `testrail docs quirks` first.
- Talk to TestRail ONLY via `testrail api`. Never curl. Never pass the API key as a flag or put it in a file; it comes from `TESTRAIL_API_KEY` env or the keyring via `testrail auth login`.
- Finding related cases / building scope -> `testrail search` and `testrail scope` (local, need `testrail sync` first). Never use `get_cases?filter=` for content search (title-only).
- Opening a run -> `testrail run add ...` and inspect the dry-run payload; add `--commit` only when the user confirmed.
- Any `testrail api` write (add_/update_/close_) is dry-run unless `--commit`. `delete_*` is not available.
- stdout is JSON; large responses land in `~/.cache/tr/last.json` and stdout gives the path.

## Typical workflow
1. `testrail sync` once per session (incremental, cheap). First sync of a big project takes a minute or two.
2. Find candidates: `testrail search "<word from the change>"` and/or `testrail scope --diff pr.diff --refs KEY-1`.
3. Read the ones that matter: `testrail case get ID`.
4. Propose a run: `testrail run add --case-ids ... --name "..."`, show the payload, wait for a yes, then rerun with `--commit`.

## Quick recipes
- auth status: `testrail auth status`
- get one case (cache vs --fresh): `testrail case get 42` | `testrail case get 42 --fresh`
- sync a project: `testrail sync --project 10`
- search a word in steps with filters: `testrail search "payment" --type Regression --refs PAY-883`
- only failed cases: `testrail search "." --failed`
- scope from a diff file and from refs: `testrail scope --diff changes.diff --refs PAY-883`
- open a run dry-run then commit: `testrail run add --case-ids 1,2 --name "Smoke"` | `testrail run add --case-ids 1,2 --name "Smoke" --commit`
- raw api GET with --query and --paginate: `testrail api get_cases/10 --query suite_id=2,limit=250 --paginate`
- multi-value param (one param, comma list): `testrail api get_tests/88 --query status_id=4,5`
- api dry-run POST with --data: `testrail api add_case/2 --data case.json`

## Environment
- `TESTRAIL_HOST`, `TESTRAIL_EMAIL`, `TESTRAIL_PROJECT_ID` — override config.yml.
- `TESTRAIL_API_KEY` — the key (CI/headless); otherwise the keyring via `testrail auth login`.
- `TR_CONFIG`, `TR_CACHE_DIR`, `TR_DOCS_DIR` — config path, cache root, docs dir.
- Keyring service `testrail-cli`, account `{email}@{host}`. Never a flag, never a file.
- Full reference: `testrail docs auth`.

## Command contract
```
testrail auth login | status | logout
testrail api METHOD[/id] [--query k=v,k2=v2] [--data FILE] [--paginate] [--dry-run] [--commit] [--sleep S]
testrail docs [TOPIC] | testrail docs search QUERY
testrail sync [--project ID] [--since ISO] [--runs N] [--sleep SECONDS] [--full]
testrail search QUERY [--type T] [--refs KEY] [--failed] [--limit N] [--project ID] [--json]
testrail scope [--diff PATH] [--refs KEYS] [--failed] [--section] [--limit N] [--project ID]
testrail case get ID [--fresh] [--project ID]
testrail run add --case-ids 1,2 --name "..." [--project ID] [--suite ID] [--description D]
            [--milestone ID] [--refs KEYS] [--commit]
```

## Exit codes
0 ok, 1 error, 2 usage, 3 auth/config, 4 HTTP/API, 5 not in cache (run testrail sync).
A refused `delete_*` call exits 2.
