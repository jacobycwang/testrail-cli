# testrail-cli (`tr`)

A small TestRail command-line tool built for coding agents (Claude Code, Codex, Cursor, ...) and the humans who supervise them.

It does four things well:

- **Talk to TestRail safely.** `tr api` wraps the REST API with retries, rate-limit handling and pagination. Anything that writes is a dry run until you add `--commit`. Delete is not available at all.
- **Search test cases offline.** `tr sync` copies a project into local markdown files, then `tr search` and `tr scope` grep them with ripgrep. Zero API calls, and it finds words inside steps, which TestRail's own search cannot.
- **Keep the API key out of files.** The key lives in your OS keychain or in an environment variable. It is never a flag and never written to disk.
- **Teach the agent how to use it.** `skills/testrail-cli/SKILL.md` is an installable agent skill, and `tr docs` ships a curated API reference with the known quirks.

It is not a replacement for the official `trcli`. Keep `trcli` in CI for JUnit uploads.

## Quick start

No clone needed. You need Python 3.12+, [uv](https://docs.astral.sh/uv/) and ripgrep.

```bash
# 1. Install the CLI
brew install uv ripgrep            # macOS; on Linux use your package manager
uv tool install git+ssh://git@github.com/jacobycwang/testrail-cli

# 2. Log in once (host, email, API key -> keychain)
tr auth login
tr auth status

# 3. Copy a project into the local cache and search it
tr sync --project 10
tr search "invalid_grant" --failed
tr case get 1042
```

Give your coding agent the skill so it knows the rules:

```bash
npx skills add jacobycwang/testrail-cli
```

Upgrade later with `uv tool upgrade testrail-cli`.

## Everyday commands

| Goal | Command |
|---|---|
| Sync a project (incremental after the first run) | `tr sync --project 10` |
| Find cases mentioning a word, even inside steps | `tr search "refund" --type Regression` |
| Only the cases that failed last time | `tr search "." --failed` |
| Build a regression scope from a PR diff | `git diff main... > pr.diff && tr scope --diff pr.diff` |
| Scope from ticket keys | `tr scope --refs PAY-883,PAY-900` |
| Read one case (cache first, `--fresh` hits the API) | `tr case get 1042` |
| Open a run (dry run) | `tr run add --case-ids 1042,1043 --name "Smoke"` |
| Open a run for real | `tr run add --case-ids 1042,1043 --name "Smoke" --commit` |
| Any raw API call | `tr api get_cases/10 --query suite_id=2,limit=250 --paginate` |
| Read the API notes and quirks | `tr docs quirks`, `tr docs search pagination` |

Every command prints JSON on stdout. Hints and progress go to stderr, so piping into `jq` just works.

## Configuration

`tr auth login` writes this file. Set `project_id` so you can drop `--project`:

```yaml
# ~/.config/tr/config.yml  (no secrets in here)
host: https://example.testrail.io
email: you@company.com
project_id: 10
cache_dir: ~/.cache/tr
```

### CI and headless machines

There is usually no keychain on a CI runner, so use environment variables instead. `tr` never falls back to a plaintext file.

```bash
export TESTRAIL_HOST=https://example.testrail.io
export TESTRAIL_EMAIL=bot@company.com
export TESTRAIL_API_KEY=...        # from a secret store
tr api get_case/42
```

Other overrides: `TESTRAIL_PROJECT_ID`, `TR_CONFIG` (config path), `TR_CACHE_DIR` (cache root), `TR_DOCS_DIR` (docs dir). Full reference: `tr docs auth`.

## Safety rules

- Writes (`add_*`, `update_*`, `close_*`, `tr run add`) are dry runs unless `--commit` is present.
- `delete_*` is refused, always.
- The API key never appears in argv, stdout, stderr or any file.
- `tr search`, `tr scope`, `tr docs` and `tr case get` (without `--fresh`) never touch the network.
- TestRail Cloud allows 180 requests per minute per instance. `tr sync` paces itself with `--sleep` (default 0.35s).

## Exit codes

`0` ok, `1` error, `2` usage (including a refused delete), `3` auth or config, `4` HTTP/API error, `5` not in cache (run `tr sync`).

## Development

```bash
git clone git@github.com:jacobycwang/testrail-cli.git && cd testrail-cli
uv sync
uv run pytest -q
uv run ruff check .
uv run tr --help
```

Tests never hit the network. See `docs/` for the bundled API reference and `skills/testrail-cli/SKILL.md` for the agent-facing rules.
