"""
Weaver registry loader — single source of truth for adapter config.

Two registry JSON files live under `plugins/`:

  - plugins/capability-memory/state/capability-registry.json  (10 hosts)
  - plugins/ci-reader/state/ci-registry.json                  (10 CI systems)

Host and CI adapters import from here instead of hardcoding values like
`api_base`, rate limits, auth modes, or webhook signing algorithms. The
registry is the data-rich source; the adapter code is the behavior.

Path resolution:

  1. $WEAVER_HOME/plugins/{capability-memory,ci-reader}/state/*-registry.json
  2. Walk up from this module's __file__ looking for `plugins/.../state/*.json`

If a registry can't be found, every top-level lookup raises
RegistryError — we fail loudly (per the Weaver contract) rather than
silently degrade.

Stdlib only. Results cached with functools.lru_cache.
"""

from __future__ import annotations

import functools
import json
import os
from pathlib import Path
from typing import Any

_CAPABILITY_REL = ("plugins", "capability-memory", "state", "capability-registry.json")
_CI_REL = ("plugins", "ci-reader", "state", "ci-registry.json")


class RegistryError(RuntimeError):
    """Raised when a registry file can't be located or parsed."""


def _weaver_home_candidate(parts: tuple[str, ...]) -> Path | None:
    home = os.environ.get("WEAVER_HOME")
    if not home:
        return None
    p = Path(home).joinpath(*parts)
    return p if p.is_file() else None


def _walk_up_candidate(parts: tuple[str, ...]) -> Path | None:
    """Walk up from this module looking for `<ancestor>/<parts>`."""
    here = Path(__file__).resolve()
    for ancestor in here.parents:
        p = ancestor.joinpath(*parts)
        if p.is_file():
            return p
    return None


def _resolve_registry_path(parts: tuple[str, ...], label: str) -> Path:
    """Find a registry JSON on disk; raise RegistryError if it's missing."""
    p = _weaver_home_candidate(parts) or _walk_up_candidate(parts)
    if p is None:
        raise RegistryError(
            f"{label} registry not found: expected "
            f"{os.path.sep.join(parts)} under $WEAVER_HOME or an ancestor of "
            f"{__file__}. Set WEAVER_HOME or run from within the Weaver repo."
        )
    return p


def _load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        raise RegistryError(f"{label} registry at {path} could not be read: {e}") from e
    if not isinstance(data, dict):
        raise RegistryError(f"{label} registry at {path} is not a JSON object")
    return data


# ──────────────────────────────────────────────────────────────────────
# Public API — cached for the process lifetime
# ──────────────────────────────────────────────────────────────────────


@functools.lru_cache(maxsize=1)
def _capability_doc() -> dict[str, Any]:
    path = _resolve_registry_path(_CAPABILITY_REL, "capability")
    return _load_json(path, "capability")


@functools.lru_cache(maxsize=1)
def _ci_doc() -> dict[str, Any]:
    path = _resolve_registry_path(_CI_REL, "CI")
    return _load_json(path, "CI")


def load_capability_registry() -> dict[str, dict[str, Any]]:
    """Return the `hosts` dict from the capability registry, keyed by id.

    Raises RegistryError if the registry is missing or malformed.
    """
    doc = _capability_doc()
    hosts = doc.get("hosts")
    if not isinstance(hosts, dict):
        raise RegistryError("capability-registry.json missing `hosts` object")
    return hosts


def load_ci_registry() -> dict[str, dict[str, Any]]:
    """Return the `systems` dict from the CI registry, keyed by id.

    Raises RegistryError if the registry is missing or malformed.
    """
    doc = _ci_doc()
    systems = doc.get("systems")
    if not isinstance(systems, dict):
        raise RegistryError("ci-registry.json missing `systems` object")
    return systems


def get_host(host_id: str) -> dict[str, Any]:
    """Return the registry entry for a single host.

    Raises KeyError if the host id isn't in the registry. This is
    deliberately a KeyError (not RegistryError) so callers can handle it
    differently from a missing/broken registry.
    """
    hosts = load_capability_registry()
    if host_id not in hosts:
        raise KeyError(f"host id not in capability registry: {host_id}")
    entry = hosts[host_id]
    if not isinstance(entry, dict):
        raise RegistryError(f"host {host_id} registry entry is not a JSON object")
    return entry


def get_ci_system(system_id: str) -> dict[str, Any]:
    """Return the registry entry for a single CI system.

    Raises KeyError if the system id isn't in the registry.
    """
    systems = load_ci_registry()
    if system_id not in systems:
        raise KeyError(f"CI system id not in registry: {system_id}")
    entry = systems[system_id]
    if not isinstance(entry, dict):
        raise RegistryError(f"CI system {system_id} registry entry is not a JSON object")
    return entry


def clear_cache() -> None:
    """Drop cached registry data. Used by tests that mutate the file on disk.

    Production code shouldn't call this — the registry is immutable within
    a process. Tests that simulate registry edits use this to force re-read.
    """
    _capability_doc.cache_clear()
    _ci_doc.cache_clear()


# ──────────────────────────────────────────────────────────────────────
# Import-time sanity: fail loudly if neither registry can be resolved.
# We probe paths (not full load) so import is cheap but broken setups
# surface immediately rather than at first use.
# ──────────────────────────────────────────────────────────────────────

_resolve_registry_path(_CAPABILITY_REL, "capability")
_resolve_registry_path(_CI_REL, "CI")
