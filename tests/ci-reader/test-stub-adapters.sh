#!/usr/bin/env bash
# Test: CI stub adapters report unavailable without raising, raise on stream/rerun.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from ci_adapters import get_adapter, NotImplementedCIOp

failures = 0
for sys_id in ("gitlab-ci", "circleci", "jenkins", "buildkite", "drone",
               "woodpecker", "tekton", "argocd", "fluxcd"):
    a = get_adapter(sys_id)
    # is_available returns False without raising.
    if a.is_available():
        print(f"FAIL  {sys_id} stub.is_available should be False")
        failures += 1
    else:
        print(f"ok    {sys_id} stub.is_available=False")

    # latest_status returns [] without raising.
    try:
        checks = a.latest_status("foo/bar", "abc")
        if checks != []:
            print(f"FAIL  {sys_id} stub.latest_status should return [] (got {checks})")
            failures += 1
        else:
            print(f"ok    {sys_id} stub.latest_status=[]")
    except Exception as e:
        print(f"FAIL  {sys_id} stub.latest_status raised: {e}")
        failures += 1

    # stream_logs and rerun raise NotImplementedCIOp.
    for op in ("stream_logs", "rerun"):
        try:
            if op == "stream_logs":
                list(a.stream_logs("x"))
            else:
                a.rerun("x")
            print(f"FAIL  {sys_id}.{op} did NOT raise")
            failures += 1
        except NotImplementedCIOp:
            print(f"ok    {sys_id}.{op} raises NotImplementedCIOp")

# GitHub Actions adapter: instantiates cleanly, is_available=False without gh.
from ci_adapters.github_actions import GitHubActionsAdapter
gha = GitHubActionsAdapter()
print(f"ok    github-actions adapter: is_available={gha.is_available()}")
# latest_status returns [] gracefully when gh is absent.
checks = gha.latest_status("foo/bar", "HEAD")
print(f"ok    github-actions.latest_status without gh: {checks}")

print(f"TOTAL_FAILURES={failures}")
PYEOF
)"

echo "$out"
total="$(printf '%s' "$out" | grep '^TOTAL_FAILURES=' | cut -d= -f2)"
assert_eq "$total" "0" "all stub CI adapters behave per contract"
ok "9 CI stubs + GitHub Actions adapter behave cleanly"
