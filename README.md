# testrail-cli (`testrail`)

A small TestRail command-line tool built for coding agents (Claude Code, Codex, Cursor, ...) and the humans who supervise them.

It does four things well:

- **Talk to TestRail safely.** `testrail api` wraps the REST API with retries, rate-limit handling and pagination. Anything that writes is a dry run until you add `--commit`. Delete is not available at all.
- **Search test cases offline.** `testrail sync` copies every active project into local markdown files, then `testrail search` and `testrail scope` grep them with ripgrep. Zero API calls, and it finds words inside steps, which TestRail's own search cannot.
- **Keep the API key out of files.** The key lives in your OS keychain or in an environment variable. It is never a flag and never written to disk.
- **Teach the agent how to use it.** `skills/testrail-cli/SKILL.md` is an installable agent skill, and `testrail docs` ships a curated API reference with the known quirks.

It is not a replacement for the official `trcli`. Keep `trcli` in CI for JUnit uploads.

## Quick start

No clone needed. You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and ripgrep.

The command is `testrail`, not `tr`, because `tr` is a Unix built-in.

```bash
# 1. Install the CLI
brew install uv ripgrep            # macOS; on Linux use your package manager
uv tool install git+ssh://git@github.com/jacobycwang/testrail-cli

# 2. Log in once (host, email, API key -> keychain)
testrail auth login
testrail auth status

# 3. Copy TestRail into the local cache and search it
testrail sync                      # every active project; add --project 10 for just one
testrail search "invalid_grant" --failed
testrail case get 1042 --project 10
```

Give your coding agent the skill so it knows the rules:

```bash
npx skills add jacobycwang/testrail-cli
```

Upgrade later with `uv tool upgrade testrail-cli`.

## Everyday commands

| Goal | Command |
|---|---|
| Sync every active project (incremental after the first run) | `testrail sync` |
| Sync just one project | `testrail sync --project 10` |
| Find cases mentioning a word, even inside steps | `testrail search "refund" --type Regression` |
| Only the cases that failed last time | `testrail search "." --failed` |
| Search inside one project only | `testrail search "refund" --project 10` |
| Build a regression scope from a PR diff | `git diff main... > pr.diff && testrail scope --diff pr.diff` |
| Scope from ticket keys | `testrail scope --refs PAY-883,PAY-900` |
| Read one case (cache first, `--fresh` hits the API) | `testrail case get 1042` |
| Open a run (dry run) | `testrail run add --case-ids 1042,1043 --name "Smoke"` |
| Open a run for real | `testrail run add --case-ids 1042,1043 --name "Smoke" --commit` |
| Any raw API call | `testrail api get_cases/10 --query suite_id=2,limit=250 --paginate` |
| Read the API notes and quirks | `testrail docs quirks`, `testrail docs search pagination` |

`sync`, `search` and `scope` cover the whole instance by default; `--project ID` narrows them to one project, and every search result carries the project it came from.

Every command prints JSON on stdout. Hints and progress go to stderr, so piping into `jq` just works.

## Configuration

`testrail auth login` writes this file. `project_id` is the default project for `testrail case get` and `testrail run add` only — `sync`, `search` and `scope` ignore it and cover the whole instance:

```yaml
# ~/.config/tr/config.yml  (no secrets in here)
host: https://example.testrail.io
email: you@company.com
project_id: 10
cache_dir: ~/.cache/tr
```

### CI and headless machines

There is usually no keychain on a CI runner, so use environment variables instead. `testrail` never falls back to a plaintext file.

```bash
export TESTRAIL_HOST=https://example.testrail.io
export TESTRAIL_EMAIL=bot@company.com
export TESTRAIL_API_KEY=...        # from a secret store
testrail api get_case/42
```

Other overrides: `TESTRAIL_PROJECT_ID` (narrows `sync`/`search`/`scope` to one project and is the default for `case get`/`run add`), `TR_CONFIG` (config path), `TR_CACHE_DIR` (cache root), `TR_DOCS_DIR` (docs dir). Full reference: `testrail docs auth`.

## Safety rules

- Writes (`add_*`, `update_*`, `close_*`, `testrail run add`) are dry runs unless `--commit` is present.
- `delete_*` is refused, always.
- The API key never appears in argv, stdout, stderr or any file.
- `testrail search`, `testrail scope`, `testrail docs` and `testrail case get` (without `--fresh`) never touch the network.
- TestRail Cloud allows 180 requests per minute per instance. `testrail sync` paces itself with `--sleep` (default 0.35s).

## Exit codes

`0` ok, `1` error, `2` usage (including a refused delete), `3` auth or config, `4` HTTP/API error, `5` not in cache (run `testrail sync`).

## Development

```bash
git clone git@github.com:jacobycwang/testrail-cli.git && cd testrail-cli
uv sync
uv run pytest -q
uv run ruff check .
uv run testrail --help
```

Tests never hit the network. See `docs/` for the bundled API reference and `skills/testrail-cli/SKILL.md` for the agent-facing rules.
