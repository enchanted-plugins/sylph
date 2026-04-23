#!/usr/bin/env bash
# Sylph atomic-state helper — pure-bash wrapper over the Emu-A4 pattern.
#
# Hooks that don't want to spawn Python source this file and call:
#
#   atomic_read   <path>                     # cat or echo {} if missing
#   atomic_write  <path> < input_json        # via mktemp + mv
#   atomic_append <path> < record_json       # via flock + cat >>
#
# Portable to macOS bash 3.2: no `mapfile`, no `[[ -v ]]`, no `${var,,}`.
# Zero external runtime deps (brand standard).

# Guard against multiple sourcing.
if [ -n "${_SYLPH_ATOMIC_STATE_SH_SOURCED:-}" ]; then return 0 2>/dev/null || exit 0; fi
_SYLPH_ATOMIC_STATE_SH_SOURCED=1

# ── atomic_read <path> ────────────────────────────────────────────────
# Prints the file contents, or `{}` if the file is missing or empty.
atomic_read() {
    local path="$1"
    if [ -s "$path" ]; then
        cat "$path"
    else
        printf '%s\n' '{}'
    fi
}

# ── atomic_write <path> < input_json ──────────────────────────────────
# Reads JSON from stdin, writes to a sibling tempfile, then `mv` (atomic on
# the same filesystem since source + target share a directory). Creates
# parent dirs on demand.
atomic_write() {
    local path="$1"
    local dir
    dir="$(dirname "$path")"
    mkdir -p "$dir"

    # mktemp with a template rooted in the target dir so `mv` stays intra-fs.
    local base
    base="$(basename "$path")"
    local tmp
    tmp="$(mktemp "${dir}/.${base}.XXXXXX")" || return 1

    if ! cat > "$tmp"; then
        rm -f "$tmp"
        return 1
    fi

    # POSIX mv over existing target is atomic on the same filesystem.
    mv -f "$tmp" "$path"
}

# ── atomic_append <path> < record_json ────────────────────────────────
# Reads one JSON record from stdin, ensures trailing newline, appends under
# an exclusive flock. On systems without flock (rare), falls back to a
# best-effort single-write append (atomic for sub-PIPE_BUF payloads under
# O_APPEND on POSIX).
atomic_append() {
    local path="$1"
    local dir
    dir="$(dirname "$path")"
    mkdir -p "$dir"
    # Ensure the target exists before opening it for the lock.
    [ -e "$path" ] || : > "$path"

    # Read the entire stdin as one JSON record.
    local record
    record="$(cat)"
    [ -z "$record" ] && return 0
    # Strip trailing newline; we always emit exactly one.
    record="${record%$'\n'}"

    if command -v flock >/dev/null 2>&1; then
        # File-path form of flock is the portable choice: the fd-form breaks
        # on MSYS/Cygwin because the external flock binary can't see the
        # parent shell's fds. A sidecar `.lock` file gives us the same
        # mutex semantics; the final write still goes through O_APPEND.
        local lockfile="${path}.lock"
        # `: > "$lockfile"` would race — just touch it if absent.
        [ -e "$lockfile" ] || : > "$lockfile" 2>/dev/null || true
        # Serialize the single-write append. `$record` is already one line
        # with trailing newline added by printf.
        flock -x -w 10 "$lockfile" sh -c 'printf "%s\n" "$1" >> "$2"' _ "$record" "$path"
    else
        printf '%s\n' "$record" >> "$path"
    fi
}
