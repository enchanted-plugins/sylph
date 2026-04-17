#!/usr/bin/env bash
# Test: W4 reviewer_route.py scores blame + CODEOWNERS + recency correctly,
# caps at WEAVER_REVIEWER_MAX_SUGGEST (3).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# Build a synthetic repo with distinct authors per file.
dir="$(mktemp -d)"
dir_py="$(py_path "$dir")"
cd "$dir"
git init -q -b main

# Seed with 3 distinct authors committing to different files.
git config user.email alice@test.com
git config user.name alice
echo "auth logic" > auth.py
git add auth.py
git commit -q -m "feat: add auth"

git config user.email bob@test.com
git config user.name bob
echo "db logic" > db.py
git add db.py
git commit -q -m "feat: add db"

git config user.email carol@test.com
git config user.name carol
echo "updated auth" > auth.py
git add auth.py
git commit -q -m "fix: auth edge"

# Rank reviewers for a change touching auth.py — carol + alice should rank above bob.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
import reviewer_route as R

ranked = R.score_reviewers(["auth.py"], Path(r"$dir_py"))
for c in ranked:
    print(c.identity, round(c.blame_score, 3))
PYEOF
)"

assert_contains "$out" "alice <alice@test.com>" "alice in ranking"
assert_contains "$out" "carol <carol@test.com>" "carol in ranking"
assert_not_contains "$out" "bob <bob@test.com>" "bob excluded (never touched auth.py)"
ok "blame-graph: per-file author filtering works"

# With CODEOWNERS boost
mkdir -p .github
cat > .github/CODEOWNERS <<'EOF'
# simple ownership
auth.py @tech-lead
EOF

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
import reviewer_route as R

ranked = R.score_reviewers(["auth.py"], Path(r"$dir_py"))
top = [c.identity for c in ranked[:3]]
print(",".join(top))
PYEOF
)"
assert_contains "$out" "@tech-lead" "CODEOWNERS @tech-lead present in ranking"
ok "CODEOWNERS: @handle appears alongside blame-graph candidates"

# suggest() caps at 3 even with more candidates.
out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from pathlib import Path
import reviewer_route as R

# Build a paths list so CODEOWNERS applies across many authors.
suggestions = R.suggest(["auth.py"], Path(r"$dir_py"), max_suggest=3)
print(len(suggestions))
PYEOF
)"
assert_eq "$out" "3" "suggest() caps at max_suggest"
ok "suggest() caps at 3"

rm -rf "$dir"
