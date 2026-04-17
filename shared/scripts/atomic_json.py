"""
Atomic JSON serialization — Allay-A4 pattern.

Writes to a tempfile in the same directory, fsyncs, then renames atomically.
Appends are line-oriented (jsonl) with O_APPEND + fsync. No partial writes,
no torn reads, stdlib only.

Also provides a reader that tolerates in-flight writes by retrying on
JSONDecodeError once.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path
from typing import Any


def atomic_write_json(path: str | Path, data: Any) -> None:
    """Write `data` as JSON to `path` atomically.

    Sequence: tempfile in same dir -> write -> fsync -> os.replace.
    os.replace is atomic on POSIX and Windows as long as source and target
    are on the same filesystem (they are, same directory).
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    # Use NamedTemporaryFile in the same directory so os.replace is atomic.
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=str(p.parent),
        prefix=f".{p.name}.",
        suffix=".tmp",
        delete=False,
    ) as tmp:
        json.dump(data, tmp, indent=2, sort_keys=True)
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = tmp.name

    # os.replace is atomic on both POSIX and Windows.
    os.replace(tmp_path, p)


def read_json(path: str | Path, default: Any = None, retry_once: bool = True) -> Any:
    """Read JSON with one retry on JSONDecodeError (in-flight write).

    Returns `default` if the file does not exist.
    """
    p = Path(path)
    if not p.exists():
        return default

    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except json.JSONDecodeError:
        if not retry_once:
            raise
        # Short backoff and try again.
        time.sleep(0.05)
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)


def append_jsonl(path: str | Path, record: dict) -> None:
    """Append a single JSON object as a line to a .jsonl file.

    Append-only audit pattern (weaver-gate audit.jsonl).
    O_APPEND is atomic for single writes up to PIPE_BUF on POSIX;
    on Windows, fsync + append is used. Each line is a self-contained
    JSON object, so a torn read can skip malformed lines safely.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    with open(p, "a", encoding="utf-8") as f:
        f.write(line)
        f.flush()
        try:
            os.fsync(f.fileno())
        except OSError:
            # fsync can fail on some filesystems (e.g., Windows network drives);
            # log-style appends prioritize durability but degrade gracefully.
            pass


def iter_jsonl(path: str | Path):
    """Yield JSON objects from a .jsonl file, skipping malformed lines."""
    p = Path(path)
    if not p.exists():
        return
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError:
                continue
