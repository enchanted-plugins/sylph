#!/usr/bin/env bash
# Weaver shared sanitization utilities

sanitize_path() {
  local path="$1"
  local project_root="${2:-}"
  [[ -z "$path" ]] && return 1

  # Decode URL-encoded path traversal
  # Two-pass decode to catch double-encoding (%252e → %2e → .)
  local decoded
  decoded=$(printf "%s" "$path" \
    | sed -e 's/%25/%/g' -e 's/%2[eE]/./g' -e 's/%2[fF]/\//g' \
    | sed -e 's/%25/%/g' -e 's/%2[eE]/./g' -e 's/%2[fF]/\//g')

  # Block path traversal (..)
  if [[ "$decoded" == *".."* ]]; then return 1; fi

  # Block null bytes
  if printf "%s" "$decoded" | grep -qP '\x00' 2>/dev/null; then return 1; fi

  # If project_root is set, ensure path is under it
  if [[ -n "$project_root" ]]; then
    case "$decoded" in
      /*) ;; # already absolute — OK
      *)  decoded="${project_root}/${decoded}" ;;
    esac
    # Normalize away single dots
    decoded=$(printf "%s" "$decoded" | sed 's|/\./|/|g; s|/\.$||')
    case "$decoded" in
      "${project_root}"*) ;; # under project root — OK
      *) return 1 ;;
    esac
  fi

  echo "$decoded"
  return 0
}

validate_json() {
  printf "%s" "$1" | jq empty >/dev/null 2>&1
}

sanitize_for_log() {
  printf "%s" "$1" \
    | sed -E \
      -e 's/(sk-ant-[a-zA-Z0-9]+)/[REDACTED]/g' \
      -e 's/(shpss_[a-zA-Z0-9]+)/[REDACTED]/g' \
      -e 's/(password|secret|token)=[^ ]*/\1=[REDACTED]/gi'
}
