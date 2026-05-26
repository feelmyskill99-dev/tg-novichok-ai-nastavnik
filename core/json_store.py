"""Атомарный JSON-store с межпроцессным lock.

API:
    load_json(path, default, expected_type) -> Any
    save_json(path, value) -> None
    update_json(path, default, expected_type, mutator) -> Any  (load → mutate → save под lock)

При битом JSON делает backup `<name>.corrupt.<UTC-stamp>.json` и возвращает default.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import portalocker


def _lock_path(path: Path) -> Path:
    return path.with_suffix(path.suffix + ".lock")


def _backup_corrupt(path: Path) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    backup = path.with_name(f"{path.stem}.corrupt.{stamp}{path.suffix}")
    try:
        backup.write_bytes(path.read_bytes())
    except FileNotFoundError:
        pass
    return backup


def _load_unlocked(path: Path, default: Any, expected_type: type) -> Any:
    if not path.exists():
        return default
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        _backup_corrupt(path)
        return default

    if not isinstance(value, expected_type):
        return default
    return value


def _save_unlocked(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".tmp.",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(value, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def load_json(path: Path, default: Any, expected_type: type) -> Any:
    path = Path(path)
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_file), timeout=30):
        return _load_unlocked(path, default, expected_type)


def save_json(path: Path, value: Any) -> None:
    path = Path(path)
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_file), timeout=30):
        _save_unlocked(path, value)


def update_json(
    path: Path,
    default: Any,
    expected_type: type,
    mutator: Callable[[Any], Any],
) -> Any:
    path = Path(path)
    lock_file = _lock_path(path)
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    with portalocker.Lock(str(lock_file), timeout=30):
        current = _load_unlocked(path, default, expected_type)
        updated = mutator(current)
        _save_unlocked(path, updated)
        return updated
