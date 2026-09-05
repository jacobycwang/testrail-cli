import os

import keyring
import keyring.errors
import typer

from tr.config import Config, load_config, save_config
from tr.output import emit, fail, hint

SERVICE = "testrail-cli"
KEY_ENV = "TESTRAIL_API_KEY"
NOT_CONFIGURED_HINT = (
    "hint: set TESTRAIL_HOST, TESTRAIL_EMAIL, TESTRAIL_API_KEY (CI) or run `testrail auth login`"
)
NO_KEY_HELP = (
    f"no TestRail API key. Run `testrail auth login`, or set {KEY_ENV} in the environment "
    f"(headless Linux without a Secret Service daemon must use {KEY_ENV})"
)

app = typer.Typer(no_args_is_help=True, help="Manage TestRail credentials.")


def account(cfg: Config) -> str:
    return f"{cfg.email}@{cfg.host}"


def keyring_backend_name() -> str | None:
    try:
        return type(keyring.get_keyring()).__name__
    except Exception:
        return None


def read_keyring(cfg: Config) -> str | None:
    if not (cfg.host and cfg.email):
        return None
    try:
        return keyring.get_password(SERVICE, account(cfg))
    except Exception:
        return None


def get_api_key(cfg: Config) -> str:
    env_key = os.environ.get(KEY_ENV)
    if env_key:
        return env_key
    key = read_keyring(cfg)
    if not key:
        fail(NO_KEY_HELP, 3)
    return key


@app.command()
def login() -> None:
    """Store host, email and API key (key goes to the OS keyring)."""
    cfg = load_config()
    host = typer.prompt(
        "TestRail host (https://acme.testrail.io)", default=cfg.host or "", err=True
    )
    email = typer.prompt("TestRail email", default=cfg.email or "", err=True)
    api_key = typer.prompt("TestRail API key", hide_input=True, err=True)
    if not (host and email and api_key):
        fail("host, email and API key are all required", 3)

    cfg.host = host.rstrip("/")
    cfg.email = email
    try:
        keyring.set_password(SERVICE, account(cfg), api_key)
    except Exception as exc:
        fail(
            f"could not store the key in the keyring ({exc}). "
            f"Export {KEY_ENV} instead; the key is never written to a file",
            3,
        )
    path = save_config(cfg)
    hint(f"saved host/email to {path}; key stored in keyring backend {keyring_backend_name()}")
    emit({"host": cfg.host, "email": cfg.email, "key_source": "keyring"})


@app.command()
def status() -> None:
    """Show the configured host/email and where the key comes from."""
    cfg = load_config()
    if os.environ.get(KEY_ENV):
        key_source = "env"
    elif read_keyring(cfg):
        key_source = "keyring"
    else:
        key_source = None
    configured = bool(cfg.host and cfg.email and key_source)
    if not configured:
        hint(NOT_CONFIGURED_HINT)
    emit(
        {
            "configured": configured,
            "host": cfg.host,
            "email": cfg.email,
            "project_id": cfg.project_id,
            "key_source": key_source,
            "keyring_backend": keyring_backend_name(),
        }
    )


@app.command()
def logout() -> None:
    """Delete the stored API key from the keyring."""
    cfg = load_config()
    if not (cfg.host and cfg.email):
        fail("no host/email configured; nothing to delete", 3)
    removed = True
    try:
        keyring.delete_password(SERVICE, account(cfg))
    except keyring.errors.PasswordDeleteError:
        removed = False
    except Exception as exc:
        fail(f"keyring unavailable ({exc})", 3)
    emit({"account": account(cfg), "removed": removed})
