from __future__ import annotations

from app.store import JsonStore


def test_returns_default_when_file_is_missing(tmp_path):
    store = JsonStore(tmp_path / "missing.json")
    assert store.load({"a": 1}) == {"a": 1}


def test_round_trips_data(tmp_path):
    store = JsonStore(tmp_path / "state.json")
    payload = {"model": "best.pt", "sources": [{"source_id": "cam1", "name": "客厅"}]}
    store.save(payload)
    assert store.load(None) == payload


def test_corrupt_file_falls_back_to_default(tmp_path):
    path = tmp_path / "state.json"
    path.write_text("{not json", encoding="utf-8")
    assert JsonStore(path).load({"fallback": True}) == {"fallback": True}


def test_save_leaves_no_temporary_files_behind(tmp_path):
    store = JsonStore(tmp_path / "state.json")
    store.save({"a": 1})
    store.save({"a": 2})
    assert [p.name for p in tmp_path.iterdir()] == ["state.json"]
