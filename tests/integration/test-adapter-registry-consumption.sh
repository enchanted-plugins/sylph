#!/usr/bin/env bash
# Test: host + CI adapters pull config from the registries (not hardcoded
# literals). We prove this by:
#   1. Asserting adapter.api_base matches the value in capability-registry.json
#      for each HTTP-based host adapter.
#   2. Mutating a temp copy of the capability registry, pointing WEAVER_HOME
#      at it, and confirming the adapter's api_base reflects the mutation.
#   3. Same mutation path for the CI registry via a CI adapter.
#
# This is the anti-regression test: if someone re-hardcodes a value in an
# adapter, the mutation step catches it.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

new_sandbox > /dev/null
tmp_shell="$SANDBOX"
tmp="$(py_path "$SANDBOX")"

# ── 1. Baseline: every HTTP host adapter exposes the registry's api_base ──
out="$("$PY" - <<PYEOF
import os, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

# Strip tokens so adapters don't try to call remotes.
for v in ("GH_TOKEN","GITHUB_TOKEN","GITLAB_TOKEN","GL_TOKEN",
          "BITBUCKET_TOKEN","BB_TOKEN","BITBUCKET_DC_TOKEN",
          "AZURE_DEVOPS_TOKEN","AZURE_TOKEN","VSTS_TOKEN",
          "GITEA_TOKEN","FORGEJO_TOKEN"):
    os.environ.pop(v, None)

from registry_loader import get_host
from adapters import get_adapter

failures = 0

# HTTP hosts where the registry carries a real (non-placeholder) api_base
# that the adapter exposes as self.api_base.
pairs = [
    ("github", "github"),
    ("gitlab", "gitlab"),
    ("bitbucket-cloud", "bitbucket-cloud"),
    ("codeberg", "codeberg"),
]
for host_id, reg_id in pairs:
    adapter = get_adapter(host_id)
    reg = get_host(reg_id)
    reg_base = reg["api_base"].rstrip("/")
    actual = (adapter.api_base or "").rstrip("/")
    if actual != reg_base:
        print(f"FAIL  {host_id}: adapter.api_base={actual!r} != registry={reg_base!r}")
        failures += 1
    else:
        print(f"ok    {host_id}: {actual}")

# Azure DevOps: adapter strips the templated path from the registry base.
adapter = get_adapter("azure-devops")
reg = get_host("azure-devops")
if "dev.azure.com" not in (adapter.api_base or ""):
    print(f"FAIL  azure-devops: adapter.api_base missing host — {adapter.api_base!r}")
    failures += 1
else:
    print(f"ok    azure-devops: {adapter.api_base}")

print(f"TOTAL_FAILURES={failures}")
PYEOF
)"
echo "$out"
total="$(printf '%s' "$out" | grep '^TOTAL_FAILURES=' | cut -d= -f2)"
assert_eq "$total" "0" "every HTTP host adapter reflects its registry api_base"
ok "host adapters pull api_base from capability-registry.json"

# ── 2. Mutation test: change the registry, confirm the adapter picks it up ──
mkdir -p "$tmp_shell/plugins/capability-memory/state" "$tmp_shell/plugins/ci-reader/state"

out="$("$PY" - <<PYEOF
import json, os, shutil, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

sandbox = r"$tmp"
real_root = r"$REPO_ROOT_PY"

shutil.copy(
    os.path.join(real_root, "plugins", "ci-reader", "state", "ci-registry.json"),
    os.path.join(sandbox, "plugins", "ci-reader", "state", "ci-registry.json"),
)
cap_src = os.path.join(real_root, "plugins", "capability-memory", "state", "capability-registry.json")
cap_dst = os.path.join(sandbox, "plugins", "capability-memory", "state", "capability-registry.json")
with open(cap_src, encoding="utf-8") as f:
    doc = json.load(f)
doc["hosts"]["github"]["api_base"] = "https://mutated-github.example.com"
doc["hosts"]["gitlab"]["api_base"] = "https://mutated-gitlab.example.com/api/v4"
with open(cap_dst, "w", encoding="utf-8") as f:
    json.dump(doc, f)

os.environ["WEAVER_HOME"] = sandbox

import registry_loader
registry_loader.clear_cache()

# Re-instantiate adapters: construction-time lookup must read the new file.
from adapters import get_adapter
gh = get_adapter("github")
gl = get_adapter("gitlab")

print(f"github_api_base={gh.api_base}")
print(f"gitlab_api_base={gl.api_base}")
print(f"gitlab_credential_host={gl.credential_host}")
PYEOF
)"
echo "$out"
assert_contains "$out" "github_api_base=https://mutated-github.example.com" \
    "github adapter reflects mutated registry value"
assert_contains "$out" "gitlab_api_base=https://mutated-gitlab.example.com/api/v4" \
    "gitlab adapter reflects mutated registry value"
assert_contains "$out" "gitlab_credential_host=mutated-gitlab.example.com" \
    "gitlab credential_host derived from mutated api_base"
ok "adapters re-read mutated registry at construction time"

# ── 3. CI adapter path: same mutation, observed through a CI adapter ──
out="$("$PY" - <<PYEOF
import json, os, shutil, sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

sandbox = r"$tmp"
real_root = r"$REPO_ROOT_PY"

# Re-copy the ci-registry.json + mutate a field inside.
ci_src = os.path.join(real_root, "plugins", "ci-reader", "state", "ci-registry.json")
ci_dst = os.path.join(sandbox, "plugins", "ci-reader", "state", "ci-registry.json")
with open(ci_src, encoding="utf-8") as f:
    doc = json.load(f)
doc["systems"]["gitlab_ci"]["support_level"] = "MUTATED-MARKER"
with open(ci_dst, "w", encoding="utf-8") as f:
    json.dump(doc, f)

os.environ["WEAVER_HOME"] = sandbox
import registry_loader
registry_loader.clear_cache()

from ci_adapters import get_adapter as get_ci_adapter
gl_ci = get_ci_adapter("gitlab-ci")
print(f"gitlab_ci_support_level={gl_ci.ci_registry['support_level']}")
PYEOF
)"
echo "$out"
assert_contains "$out" "gitlab_ci_support_level=MUTATED-MARKER" \
    "CI adapter reflects mutated ci-registry.json"
ok "CI adapters re-read mutated ci-registry at construction time"

# ── 4. No hardcoded api_base literals remain in adapter signatures ──
# Regression guard: if someone reintroduces a default like
# api_base: str = "https://api.github.com" we catch it here.
bad_count=0
for f in "$REPO_ROOT"/shared/scripts/adapters/*.py "$REPO_ROOT"/shared/scripts/ci_adapters/*.py; do
    # Skip helper modules that don't take api_base.
    case "$(basename "$f")" in
        __init__.py|_rest.py|_http.py|codecommit.py|sourcehut.py|k8s.py|github_actions.py) continue ;;
    esac
    # Match a non-None default URL literal in a signature like
    # `api_base: str = "https://...`. We deliberately allow `api_base: str | None = None`.
    if grep -E '^[[:space:]]*api_base: *str *= *"https?://' "$f" >/dev/null 2>&1; then
        echo "REGRESSION: hardcoded api_base default in $f"
        bad_count=$((bad_count + 1))
    fi
done
assert_eq "$bad_count" "0" "no adapter retains a hardcoded api_base= URL in its signature"
ok "no adapter re-hardcodes api_base in its signature"
