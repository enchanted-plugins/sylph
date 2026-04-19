#!/usr/bin/env bash
# Test: GitHubAdapter's urllib path resolves tokens correctly and calls the
# right HTTP endpoints with the right payloads. Uses a mocked urlopen so no
# network traffic hits GitHub.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

export PYTHONIOENCODING=utf-8
out="$("$PY" - <<PYEOF
import io, json, os, sys
from unittest.mock import patch, MagicMock
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

# Clear any inherited env so resolve_token doesn't pick up a real token.
os.environ.pop("GH_TOKEN", None)
os.environ.pop("GITHUB_TOKEN", None)

from adapters import github as G

# ── 1) resolve_token prefers GH_TOKEN ───────────────────────────────────
os.environ["GH_TOKEN"] = "TOKEN_FROM_ENV"
tok = G.resolve_token()
print("ok " if tok == "TOKEN_FROM_ENV" else "FAIL", "resolve_token prefers GH_TOKEN")
del os.environ["GH_TOKEN"]

# ── 2) resolve_token falls back to GITHUB_TOKEN ─────────────────────────
os.environ["GITHUB_TOKEN"] = "TOKEN_FROM_GITHUB_VAR"
tok = G.resolve_token()
print("ok " if tok == "TOKEN_FROM_GITHUB_VAR" else "FAIL", "resolve_token falls back to GITHUB_TOKEN")
del os.environ["GITHUB_TOKEN"]

# ── 3) resolve_token parses git credential fill output ──────────────────
fake_fill = MagicMock(returncode=0, stdout="protocol=https\nhost=github.com\nusername=x\npassword=TOKEN_FROM_GITCRED\n")
with patch.object(G.subprocess, "run", return_value=fake_fill):
    tok = G.resolve_token()
print("ok " if tok == "TOKEN_FROM_GITCRED" else f"FAIL (got {tok!r})", "resolve_token parses git credential fill")

# ── 4) open_pr via urllib hits POST /pulls with correct payload ─────────
class FakeResp:
    def __init__(self, payload):
        self._payload = json.dumps(payload).encode("utf-8")
    def __enter__(self): return self
    def __exit__(self, *a): return None
    def read(self): return self._payload

calls = []  # list of (method, url, headers, body-or-None)
def fake_urlopen(req, timeout=30):
    calls.append((
        req.get_method(),
        req.full_url,
        {k.lower(): v for k, v in req.headers.items()},
        req.data.decode("utf-8") if req.data else None,
    ))
    return FakeResp({
        "number": 42, "html_url": "https://github.com/owner/repo/pull/42",
        "state": "open", "draft": True, "merged": False,
        "title": "test title", "body": "test body",
        "base": {"ref": "main"}, "head": {"ref": "feat/x"},
        "requested_reviewers": [{"login": "alice"}],
        "node_id": "PR_kwDOxxxx",
    })

adapter = G.GitHubAdapter(token="TOKEN_EXPLICIT")
with patch.object(G.urllib.request, "urlopen", side_effect=fake_urlopen):
    pr = adapter.open_pr("owner/repo", "main", "feat/x", "test title", "test body", draft=True)

# First call must be the POST /pulls.
post_call = calls[0]
method, url, headers, body = post_call
print("ok " if pr.number == 42 else f"FAIL (number={pr.number})", "open_pr returns PR with correct number")
print("ok " if pr.state == "draft" else f"FAIL (state={pr.state})", "open_pr returns state=draft when draft=True")
print("ok " if "owner/repo/pulls" in url else f"FAIL (url={url})", "POST to /repos/owner/repo/pulls")
print("ok " if method == "POST" else f"FAIL ({method})", "HTTP method = POST")
print("ok " if headers.get("authorization") == "Bearer TOKEN_EXPLICIT" else "FAIL", "Authorization header carries bearer token")
print("ok " if headers.get("x-github-api-version") == "2022-11-28" else "FAIL", "X-GitHub-Api-Version header present")
body_parsed = json.loads(body)
print("ok " if body_parsed["draft"] is True else "FAIL", "payload.draft=True")
print("ok " if body_parsed["head"] == "feat/x" else "FAIL", "payload.head=feat/x")
print("ok " if body_parsed["base"] == "main" else "FAIL", "payload.base=main")
# After POST, open_pr calls GET /pulls/N for the full record.
print("ok " if any(c[0] == "GET" and "/pulls/42" in c[1] for c in calls) else "FAIL", "follow-up GET /pulls/42 to refresh state")

# ── 5) get_pr maps REST payload correctly ──────────────────────────────
with patch.object(G.urllib.request, "urlopen", side_effect=fake_urlopen):
    pr2 = adapter.get_pr("owner/repo", 42)
print("ok " if pr2.url == "https://github.com/owner/repo/pull/42" else "FAIL", "url from html_url")
print("ok " if pr2.reviewers == ["alice"] else f"FAIL ({pr2.reviewers})", "reviewers from requested_reviewers")

# ── 6) merged state overrides open state ───────────────────────────────
def fake_merged(req, timeout=30):
    return FakeResp({
        "number": 42, "state": "closed", "merged": True, "draft": False,
        "title": "t", "body": "b", "base": {"ref": "main"}, "head": {"ref": "f"},
        "html_url": "u", "requested_reviewers": [],
    })
with patch.object(G.urllib.request, "urlopen", side_effect=fake_merged):
    pr3 = adapter.get_pr("o/r", 42)
print("ok " if pr3.state == "merged" else f"FAIL (state={pr3.state})", "merged:true → state=merged")

# ── 7) is_authenticated True when token is set ─────────────────────────
a2 = G.GitHubAdapter(token="X")
print("ok " if a2.is_authenticated() else "FAIL", "is_authenticated=True with explicit token")

# ── 8) no token + no gh → raise on open_pr ─────────────────────────────
a3 = G.GitHubAdapter()
# Clear env + force token probe to return None.
for v in ("GH_TOKEN", "GITHUB_TOKEN"):
    os.environ.pop(v, None)
with patch.object(G, "resolve_token", return_value=None), patch.object(G.shutil, "which", return_value=None):
    try:
        a3._token_explicit = None
        a3._token_cached = None
        a3._token_probed = False
        a3.open_pr("o/r", "m", "f", "t", "b")
        print("FAIL  no-token no-gh should raise")
    except G.NotImplementedHostOp:
        print("ok  no-token no-gh raises NotImplementedHostOp")
PYEOF
)"

echo "$out"
if printf '%s' "$out" | grep -q '^FAIL'; then
    fail "one or more GitHub urllib-path cases failed"
fi
ok "resolve_token + urllib POST/GET + state parsing + auth guard (8 cases)"
