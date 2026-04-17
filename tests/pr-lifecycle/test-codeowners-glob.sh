#!/usr/bin/env bash
# Test: reviewer_route _glob_match handles CODEOWNERS glob semantics.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

out="$("$PY" - <<PYEOF
import sys
sys.path.insert(0, r"$SHARED_SCRIPTS_PY")
from reviewer_route import _glob_match

cases = [
    # (path, glob, expected)
    ("src/auth/oauth.py", "src/auth/*", True),            # '*' within a segment
    ("src/auth/sub/foo.py", "src/auth/*", False),          # '*' doesn't cross '/'
    ("src/auth/sub/foo.py", "src/auth/**", True),          # '**' crosses segments
    ("src/auth/oauth.py", "/src/auth/*", True),            # leading '/' = anchored
    ("foo/src/auth/x.py", "/src/auth/*", False),           # anchored: must start with /src
    ("src/auth/", "src/auth/", True),                      # trailing '/' dir match
    ("src/auth/x.py", "src/auth/", True),                   # trailing '/' also matches contents
    ("README.md", "*.md", True),                           # literal extension match
    ("docs/README.md", "*.md", True),                     # non-anchored
    ("docs/README.rst", "*.md", False),                   # non-match
]

for path, glob, expected in cases:
    got = _glob_match(path, glob)
    print(f"{'ok ' if got == expected else 'FAIL'}  glob_match({path!r}, {glob!r}) -> {got} (expected {expected})")
PYEOF
)"

echo "$out"
if printf '%s' "$out" | grep -q 'FAIL'; then
    fail "one or more glob cases failed"
fi
ok "CODEOWNERS glob semantics: 10 cases pass"
