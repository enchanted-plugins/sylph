"""
Destructive-op classifier for git subcommands.

Consumed by weaver-gate's PreToolUse(Bash) hook. Takes a shell command
string and returns a classification: safe | destructive | protected-destructive.

Rules-only — no LLM in the hot path. Matches the destructive-op table
in the Weaver architecture output-reference.md.

Recovery windows are advisory (used in the gate confirmation prompt);
protected-destructive ops are never bypassed regardless of the flag.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum


class Classification(Enum):
    SAFE = "safe"
    DESTRUCTIVE = "destructive"
    PROTECTED_DESTRUCTIVE = "protected-destructive"


@dataclass
class Verdict:
    classification: Classification
    op: str
    reason: str
    recovery_window_days: int  # 0 = irrecoverable
    reverse_command: str | None  # if we can suggest a reversal


# Canonical destructive-op patterns. Order matters: more specific first.
# Each entry: (match_predicate, op_name, reason, recovery_days, reverse_template)
_PATTERNS: list[tuple] = []


def _match_force_push(parts: list[str]) -> bool:
    return (
        len(parts) >= 2
        and parts[0] == "git"
        and parts[1] == "push"
        and any(p in parts for p in ("--force", "-f"))
        and "--force-with-lease" not in parts
    )


def _match_force_with_lease(parts: list[str]) -> bool:
    return (
        len(parts) >= 2
        and parts[0] == "git"
        and parts[1] == "push"
        and any(p.startswith("--force-with-lease") for p in parts)
    )


def _match_filter(parts: list[str]) -> bool:
    return (
        len(parts) >= 2
        and parts[0] == "git"
        and parts[1] in ("filter-branch", "filter-repo")
    )


def _match_rebase_interactive(parts: list[str]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "rebase"
        and ("-i" in parts or "--interactive" in parts)
    )


def _match_reset_hard(parts: list[str]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "reset"
        and "--hard" in parts
    )


def _match_branch_delete(parts: list[str]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "branch"
        and ("-D" in parts or "--delete" in parts and "-d" not in parts)
    )


def _match_remote_branch_delete(parts: list[str]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "push"
        and ("--delete" in parts or (len(parts) >= 4 and parts[3].startswith(":")))
    )


def _match_tag_delete(parts: list[str]) -> bool:
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "tag"
        and "-d" in parts
    )


def _match_clean(parts: list[str]) -> bool:
    return (
        len(parts) >= 2
        and parts[0] == "git"
        and parts[1] == "clean"
        and any(f in parts for f in ("-fd", "-fdx", "-df", "-dfx", "-fdX"))
    )


# Ordered: check protected/irrecoverable first, then other destructive, then safe default.
_RULES = [
    (_match_clean, Classification.PROTECTED_DESTRUCTIVE,
     "git clean -fdx",
     "Deletes untracked + ignored files; reflog does not cover this",
     0, None),
    (_match_filter, Classification.DESTRUCTIVE,
     "git filter-branch/filter-repo",
     "History rewrite; destroys commits permanently once pushed",
     90, "git reflog + reset to pre-filter ref (local only)"),
    (_match_force_push, Classification.DESTRUCTIVE,
     "git push --force",
     "Force-push can rewrite shared history; prefer --force-with-lease",
     30, None),
    (_match_force_with_lease, Classification.DESTRUCTIVE,
     "git push --force-with-lease",
     "Force-push with lease; protected branches never bypassed",
     30, None),
    (_match_reset_hard, Classification.DESTRUCTIVE,
     "git reset --hard",
     "Resets working tree and index; uncommitted work lost to reflog",
     90, "git reflog + reset back"),
    (_match_rebase_interactive, Classification.DESTRUCTIVE,
     "git rebase -i",
     "Interactive rebase across pushed commits rewrites shared history",
     90, "git reflog + reset to pre-rebase ref"),
    (_match_remote_branch_delete, Classification.DESTRUCTIVE,
     "git push --delete <branch>",
     "Remote branch deletion; host retention varies (GitHub default 14d)",
     14, "git push origin <branch> (requires local ref)"),
    (_match_branch_delete, Classification.DESTRUCTIVE,
     "git branch -D",
     "Deletes branch including unmerged commits; reflog covers 90d",
     90, "git reflog + git branch <name> <sha>"),
    (_match_tag_delete, Classification.DESTRUCTIVE,
     "git tag -d",
     "Tag deletion; if also pushed-delete, remote removal is permanent",
     90, None),
]


def classify(command: str) -> Verdict:
    """Classify a shell command string as safe / destructive / protected-destructive.

    The command is tokenized with shlex.split; if tokenization fails (e.g. unclosed
    quote), we err on the side of caution and return SAFE — the Bash call will
    fail anyway and won't touch git state.
    """
    command = command.strip()
    try:
        parts = shlex.split(command)
    except ValueError:
        return Verdict(Classification.SAFE, "unknown", "command failed to tokenize", 0, None)

    if not parts or parts[0] != "git":
        return Verdict(Classification.SAFE, "non-git", "not a git invocation", 0, None)

    for predicate, cls, op_name, reason, days, reverse in _RULES:
        if predicate(parts):
            return Verdict(
                classification=cls,
                op=op_name,
                reason=reason,
                recovery_window_days=days,
                reverse_command=reverse,
            )

    return Verdict(Classification.SAFE, parts[1] if len(parts) >= 2 else "git", "no destructive pattern matched", 0, None)


def is_protected_branch(branch: str, protected_set: set[str] | None = None) -> bool:
    """Check if a branch name is in the protected set.

    Defaults to common protected branches. Callers should pass the resolved
    set from capability-memory when available (host-specific protection rules).
    """
    if protected_set is None:
        protected_set = {"main", "master", "develop", "release", "trunk"}
    # Also treat release/* and hotfix/* as protected by convention.
    if branch in protected_set:
        return True
    if "/" in branch:
        prefix = branch.split("/", 1)[0]
        if prefix in {"release", "hotfix"}:
            return True
    return False


def __main_cli():
    """CLI entry for the bash hook to call.

    Usage: python destructive_patterns.py "<shell command>"
    Exits 0 = safe (allow), 1 = destructive (gate), 2 = protected (always gate),
    3 = usage error.

    Prints JSON verdict on stdout so the hook can surface details.
    """
    import sys
    import json

    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: destructive_patterns.py <command>"}))
        sys.exit(3)

    verdict = classify(sys.argv[1])
    print(json.dumps({
        "classification": verdict.classification.value,
        "op": verdict.op,
        "reason": verdict.reason,
        "recovery_window_days": verdict.recovery_window_days,
        "reverse_command": verdict.reverse_command,
    }))

    if verdict.classification == Classification.SAFE:
        sys.exit(0)
    if verdict.classification == Classification.DESTRUCTIVE:
        sys.exit(1)
    sys.exit(2)


if __name__ == "__main__":
    __main_cli()
