"""
Sylph atomic-state helper — Emu-A4 pattern.

Stdlib-only (json, os, pathlib, tempfile, fcntl). Used by hook scripts and
engines that persist per-plugin state under ``plugins/*/state/``. The three
public functions are the contract agents D (hook wiring) and E (safe-amend)
call against:

    read_state(path, default=None)
    write_state(path, state)
    append_jsonl(path, record)

Pattern (Emu-A4):
    1. Write payload to a tempfile in the **same directory** as the target.
    2. ``flush()`` + ``os.fsync()`` the tempfile descriptor.
    3. ``os.replace(tmp, target)`` — POSIX-atomic rename, same-volume on NT.

Windows note:
    ``fcntl`` is POSIX-only. On Windows (``os.name == "nt"``) the JSONL
    append path degrades to best-effort: O_APPEND is still used and every
    write fsyncs, but we skip the cross-process ``flock(LOCK_EX)``. Sylph's
    primary target is POSIX; Windows is the developer environment only.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Union

try:  # POSIX only.
    import fcntl  # type: ignore[import-not-found]
    _HAVE_FCNTL = True
except ImportError:  # Windows.
    fcntl = None  # type: ignore[assignment]
    _HAVE_FCNTL = False


PathLike = Union[str, "os.PathLike[str]", Path]


def read_state(path: PathLike, default: Any = None) -> Any:
    """Read a JSON state file.

    Returns ``default`` (or ``{}`` when ``default is None``) if the file is
    missing, empty, or contains corrupt JSON. Never raises on I/O — the
    Sylph hooks layer must be resilient to half-written state inherited
    from a crashed prior session.
    """
    fallback = {} if default is None else default
    p = Path(path)
    if not p.exists():
        return fallback
    try:
        raw = p.read_text(encoding="utf-8")
    except OSError:
        return fallback
    if not raw.strip():
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def write_state(path: PathLike, state: Any) -> None:
    """Atomically write ``state`` as JSON to ``path``.

    Creates parent directories if missing. 2-space indent, trailing newline.
    The write is durable: tempfile in the same directory, fsync the
    descriptor, then ``os.replace`` — atomic on POSIX and same-volume NTFS.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    fd, tmp = tempfile.mkstemp(
        dir=str(p.parent),
        prefix=f".{p.name}.",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2, ensure_ascii=False)
            f.write("\n")
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                # fsync unsupported (e.g., some Windows network mounts) —
                # the atomic rename below still gives the key guarantee.
                pass
        os.replace(tmp, p)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def append_jsonl(path: PathLike, record: Any) -> None:
    """Atomically append one JSON record + newline to a JSONL file.

    Uses ``O_APPEND | O_CREAT | O_WRONLY`` plus (on POSIX) an exclusive
    ``flock`` on the file descriptor for cross-process safety. The record
    is pre-serialized to a single line and written with one ``os.write()``;
    a torn read can skip the last malformed line — every earlier line is a
    self-contained JSON object.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)

    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False) + "\n"
    data = line.encode("utf-8")

    flags = os.O_APPEND | os.O_CREAT | os.O_WRONLY
    fd = os.open(str(p), flags, 0o644)
    try:
        if _HAVE_FCNTL:
            fcntl.flock(fd, fcntl.LOCK_EX)  # type: ignore[union-attr]
        try:
            # Single write() of a sub-PIPE_BUF line is atomic on POSIX; for
            # longer payloads the flock above serializes concurrent writers
            # so we never interleave partial records.
            os.write(fd, data)
            try:
                os.fsync(fd)
            except OSError:
                pass
        finally:
            if _HAVE_FCNTL:
                try:
                    fcntl.flock(fd, fcntl.LOCK_UN)  # type: ignore[union-attr]
                except OSError:
                    pass
    finally:
        os.close(fd)
