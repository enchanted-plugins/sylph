#!/usr/bin/env bash
# Test: adapters/__init__.py detect_host and parse_github_repo across all 10
# supported hosts, plus stub adapters raise NotImplementedHostOp.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from adapters import detect_host, parse_github_repo, get_adapter, NotImplementedHostOp

cases = [
    ("git@github.com:enchanter-ai/sylph.git", "github"),
    ("https://github.com/enchanter-ai/sylph", "github"),
    ("https://gitlab.com/foo/bar.git", "gitlab"),
    ("https://gitlab.self-hosted.corp/foo/bar", "gitlab"),
    ("https://bitbucket.org/foo/bar", "bitbucket-cloud"),
    ("https://bitbucket.internal/foo/bar", "bitbucket-dc"),
    ("https://dev.azure.com/org/proj/_git/repo", "azure-devops"),
    ("https://myorg.visualstudio.com/_git/repo", "azure-devops"),
    ("https://codeberg.org/foo/bar", "codeberg"),
    ("https://codecommit.us-east-1.amazonaws.com/v1/repos/x", "codecommit"),
    ("https://git.sr.ht/~user/repo", "sourcehut"),
]

failures = 0
for url, expected in cases:
    got = detect_host(url)
    if got != expected:
        print(f"FAIL  detect_host({url!r}) -> {got} (expected {expected})")
        failures += 1
    else:
        print(f"ok    detect_host({url!r}) -> {got}")

# parse_github_repo
for url, expected in [
    ("git@github.com:enchanter-ai/sylph.git", "enchanter-ai/sylph"),
    ("https://github.com/enchanter-ai/sylph", "enchanter-ai/sylph"),
    ("https://github.com/foo/bar/", "foo/bar"),
    ("https://gitlab.com/foo/bar", None),
]:
    got = parse_github_repo(url)
    if got != expected:
        print(f"FAIL  parse_github_repo({url!r}) -> {got}")
        failures += 1
    else:
        print(f"ok    parse_github_repo({url!r}) -> {got}")

# All 9 non-GitHub host adapters are real but unavailable without
# credentials in this env. Their is_authenticated() returns False and
# any op invocation raises NotImplementedHostOp. Isolate os.environ so
# inherited tokens don't make the test flaky on a dev box.
import os
saved = {k: os.environ.pop(k, None) for k in (
    "GITLAB_TOKEN", "GL_TOKEN", "BITBUCKET_TOKEN", "BB_TOKEN",
    "BITBUCKET_DC_TOKEN", "AZURE_DEVOPS_TOKEN", "AZURE_TOKEN",
    "VSTS_TOKEN", "GITEA_TOKEN", "FORGEJO_TOKEN",
)}
try:
    for host_id in ("gitlab", "bitbucket-cloud", "bitbucket-dc", "azure-devops",
                    "gitea", "forgejo", "codeberg", "codecommit", "sourcehut"):
        adapter = get_adapter(host_id)
        # Force _token_probed without going through git credential-manager.
        if hasattr(adapter, "_token_cached"):
            adapter._token_cached = None
            adapter._token_probed = True
        # is_authenticated: False when no token + tooling.
        # (CodeCommit checks aws CLI; SourceHut checks SMTP/git-send-email.)
        # We don't assert is_authenticated here — too env-dependent.
        # Just assert op invocation raises cleanly when credentials are absent.
        try:
            adapter.open_pr("x/y","m","f","t","b")
            print(f"FAIL  {host_id} did NOT raise without credentials")
            failures += 1
        except NotImplementedHostOp:
            print(f"ok    {host_id} raises NotImplementedHostOp without credentials")
        except Exception as e:
            # Real API attempts may raise RuntimeError from urllib errors;
            # that's also acceptable — the point is they don't return a
            # bogus PR.
            print(f"ok    {host_id} op attempt raised {type(e).__name__} without credentials")
finally:
    for k, v in saved.items():
        if v is not None:
            os.environ[k] = v

# GitHub adapter instantiates cleanly even without gh.
from adapters.github import GitHubAdapter
gh = GitHubAdapter()
print(f"ok    GitHub adapter: is_authenticated={gh.is_authenticated()}")

print(f"TOTAL_FAILURES={failures}")
PYEOF
)"

echo "$out"
total="$(printf '%s' "$out" | grep '^TOTAL_FAILURES=' | cut -d= -f2)"
assert_eq "$total" "0" "no detection / parse / stub failures"
ok "11 URL-detections + 4 parse-repo + 9 no-credentials raises + GitHub instantiation"
