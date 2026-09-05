import json
from pathlib import Path
from typing import Any

import yaml

from tr.config import Config

FRONT_MATTER_FENCE = "---"


def project_dir(cfg: Config, project_id: int | str) -> Path:
    return cfg.cache_dir / str(project_id)


def cached_project_dirs(cfg: Config) -> list[Path]:
    """Every `{cache_dir}/<project id>/` that already holds a `cases/` dir, in numeric order."""
    root = Path(cfg.cache_dir)
    if not root.is_dir():
        return []
    dirs = [p for p in root.iterdir() if p.name.isdigit() and (p / "cases").is_dir()]
    return sorted(dirs, key=lambda p: int(p.name))


def project_name(project_dir: Path) -> str | None:
    meta = load_json(Path(project_dir) / "meta.json")
    return meta.get("project_name") if isinstance(meta, dict) else None


def case_path(project_dir: Path, case_id: int | str) -> Path:
    return project_dir / "cases" / f"C{case_id}.md"


def read_case_md(path: Path) -> tuple[dict, str]:
    text = Path(path).read_text()
    if not text.startswith(FRONT_MATTER_FENCE):
        return {}, text
    _, _, rest = text.partition(FRONT_MATTER_FENCE + "\n")
    raw_meta, fence, body = rest.partition("\n" + FRONT_MATTER_FENCE + "\n")
    if not fence:
        return {}, text
    meta = yaml.safe_load(raw_meta) or {}
    return meta, body


def write_case_md(path: Path, meta: dict, body: str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump(meta, allow_unicode=True, sort_keys=False, default_flow_style=None)
    path.write_text(f"{FRONT_MATTER_FENCE}\n{front}{FRONT_MATTER_FENCE}\n{body}")


def load_json(path: Path) -> Any:
    path = Path(path)
    if not path.is_file():
        return None
    return json.loads(path.read_text())


def dump_json(path: Path, obj: Any) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n")
