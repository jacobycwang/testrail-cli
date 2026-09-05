import os

import pytest

ENV_KEYS = (
    "TESTRAIL_API_KEY",
    "TESTRAIL_HOST",
    "TESTRAIL_EMAIL",
    "TESTRAIL_PROJECT_ID",
    "TR_DOCS_DIR",
    "TR_CONFIG",
    "TR_CACHE_DIR",
)


@pytest.fixture(autouse=True)
def isolated_env(tmp_path, monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("TR_CONFIG", str(tmp_path / "config.yml"))
    monkeypatch.setenv("TR_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg-config"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "xdg-cache"))
    yield


@pytest.fixture
def no_sleep(monkeypatch):
    import tr.http

    slept: list[float] = []
    monkeypatch.setattr(tr.http.time, "sleep", slept.append)
    return slept


@pytest.fixture
def cache_dir(tmp_path):
    return tmp_path / "cache"


def _unused():
    return os.getcwd()
