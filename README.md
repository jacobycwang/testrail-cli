# testrail-cli (`tr`)

Thin TestRail CLI for coding agents. stdout is JSON, hints go to stderr, writes are dry-run by default.

## Install

    uv tool install .          # or: uv sync && uv run tr --help

Needs Python >=3.12 and `rg` (ripgrep) on PATH.

## Auth

    tr auth login              # saves host/email to ~/.config/tr/config.yml, key to the OS keyring
    tr auth status             # never prints the key; TESTRAIL_API_KEY env also works

## Examples

    tr api get_case/42
    tr api get_cases/34 --query suite_id=7,limit=250 --paginate
    tr api add_run/34 --data run.json            # dry run; add --commit to send
    tr docs && tr docs quirks
    tr docs search pagination
