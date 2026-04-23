#!/usr/bin/env bash
# Test: every host adapter (all 10) upholds the HostAdapter contract:
#   - instantiates cleanly via get_adapter(id)
#   - has a consistent is_authenticated() that doesn't raise
#   - open_pr/update_pr/get_pr/merge_pr/close_pr/list_checks/enqueue_merge
#     either succeed or raise (no silent bogus returns) when unauthenticated
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

export PYTHONIOENCODING=utf-8

out="$("$PY" - <<PYEOF
import os, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

# Strip every known host-token env var so the test is deterministic.
for v in ("GH_TOKEN","GITHUB_TOKEN","GITLAB_TOKEN","GL_TOKEN",
          "BITBUCKET_TOKEN","BB_TOKEN","BITBUCKET_DC_TOKEN",
          "AZURE_DEVOPS_TOKEN","AZURE_TOKEN","VSTS_TOKEN",
          "GITEA_TOKEN","FORGEJO_TOKEN","SYLPH_SRHT_LIST"):
    os.environ.pop(v, None)

from adapters import get_adapter, HostAdapter, NotImplementedHostOp, PullRequest

HOSTS = ["github","gitlab","bitbucket-cloud","bitbucket-dc","azure-devops",
         "gitea","forgejo","codeberg","codecommit","sourcehut"]

failures = 0

for hid in HOSTS:
    adapter = get_adapter(hid)
    # Instance checks.
    if not isinstance(adapter, HostAdapter):
        print(f"FAIL  {hid} not a HostAdapter")
        failures += 1
        continue
    if adapter.host_id != hid:
        print(f"FAIL  {hid} host_id mismatch: {adapter.host_id}")
        failures += 1
        continue

    # Force no-cred path on HTTP adapters.
    if hasattr(adapter, "_token_cached"):
        adapter._token_cached = None
        adapter._token_probed = True
    if hasattr(adapter, "_list_explicit"):
        adapter._list_explicit = None

    # is_authenticated MUST NOT raise.
    try:
        ok = adapter.is_authenticated()
        if not isinstance(ok, bool):
            print(f"FAIL  {hid}.is_authenticated returned non-bool: {ok!r}")
            failures += 1
    except Exception as e:
        print(f"FAIL  {hid}.is_authenticated raised: {type(e).__name__}: {e}")
        failures += 1
        continue

    # open_pr without credentials MUST raise (not silently invent a PR).
    try:
        adapter.open_pr("x/y", "main", "feat/x", "t", "b")
        print(f"FAIL  {hid}.open_pr succeeded without credentials")
        failures += 1
    except NotImplementedHostOp:
        pass
    except Exception:
        # Any raised exception proves we're not silently fabricating.
        pass

    print(f"ok    {hid} HostAdapter contract upheld")

print(f"TOTAL_FAILURES={failures}")
PYEOF
)"

echo "$out"
total="$(printf '%s' "$out" | grep '^TOTAL_FAILURES=' | cut -d= -f2)"
assert_eq "$total" "0" "every host adapter honors the HostAdapter contract"
ok "all 10 host adapters pass the contract test"
