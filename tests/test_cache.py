from tr.cache import (
    case_path,
    dump_json,
    load_json,
    project_dir,
    read_case_md,
    write_case_md,
)
from tr.config import load_config

BODY = "# Preconditions\n使用者已登入\n# Steps\n1. 點選付款\n   Expected: 顯示付款頁\n"

META = {
    "id": 1042,
    "title": "以過期 token 登入 — expired",
    "section": "Auth/Token",
    "suite_id": 2,
    "type": "Regression",
    "priority": "High",
    "refs": ["PAY-883", "PAY-900"],
    "labels": [],
    "last_status": "failed",
    "updated_on": "2026-09-01T00:00:00Z",
}


def test_write_then_read_case_md_roundtrip(tmp_path):
    path = tmp_path / "C1042.md"
    write_case_md(path, META, BODY)
    meta, body = read_case_md(path)
    assert meta == META
    assert meta["refs"] == ["PAY-883", "PAY-900"]
    assert body == BODY


def test_body_containing_triple_dash_is_preserved(tmp_path):
    path = tmp_path / "C7.md"
    body = "intro\n---\nafter separator\n"
    write_case_md(path, {"id": 7, "title": "sep"}, body)
    meta, read_body = read_case_md(path)
    assert meta["id"] == 7
    assert read_body == body


def test_project_dir_and_case_path():
    cfg = load_config()
    pdir = project_dir(cfg, 34)
    assert pdir == cfg.cache_dir / "34"
    assert case_path(pdir, 1042) == pdir / "cases" / "C1042.md"


def test_json_roundtrip(tmp_path):
    path = tmp_path / "nested" / "meta.json"
    obj = {"suites": {"2": "Regression"}, "last_sync": "2026-09-01T00:00:00Z"}
    dump_json(path, obj)
    assert load_json(path) == obj


def test_load_json_missing_returns_none(tmp_path):
    assert load_json(tmp_path / "nope.json") is None
