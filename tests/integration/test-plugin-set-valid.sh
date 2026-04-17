#!/usr/bin/env bash
# Test: every plugin.json + hooks.json + marketplace.json is valid JSON, the
# marketplace lists every plugin, and 'full' declares all non-meta plugins
# as dependencies.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=../shared/helpers.sh
source "$SCRIPT_DIR/../shared/helpers.sh"

# All plugin.json / hooks.json / marketplace.json parse.
while IFS= read -r f; do
    assert_json_valid "$f" "valid JSON: $f"
done < <(find "$REPO_ROOT" -type f \( -name plugin.json -o -name hooks.json -o -name marketplace.json \) ! -path "*/.git/*")
ok "all JSON config files valid"

# Marketplace lists every plugin that has a .claude-plugin/plugin.json.
MARKETPLACE="$REPO_ROOT/.claude-plugin/marketplace.json"

new_sandbox > /dev/null
mkt_file="$SANDBOX/marketplace-names.txt"
dir_file="$SANDBOX/dir-names.txt"

jq -r '.plugins[].name' "$MARKETPLACE" | tr -d '\r' | sort > "$mkt_file"

: > "$dir_file"
for d in "$REPO_ROOT"/plugins/*/; do
    if [[ -f "$d/.claude-plugin/plugin.json" ]]; then
        jq -r '.name' "$d/.claude-plugin/plugin.json" | tr -d '\r' >> "$dir_file"
    fi
done
sort -o "$dir_file" "$dir_file"

if ! diff -q "$mkt_file" "$dir_file" >/dev/null 2>&1; then
    diff_out="$(diff "$mkt_file" "$dir_file" 2>&1 || true)"
    fail "marketplace plugins != plugin directory names:
$diff_out"
fi
ok "marketplace.json lists every plugin directory (and vice versa)"

# 'full' meta-plugin dependencies cover every non-'full' plugin.
FULL="$REPO_ROOT/plugins/full/.claude-plugin/plugin.json"
full_deps_file="$SANDBOX/full-deps.txt"
expected_deps_file="$SANDBOX/expected-deps.txt"

jq -r '.dependencies[]' "$FULL" | tr -d '\r' | sort > "$full_deps_file"
grep -v '^full$' "$dir_file" | sort > "$expected_deps_file"

if ! diff -q "$full_deps_file" "$expected_deps_file" >/dev/null 2>&1; then
    diff_out="$(diff "$full_deps_file" "$expected_deps_file" 2>&1 || true)"
    fail "full's dependencies don't match non-full plugins:
$diff_out"
fi
ok "full meta-plugin declares every sibling as a dependency"

# Each plugin.json has name, description, version.
for d in "$REPO_ROOT"/plugins/*/; do
    [[ -f "$d/.claude-plugin/plugin.json" ]] || continue
    name="$(basename "$d")"
    for field in name description version; do
        val="$(jq -r --arg f "$field" '.[$f]' "$d/.claude-plugin/plugin.json")"
        if [[ "$val" == "null" || -z "$val" ]]; then
            fail "$name/plugin.json missing field: $field"
        fi
    done
done
ok "every plugin.json has name + description + version"
