"""Тесты core/json_store: atomic write, corrupt backup, межпроцессный lock."""
from __future__ import annotations

import json
import multiprocessing as mp
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core.json_store import load_json, save_json, update_json


def test_save_then_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    save_json(path, {"a": 1, "b": [2, 3]})

    loaded = load_json(path, default={}, expected_type=dict)

    assert loaded == {"a": 1, "b": [2, 3]}


def test_load_returns_default_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "absent.json"

    loaded = load_json(path, default={"k": "v"}, expected_type=dict)

    assert loaded == {"k": "v"}


def test_load_wrong_type_returns_default(tmp_path: Path) -> None:
    path = tmp_path / "wrong.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")

    loaded = load_json(path, default={}, expected_type=dict)

    assert loaded == {}


def test_corrupt_json_backed_up_and_default_returned(tmp_path: Path) -> None:
    path = tmp_path / "corrupt.json"
    path.write_text("{not valid json", encoding="utf-8")

    loaded = load_json(path, default={"safe": True}, expected_type=dict)

    assert loaded == {"safe": True}
    backups = list(tmp_path.glob("corrupt.corrupt.*.json"))
    assert len(backups) == 1, f"Expected one backup, got {backups}"
    assert backups[0].read_text(encoding="utf-8") == "{not valid json"


def test_save_is_atomic_no_tmp_leftover(tmp_path: Path) -> None:
    path = tmp_path / "atomic.json"
    save_json(path, {"x": 1})

    leftovers = list(tmp_path.glob("atomic.json.tmp*"))
    assert leftovers == []
    assert json.loads(path.read_text(encoding="utf-8")) == {"x": 1}


def test_update_json_applies_mutator(tmp_path: Path) -> None:
    path = tmp_path / "u.json"
    save_json(path, {"counter": 0})

    def mutator(state: dict) -> dict:
        state["counter"] += 1
        return state

    result = update_json(path, default={"counter": 0}, expected_type=dict, mutator=mutator)

    assert result == {"counter": 1}
    assert json.loads(path.read_text(encoding="utf-8")) == {"counter": 1}


def test_update_json_creates_file_when_missing(tmp_path: Path) -> None:
    path = tmp_path / "new.json"

    def mutator(state: list) -> list:
        state.append("hello")
        return state

    result = update_json(path, default=[], expected_type=list, mutator=mutator)

    assert result == ["hello"]


# ---------- Multiprocessing test (межпроцессный lock) ----------


def _append_worker(path_str: str, items: list[int]) -> None:
    """Worker: добавляет элементы в JSON-массив через update_json."""
    sys.path.insert(0, str(Path(path_str).parent.parent))
    from core.json_store import update_json as _update

    for item in items:
        def m(state: list, _item=item) -> list:
            state.append(_item)
            return state

        _update(Path(path_str), default=[], expected_type=list, mutator=m)


def test_multiprocess_append_no_lost_writes(tmp_path: Path) -> None:
    path = tmp_path / "mp.json"
    save_json(path, [])

    procs = []
    per_proc = 30
    n_procs = 3
    for i in range(n_procs):
        items = list(range(i * per_proc, (i + 1) * per_proc))
        p = mp.Process(target=_append_worker, args=(str(path), items))
        procs.append(p)
        p.start()

    for p in procs:
        p.join(timeout=30)
        assert p.exitcode == 0, f"Worker failed with {p.exitcode}"

    final = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(final, list)
    assert len(final) == n_procs * per_proc, f"Lost writes: got {len(final)}"
    assert sorted(final) == list(range(n_procs * per_proc))
