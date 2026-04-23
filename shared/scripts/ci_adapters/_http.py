"""
Shared REST helper for CI adapters. Mirrors adapters/_rest.py — GitHub
Actions, GitLab CI, CircleCI, Buildkite, Drone, Woodpecker, Jenkins
all fit the Bearer-auth JSON pattern.

Separate module from adapters/_rest.py so CI and host packages evolve
independently; the contract is identical.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.request
from typing import Any

USER_AGENT = "sylph/0.1.0"


def resolve_token(env_vars: list[str], credential_host: str | None) -> str | None:
    """Identical to adapters/_rest.resolve_token — duplicated to keep
    the CI package import-isolated from hosts."""
    for var in env_vars:
        tok = os.environ.get(var)
        if tok and tok.strip():
            return tok.strip()

    if not credential_host:
        return None

    try:
        r = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={credential_host}\n\n",
            capture_output=True, text=True, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return None
    if r.returncode != 0:
        return None
    for line in r.stdout.splitlines():
        if line.startswith("password="):
            tok = line[len("password="):]
            return tok if tok else None
    return None


class CIHttpError(Exception):
    def __init__(self, method: str, url: str, status: int, body: str):
        super().__init__(f"{method} {url} failed: {status}: {body[:300]}")
        self.status = status


def get_json(
    url: str,
    *,
    token: str | None = None,
    auth_scheme: str = "Bearer",
    extra_headers: dict[str, str] | None = None,
    timeout: float = 20.0,
) -> Any:
    """Authenticated GET → parsed JSON. None-valued token omits auth header
    (useful for Drone/Woodpecker + some self-hosted Jenkins)."""
    headers = {
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"{auth_scheme} {token}" if auth_scheme else token
    if extra_headers:
        headers.update(extra_headers)

    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return json.loads(raw.decode("utf-8")) if raw else {}
    except urllib.error.HTTPError as e:
        try:
            body = e.read().decode("utf-8", errors="replace")
        except Exception:
            body = ""
        raise CIHttpError("GET", url, e.code, body) from e
