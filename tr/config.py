import os
from dataclasses import dataclass
from pathlib import Path

import yaml

CONFIG_ENV = "TR_CONFIG"
CACHE_ENV = "TR_CACHE_DIR"


@dataclass
class Config:
    host: str | None = None
    email: str | None = None
    project_id: int | None = None
    cache_dir: Path = Path.home() / ".cache" / "tr"
    max_stdout_kb: int = 64


def config_path() -> Path:
    override = os.environ.get(CONFIG_ENV)
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or "~/.config"
    return Path(base).expanduser() / "tr" / "config.yml"


def default_cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or "~/.cache"
    return Path(base).expanduser() / "tr"


def _as_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def load_config() -> Config:
    path = config_path()
    raw: dict = {}
    if path.is_file():
        loaded = yaml.safe_load(path.read_text()) or {}
        if isinstance(loaded, dict):
            raw = loaded

    host = os.environ.get("TESTRAIL_HOST") or raw.get("host") or None
    email = os.environ.get("TESTRAIL_EMAIL") or raw.get("email") or None
    project_id = _as_int(os.environ.get("TESTRAIL_PROJECT_ID")) or _as_int(raw.get("project_id"))

    cache_raw = os.environ.get(CACHE_ENV) or raw.get("cache_dir")
    cache_dir = Path(cache_raw).expanduser().absolute() if cache_raw else default_cache_dir()

    max_stdout_kb = _as_int(raw.get("max_stdout_kb")) or 64

    return Config(
        host=host.rstrip("/") if host else None,
        email=email,
        project_id=project_id,
        cache_dir=cache_dir,
        max_stdout_kb=max_stdout_kb,
    )


def save_config(cfg: Config) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "host": cfg.host,
        "email": cfg.email,
        "project_id": cfg.project_id,
        "cache_dir": str(cfg.cache_dir),
        "max_stdout_kb": cfg.max_stdout_kb,
    }
    path.write_text(yaml.safe_dump({k: v for k, v in payload.items() if v is not None}))
    return path
