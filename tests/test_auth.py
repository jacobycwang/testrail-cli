import json

import keyring
import keyring.errors
import pytest
from typer.testing import CliRunner

from tr.__main__ import app
from tr.auth import get_api_key
from tr.config import load_config

runner = CliRunner()


def test_env_key_wins_and_keyring_never_touched(monkeypatch):
    monkeypatch.setenv("TESTRAIL_API_KEY", "env-key-8842")

    def boom(*args, **kwargs):
        raise AssertionError("keyring must not be consulted when env key is set")

    monkeypatch.setattr(keyring, "get_password", boom)
    assert get_api_key(load_config()) == "env-key-8842"


def test_missing_keyring_backend_exits_3_and_mentions_env(monkeypatch, capsys):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")

    def no_backend(*args, **kwargs):
        raise keyring.errors.NoKeyringError("no backend")

    monkeypatch.setattr(keyring, "get_password", no_backend)
    with pytest.raises(SystemExit) as exc:
        get_api_key(load_config())
    assert exc.value.code == 3
    err = capsys.readouterr().err
    assert "TESTRAIL_API_KEY" in err
    assert "tr auth login" in err


def test_no_stored_password_exits_3(monkeypatch, capsys):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)
    with pytest.raises(SystemExit) as exc:
        get_api_key(load_config())
    assert exc.value.code == 3
    assert "TESTRAIL_API_KEY" in capsys.readouterr().err


def test_keyring_key_used_when_no_env(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    seen = {}

    def fake_get(service, account):
        seen["service"] = service
        seen["account"] = account
        return "ring-key-5531"

    monkeypatch.setattr(keyring, "get_password", fake_get)
    assert get_api_key(load_config()) == "ring-key-5531"
    assert seen == {
        "service": "testrail-cli",
        "account": "qa@example.com@https://example.testrail.io",
    }


def test_auth_status_without_config_reports_nulls(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    import json

    payload = json.loads(result.stdout)
    assert payload["host"] is None
    assert payload["email"] is None
    assert payload["project_id"] is None
    assert payload["key_source"] is None
    assert "keyring_backend" in payload


def test_auth_status_never_prints_the_key(monkeypatch):
    monkeypatch.setenv("TESTRAIL_API_KEY", "super-secret-7712")
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: "super-secret-7712")
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    assert "super-secret-7712" not in result.stdout
    import json

    assert json.loads(result.stdout)["key_source"] == "env"


def test_auth_logout_ignores_missing_password(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")

    def missing(*args, **kwargs):
        raise keyring.errors.PasswordDeleteError("nope")

    monkeypatch.setattr(keyring, "delete_password", missing)
    result = runner.invoke(app, ["auth", "logout"])
    assert result.exit_code == 0


def test_status_unconfigured_exits_0_with_one_hint(monkeypatch):
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["configured"] is False
    assert payload["key_source"] is None
    assert result.stderr.splitlines() == [
        "hint: set TESTRAIL_HOST, TESTRAIL_EMAIL, TESTRAIL_API_KEY (CI) "
        "or run `tr auth login`"
    ]


def test_status_configured_is_quiet_and_hides_the_key(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setenv("TESTRAIL_API_KEY", "secret-key-3391")
    result = runner.invoke(app, ["auth", "status"])
    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["configured"] is True
    assert payload["key_source"] == "env"
    assert result.stderr == ""
    assert "secret-key-3391" not in result.stdout


def test_status_without_a_key_is_not_configured(monkeypatch):
    monkeypatch.setenv("TESTRAIL_HOST", "https://example.testrail.io")
    monkeypatch.setenv("TESTRAIL_EMAIL", "qa@example.com")
    monkeypatch.setattr(keyring, "get_password", lambda *a, **k: None)
    result = runner.invoke(app, ["auth", "status"])
    assert json.loads(result.stdout)["configured"] is False
    assert "hint: set TESTRAIL_HOST" in result.stderr
