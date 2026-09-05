# testrail-cli (`tr`)

Thin agent CLI for TestRail. Not a `trcli` replacement (`trcli` stays for JUnit in CI).

## Install & Requirements
`uv tool install .` or `uv sync` + `uv run tr`. Requires Python >=3.12 and `rg` on PATH.

## Auth & Config
Auth via `TESTRAIL_API_KEY` env var or keyring via `tr auth login` (use env on headless Linux).
Config file (`~/.config/tr/config.yml` — no secrets):
```yaml
host: https://example.testrail.io
email: agent@example.com
project_id: 1
cache_dir: ~/.cache/tr
```

## Environment
- `TESTRAIL_HOST`, `TESTRAIL_EMAIL`, `TESTRAIL_PROJECT_ID` — override config.yml.
- `TESTRAIL_API_KEY` — the key (CI/headless); otherwise the keyring via `tr auth login`.
- `TR_CONFIG`, `TR_CACHE_DIR`, `TR_DOCS_DIR` — config path, cache root, docs dir.
- Keyring service `testrail-cli`, account `{email}@{host}`. Never a flag, never a file.
- Full reference: `tr docs auth`.

## Examples
- `tr sync --project 1`
- `tr search "payment" --type Regression`
- `tr scope --diff pr.diff`
- `tr case get 42`
- `tr run add --case-ids 1,2 --name "Smoke"` # dry run; add --commit to send
- `tr api get_case/42`
- `tr api get_cases/1 --query suite_id=2,limit=250 --paginate`
- `tr docs quirks`

Commands: `tr auth`, `tr api`, `tr docs`, `tr sync`, `tr search`, `tr scope`, `tr case`, `tr run`.
See [skill.md](skill.md) for agent usage guide and [docs/](docs/) for reference (`tr docs quirks`, `tr docs auth`).
