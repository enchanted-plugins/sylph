#!/usr/bin/env bash
# Test: registry_loader provides cached, stdlib-only access to the two
# Sylph registries (capability + CI). Fails loudly when a registry is
# missing; roundtrips through get_host / get_ci_system; respects cache;
# cache can be invalidated via clear_cache().
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=./helpers.sh
source "$SCRIPT_DIR/helpers.sh"

new_sandbox > /dev/null
tmp="$(py_path "$SANDBOX")"
tmp_shell="$SANDBOX"

# ── 1. load_capability_registry returns 10 hosts keyed by id ──────────
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from registry_loader import load_capability_registry
hosts = load_capability_registry()
print("count=" + str(len(hosts)))
print("has_github=" + str("github" in hosts))
print("has_sourcehut=" + str("sourcehut" in hosts))
print("github_api_base=" + hosts["github"]["api_base"])
PYEOF
)"
assert_contains "$out" "count=10" "capability registry has 10 hosts"
assert_contains "$out" "has_github=True" "github host present"
assert_contains "$out" "has_sourcehut=True" "sourcehut host present"
assert_contains "$out" "github_api_base=https://api.github.com" "github api_base matches registry"
ok "load_capability_registry returns 10 hosts with expected values"

# ── 2. load_ci_registry returns 10 systems ────────────────────────────
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from registry_loader import load_ci_registry
systems = load_ci_registry()
print("count=" + str(len(systems)))
print("has_gha=" + str("github_actions" in systems))
print("has_tekton=" + str("tekton" in systems))
PYEOF
)"
assert_contains "$out" "count=10" "ci registry has 10 systems"
assert_contains "$out" "has_gha=True" "github_actions present"
assert_contains "$out" "has_tekton=True" "tekton present"
ok "load_ci_registry returns 10 systems"

# ── 3. get_host + get_ci_system single-entry lookup ───────────────────
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from registry_loader import get_host, get_ci_system
gh = get_host("github")
print("id=" + gh["id"])
print("support_level=" + gh["support_level"])
gha = get_ci_system("github_actions")
print("ci_id=" + gha["id"])
PYEOF
)"
assert_contains "$out" "id=github" "get_host returns entry"
assert_contains "$out" "support_level=first-class" "github support_level"
assert_contains "$out" "ci_id=github_actions" "get_ci_system returns entry"
ok "get_host + get_ci_system single-entry lookup"

# ── 4. Unknown id raises KeyError (not silent) ────────────────────────
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from registry_loader import get_host
try:
    get_host("fake-host")
    print("UNEXPECTED_OK")
except KeyError as e:
    print("got_keyerror")
PYEOF
)"
assert_eq "$out" "got_keyerror" "unknown host raises KeyError"
ok "unknown host id raises KeyError"

# ── 5. clear_cache lets tests mutate + reload ─────────────────────────
out="$("$PY" - <<PYEOF
import sys, json, os, shutil
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")

# Prepare a sandboxed SYLPH_HOME with a mutated capability registry.
sandbox = r"$tmp"
os.makedirs(os.path.join(sandbox, "plugins", "capability-memory", "state"), exist_ok=True)
os.makedirs(os.path.join(sandbox, "plugins", "ci-reader", "state"), exist_ok=True)

# Copy real registries into the sandbox, then mutate github.api_base.
real_root = r"$REPO_ROOT_PY"
shutil.copy(
    os.path.join(real_root, "plugins", "ci-reader", "state", "ci-registry.json"),
    os.path.join(sandbox, "plugins", "ci-reader", "state", "ci-registry.json"),
)
cap_src = os.path.join(real_root, "plugins", "capability-memory", "state", "capability-registry.json")
with open(cap_src, encoding="utf-8") as f:
    doc = json.load(f)
doc["hosts"]["github"]["api_base"] = "https://mutated.example.com"
with open(os.path.join(sandbox, "plugins", "capability-memory", "state", "capability-registry.json"), "w", encoding="utf-8") as f:
    json.dump(doc, f)

os.environ["SYLPH_HOME"] = sandbox

# Re-import + clear cache — because registry_loader cached the real file
# at module import time, we call clear_cache() to force re-probe.
import registry_loader
registry_loader.clear_cache()
h = registry_loader.get_host("github")
print("mutated_base=" + h["api_base"])
PYEOF
)"
assert_contains "$out" "mutated_base=https://mutated.example.com" "clear_cache + SYLPH_HOME picks up mutation"
ok "clear_cache() + SYLPH_HOME honor registry mutations"

# ── 6. Walk-up fallback finds registries when SYLPH_HOME is bogus ────
empty="$(mktemp -d)"
empty_py="$(py_path "$empty")"
out="$("$PY" - <<PYEOF 2>&1 || true
import sys, os
os.environ["SYLPH_HOME"] = r"$empty_py"
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
# Walk-up from registry_loader.__file__ should still land on the real
# repo's plugins/… registries. Import must succeed.
import registry_loader
from registry_loader import load_capability_registry
hosts = load_capability_registry()
print("fallback_count=" + str(len(hosts)))
PYEOF
)"
rm -rf "$empty"
assert_contains "$out" "fallback_count=10" "walk-up fallback finds real registry"
ok "walk-up from __file__ finds registries when SYLPH_HOME is bogus"
