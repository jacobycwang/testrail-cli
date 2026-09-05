import json
import sys
from typing import Any, NoReturn

from tr.config import Config


def dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def emit(obj: Any) -> None:
    sys.stdout.write(dumps(obj) + "\n")


def hint(msg: str) -> None:
    sys.stderr.write(msg.rstrip("\n") + "\n")


def fail(msg: str, code: int = 1) -> NoReturn:
    sys.stderr.write(f"error: {msg}\n")
    raise SystemExit(code)


def emit_capped(obj: Any, cfg: Config) -> None:
    payload = dumps(obj)
    size = len(payload.encode())
    if size <= cfg.max_stdout_kb * 1024:
        sys.stdout.write(payload + "\n")
        return
    cfg.cache_dir.mkdir(parents=True, exist_ok=True)
    spill = cfg.cache_dir / "last.json"
    spill.write_text(payload)
    hint(f"payload {size} bytes exceeds {cfg.max_stdout_kb} KB; wrote {spill}")
    emit({"path": str(spill), "bytes": size, "truncated": True})


_state = {"json": False}


def set_json(value: bool) -> None:
    _state["json"] = value


def json_mode() -> bool:
    return _state["json"]
