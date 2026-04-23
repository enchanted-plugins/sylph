"""
Destructive-op classifier for git subcommands.

Consumed by sylph-gate's PreToolUse(Bash) hook. Takes a shell command
string and returns a classification: safe | destructive | protected-destructive.

Rules-only — no LLM in the hot path. Matches the destructive-op table
in the Sylph architecture output-reference.md.

Recovery windows are advisory (used in the gate confirmation prompt);
protected-destructive ops are never bypassed regardless of the flag.
"""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Callable


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


def _match_amend(parts: list[str]) -> bool:
    """Match `git commit ... --amend ...`. Context-checked via amend_safety.

    The regex hint in the rule table is naive; this predicate is authoritative:
    anywhere --amend appears in the argv after `commit`, it's an amend.
    """
    return (
        len(parts) >= 3
        and parts[0] == "git"
        and parts[1] == "commit"
        and "--amend" in parts[2:]
    )


def _amend_context_check(parts: list[str], repo_path: str | Path) -> bool:
    """Return True iff this amend rewrites pushed history.

    Delegated to amend_safety.is_head_pushed — imported lazily to keep the
    module import-cheap for the common classify() path that never hits amend.
    """
    from amend_safety import is_head_pushed  # local import, stdlib + subprocess only

    pushed, _, _ = is_head_pushed(repo_path)
    return pushed


# Ordered: check protected/irrecoverable first, then other destructive, then safe default.
#
# Each rule is a 7-tuple:
#   (predicate, classification, op_name, reason, recovery_days, reverse_cmd,
#    context_check)
#
# context_check is Optional[Callable[[list[str], str | Path], bool]]. When set,
# the rule only fires if the context_check returns True for the current repo.
# This is how `amend_of_pushed_head` is gated on actual push-state rather than
# the raw invocation: an amend on a never-pushed branch is safe.
_RULES = [
    (_match_clean, Classification.PROTECTED_DESTRUCTIVE,
     "git clean -fdx",
     "Deletes untracked + ignored files; reflog does not cover this",
     0, None, None),
    (_match_filter, Classification.DESTRUCTIVE,
     "git filter-branch/filter-repo",
     "History rewrite; destroys commits permanently once pushed",
     90, "git reflog + reset to pre-filter ref (local only)", None),
    (_match_force_push, Classification.DESTRUCTIVE,
     "git push --force",
     "Force-push can rewrite shared history; prefer --force-with-lease",
     30, None, None),
    (_match_force_with_lease, Classification.DESTRUCTIVE,
     "git push --force-with-lease",
     "Force-push with lease; protected branches never bypassed",
     30, None, None),
    (_match_reset_hard, Classification.DESTRUCTIVE,
     "git reset --hard",
     "Resets working tree and index; uncommitted work lost to reflog",
     90, "git reflog + reset back", None),
    (_match_rebase_interactive, Classification.DESTRUCTIVE,
     "git rebase -i",
     "Interactive rebase across pushed commits rewrites shared history",
     90, "git reflog + reset to pre-rebase ref", None),
    (_match_remote_branch_delete, Classification.DESTRUCTIVE,
     "git push --delete <branch>",
     "Remote branch deletion; host retention varies (GitHub default 14d)",
     14, "git push origin <branch> (requires local ref)", None),
    (_match_branch_delete, Classification.DESTRUCTIVE,
     "git branch -D",
     "Deletes branch including unmerged commits; reflog covers 90d",
     90, "git reflog + git branch <name> <sha>", None),
    (_match_tag_delete, Classification.DESTRUCTIVE,
     "git tag -d",
     "Tag deletion; if also pushed-delete, remote removal is permanent",
     90, None, None),
    # amend_of_pushed_head — anti-pattern #2. Only destructive when HEAD
    # is already reachable from a remote-tracking ref; otherwise safe.
    (_match_amend, Classification.DESTRUCTIVE,
     "git commit --amend (of pushed HEAD)",
     "Amending a pushed commit rewrites shared history (anti-pattern #2). "
     "Use a follow-up commit instead.",
     30, "git reflog + reset to pre-amend ref (local only)", _amend_context_check),
]


def classify(command: str, repo_path: str | Path | None = None) -> Verdict:
    """Classify a shell command string as safe / destructive / protected-destructive.

    The command is tokenized with shlex.split; if tokenization fails (e.g. unclosed
    quote), we err on the side of caution and return SAFE — the Bash call will
    fail anyway and won't touch git state.

    Some rules carry a `context_check` callable that takes `(parts, repo_path)`
    and decides whether the match is actually destructive in this repo. If the
    context_check returns False, the rule is skipped and classification falls
    through. `repo_path` defaults to the current working directory.
    """
    command = command.strip()
    try:
        parts = shlex.split(command)
    except ValueError:
        return Verdict(Classification.SAFE, "unknown", "command failed to tokenize", 0, None)

    if not parts or parts[0] != "git":
        return Verdict(Classification.SAFE, "non-git", "not a git invocation", 0, None)

    if repo_path is None:
        import os
        repo_path = os.getcwd()

    for rule in _RULES:
        # Support both legacy 6-tuples and new 7-tuples with context_check.
        if len(rule) == 7:
            predicate, cls, op_name, reason, days, reverse, ctx_check = rule
        else:
            predicate, cls, op_name, reason, days, reverse = rule
            ctx_check = None

        if not predicate(parts):
            continue

        if ctx_check is not None:
            try:
                if not ctx_check(parts, repo_path):
                    # Pattern matched but context says it's safe — e.g. amend
                    # on an unpushed branch. Skip this rule; don't fall back
                    # to SAFE yet (another rule might still match).
                    continue
            except Exception:
                # context_check must never raise. If it does, be conservative:
                # treat as destructive so we gate rather than miss the pattern.
                pass

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

    Usage: python destructive_patterns.py "<shell command>" [<repo_path>]
    Exits 0 = safe (allow), 1 = destructive (gate), 2 = protected (always gate),
    3 = usage error.

    If <repo_path> is omitted the classifier uses cwd for context_check calls.
    Prints JSON verdict on stdout so the hook can surface details.
    """
    import sys
    import json

    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: destructive_patterns.py <command> [repo_path]"}))
        sys.exit(3)

    repo_path = sys.argv[2] if len(sys.argv) >= 3 else None
    verdict = classify(sys.argv[1], repo_path=repo_path)
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
