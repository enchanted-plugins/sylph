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
    ("git@github.com:enchanted-plugins/weaver.git", "github"),
    ("https://github.com/enchanted-plugins/weaver", "github"),
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
    ("git@github.com:enchanted-plugins/weaver.git", "enchanted-plugins/weaver"),
    ("https://github.com/enchanted-plugins/weaver", "enchanted-plugins/weaver"),
    ("https://github.com/foo/bar/", "foo/bar"),
    ("https://gitlab.com/foo/bar", None),
]:
    got = parse_github_repo(url)
    if got != expected:
        print(f"FAIL  parse_github_repo({url!r}) -> {got}")
        failures += 1
    else:
        print(f"ok    parse_github_repo({url!r}) -> {got}")

# Stub adapters raise
for host_id in ("gitlab", "bitbucket-cloud", "bitbucket-dc", "azure-devops",
                "gitea", "forgejo", "codeberg", "codecommit", "sourcehut"):
    try:
        get_adapter(host_id).open_pr("x/y","m","f","t","b")
        print(f"FAIL  {host_id} stub did NOT raise")
        failures += 1
    except NotImplementedHostOp:
        print(f"ok    {host_id} stub raises NotImplementedHostOp")

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
ok "11 URL-detections + 4 parse-repo + 9 stub-raises + GitHub instantiation"
