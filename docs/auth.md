# Auth & Environment

Where `testrail` reads credentials, config and paths from; check with `testrail auth status`.
Precedence: environment variable > config.yml > built-in default.

## Environment variables

| Variable | Purpose |
| --- | --- |
| `TESTRAIL_HOST` | Instance URL, e.g. `https://acme.testrail.io`. Overrides config. |
| `TESTRAIL_EMAIL` | API user email. Overrides config. |
| `TESTRAIL_PROJECT_ID` | Narrows `sync`/`search`/`scope` to one project, and is the default project for `case get`/`run add`. Overrides config. |
| `TESTRAIL_API_KEY` | The API key. The ONLY env var that carries a secret. |
| `TR_CONFIG` | Full path to config.yml (overrides `XDG_CONFIG_HOME`/`~/.config`). |
| `TR_CACHE_DIR` | Cache root (overrides `XDG_CACHE_HOME`/`~/.cache/tr`). |
| `TR_DOCS_DIR` | Directory these docs are read from. |

## Keyring

`testrail auth login` stores the key in the OS keyring under service `testrail-cli`,
account `{email}@{host}`, e.g. `qa@acme.com@https://acme.testrail.io`;
`testrail auth logout` deletes it. The key is never a CLI flag, never printed,
never logged, never written to config.yml.

## Headless Linux / CI

No Secret Service daemon means no keyring: export `TESTRAIL_HOST`,
`TESTRAIL_EMAIL` and `TESTRAIL_API_KEY` from the CI secret store instead.
Never put the key in a plaintext file.

## config.yml

Non-secret values only, at `~/.config/tr/config.yml`:

```yaml
host: https://acme.testrail.io
email: qa@acme.com
project_id: 1
cache_dir: ~/.cache/tr
```

## Which project a command uses

`sync`, `search` and `scope` are instance-wide: `--project ID` narrows them to one
project, otherwise `TESTRAIL_PROJECT_ID` does, otherwise they cover every active
(sync) or every cached (search/scope) project. They never read config.yml
`project_id`.

`case get` and `run add` need exactly one project: `--project` >
`TESTRAIL_PROJECT_ID` > config.yml `project_id`, and exit 3 when none is set.
