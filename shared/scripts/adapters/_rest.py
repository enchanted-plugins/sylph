"""
Shared REST helper for host adapters that speak Bearer-auth JSON HTTP.

GitHub, GitLab, Bitbucket Cloud/DC, Azure DevOps, and Gitea-family all
fit this pattern (modulo header flavor). SourceHut and CodeCommit don't
— they compose their own clients.

Tokens resolved in order:
  1. Adapter-specified env var name ($GITLAB_TOKEN, $GITHUB_TOKEN, etc.)
  2. Generic $SYLPH_<HOST>_TOKEN
  3. `git credential fill` for the adapter's canonical host

Stdlib only.
"""

from __future__ import annotations

import json
import os
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

USER_AGENT = "sylph/0.1.0"


def resolve_token(env_vars: list[str], credential_host: str) -> str | None:
    """Token resolution shared by every REST adapter.

    env_vars: ordered list of environment variable names to check first.
    credential_host: hostname to pass to `git credential fill` as the
        fallback (e.g., "gitlab.com", "bitbucket.org", "dev.azure.com").
    """
    for var in env_vars:
        tok = os.environ.get(var)
        if tok and tok.strip():
            return tok.strip()

    try:
        r = subprocess.run(
            ["git", "credential", "fill"],
            input=f"protocol=https\nhost={credential_host}\n\n",
            capture_output=True,
            text=True,
            timeout=5,
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


class RestError(Exception):
    """Raised on 4xx/5xx HTTP responses from the adapter."""

    def __init__(self, method: str, url: str, status: int, body: str):
        super().__init__(f"{method} {url} failed: {status} — {body[:500]}")
        self.method = method
        self.url = url
        self.status = status
        self.body = body


def api_request(
    method: str,
    url: str,
    *,
    token: str,
    auth_scheme: str = "Bearer",
    body: dict[str, Any] | list[Any] | None = None,
    extra_headers: dict[str, str] | None = None,
    timeout: float = 30.0,
) -> dict[str, Any] | list[Any]:
    """Generic authenticated JSON request.

    Returns parsed JSON (dict or list) or {} for empty responses.
    Raises RestError on non-2xx.
    """
    headers = {
        "Authorization": f"{auth_scheme} {token}" if auth_scheme else token,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)

    data: bytes | None = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"

    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if not raw:
                return {}
            return json.loads(raw.decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            err_body = e.read().decode("utf-8", errors="replace")
        except Exception:
            err_body = ""
        raise RestError(method, url, e.code, err_body) from e
