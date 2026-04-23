#!/usr/bin/env bash
# Test: merge_queue_gate.check_gate across the canonical traffic-light
# matrix (green / red / yellow / unknown) + strict-flag promotion +
# pr_lifecycle.promote_to_ready routing.
#
# The adapters themselves are never called — we override CI status via
# the `SYLPH_TEST_CI_STATUS` env var (a JSON fixture path). This keeps
# the test offline and independent of `gh`, kubeconfig, etc.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

FIXTURE_DIR="$(mktemp -d)"
trap 'rm -rf "$FIXTURE_DIR"; cleanup_sandbox' EXIT

# ──────────────────────────────────────────────────────────────────────
# Case 1: all green -> allow
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/green.json" <<'JSON'
{
  "github-actions": [
    {"name": "build", "status": "completed", "conclusion": "success"},
    {"name": "unit-tests", "status": "completed", "conclusion": "success"}
  ],
  "gitlab-ci": [
    {"name": "lint", "status": "completed", "conclusion": "success"}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/green.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "allow"' "all-green yields allow"
assert_not_contains "$out" '"decision": "block"' "no block on all-green"
ok "case 1: all green -> allow"

# ──────────────────────────────────────────────────────────────────────
# Case 2: one red -> block, with reason referencing the check name
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/red.json" <<'JSON'
{
  "github-actions": [
    {"name": "build", "status": "completed", "conclusion": "success"},
    {"name": "test-integration", "status": "completed", "conclusion": "failure"}
  ],
  "gitlab-ci": [
    {"name": "lint", "status": "completed", "conclusion": "success"}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/red.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "block"' "any red yields block"
assert_contains "$out" "test-integration" "reason names the failing check"
assert_contains "$out" "failure" "reason surfaces the failure conclusion"
ok "case 2: one red -> block with failing-check reason"

# ──────────────────────────────────────────────────────────────────────
# Case 3: pending (in_progress) -> block "still running"
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/yellow.json" <<'JSON'
{
  "github-actions": [
    {"name": "build", "status": "completed", "conclusion": "success"},
    {"name": "deploy", "status": "in_progress", "conclusion": null}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/yellow.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "block"' "pending yields block"
assert_contains "$out" "still running" "reason explains pending"
ok "case 3: pending -> block (still running)"

# ──────────────────────────────────────────────────────────────────────
# Case 4: no eligible status / empty fixture -> unknown (not silent allow)
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/empty.json" <<'JSON'
{}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/empty.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "unknown"' "empty fixture yields unknown"
assert_not_contains "$out" '"decision": "allow"' "empty fixture must not auto-allow"
ok "case 4: empty status -> unknown (never silent allow)"

# ──────────────────────────────────────────────────────────────────────
# Case 5: --strict promotes unknown to block
# ──────────────────────────────────────────────────────────────────────
out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github", strict=True)
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "block"' "strict flag promotes unknown -> block"
ok "case 5: strict unknown -> block"

# ──────────────────────────────────────────────────────────────────────
# Case 6: unknown host -> unknown (no registry entry)
# ──────────────────────────────────────────────────────────────────────
out="$("$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="unknown")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "unknown"' "unknown host -> unknown decision"
assert_contains "$out" "no registry entry for host unknown" "unknown host reason is specific"
ok "case 6: unknown host -> unknown with explicit reason"

# ──────────────────────────────────────────────────────────────────────
# Case 7: read-only CI (ArgoCD/WixieCD) is not auto-queried.
# A red fixture for WixieCD should be ignored — it's not gate-eligible.
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/wixiecd-red.json" <<'JSON'
{
  "wixiecd": [
    {"name": "reconcile", "status": "completed", "conclusion": "ReconciliationFailed"}
  ],
  "github-actions": [
    {"name": "build", "status": "completed", "conclusion": "success"}
  ],
  "gitlab-ci": [
    {"name": "lint", "status": "completed", "conclusion": "success"}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/wixiecd-red.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from merge_queue_gate import check_gate
r = check_gate({"head_sha": "abc123"}, host_id="github")
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"decision": "allow"' "wixiecd red is ignored (not gate-eligible)"
ok "case 7: read-only CI systems skipped per registry"

# ──────────────────────────────────────────────────────────────────────
# Case 8: pr_lifecycle.promote_to_ready routes through the gate.
# A red CI must yield promoted:False with the gate attached.
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/promote-red.json" <<'JSON'
{
  "github-actions": [
    {"name": "test", "status": "completed", "conclusion": "failure"}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/promote-red.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
from pathlib import Path
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pr_lifecycle import promote_to_ready
r = promote_to_ready(
    Path(r"$SHARED_SCRIPTS_PY"),
    host_id="github",
    head_sha="abc123",
)
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"promoted": false' "red CI blocks promote_to_ready"
assert_contains "$out" '"decision": "block"' "gate record is attached"
ok "case 8: promote_to_ready blocks on red CI"

# ──────────────────────────────────────────────────────────────────────
# Case 9: promote_to_ready allows when CI is green.
# ──────────────────────────────────────────────────────────────────────
cat > "$FIXTURE_DIR/promote-green.json" <<'JSON'
{
  "github-actions": [
    {"name": "test", "status": "completed", "conclusion": "success"}
  ],
  "gitlab-ci": [
    {"name": "lint", "status": "completed", "conclusion": "success"}
  ]
}
JSON
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/promote-green.json")"

out="$(SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" - <<PYEOF
import sys, json
from pathlib import Path
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pr_lifecycle import promote_to_ready
r = promote_to_ready(
    Path(r"$SHARED_SCRIPTS_PY"),
    host_id="github",
    head_sha="abc123",
)
print(json.dumps(r))
PYEOF
)"

assert_contains "$out" '"promoted": true' "green CI allows promote_to_ready"
ok "case 9: promote_to_ready allows on green CI"

# ──────────────────────────────────────────────────────────────────────
# Case 10: CLI round-trip — exit codes match decision.
# ──────────────────────────────────────────────────────────────────────
FIXTURE_PATH="$(py_path "$FIXTURE_DIR/green.json")"
set +e
SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" "$SHARED_SCRIPTS_PY/merge_queue_gate.py" \
    --host github --ref abc123 --json >/dev/null 2>&1
rc_allow=$?
set -e
assert_exit_code 0 "$rc_allow" "CLI exit 0 on allow"

FIXTURE_PATH="$(py_path "$FIXTURE_DIR/red.json")"
set +e
SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" "$SHARED_SCRIPTS_PY/merge_queue_gate.py" \
    --host github --ref abc123 --json >/dev/null 2>&1
rc_block=$?
set -e
assert_exit_code 1 "$rc_block" "CLI exit 1 on block"

FIXTURE_PATH="$(py_path "$FIXTURE_DIR/empty.json")"
set +e
SYLPH_TEST_CI_STATUS="$FIXTURE_PATH" "$PY" "$SHARED_SCRIPTS_PY/merge_queue_gate.py" \
    --host github --ref abc123 --json >/dev/null 2>&1
rc_unknown=$?
set -e
assert_exit_code 2 "$rc_unknown" "CLI exit 2 on unknown"
ok "case 10: CLI exit codes track decision (0/1/2)"
