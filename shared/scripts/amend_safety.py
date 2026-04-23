"""
Safe-amend detection for sylph-gate.

Closes CLAUDE.md anti-pattern #2: auto-amending pushed commits.

`git commit --amend` rewrites HEAD. If HEAD has already been pushed to any
remote-tracking ref, the amend rewrites *shared* history — every downstream
consumer must force-pull or re-fork. That's the anti-pattern. The fix is a
follow-up commit, not `--amend`.

Detection is one git command:

    git rev-list --count HEAD --not --remotes

If the count is 0, HEAD is reachable from some remote-tracking ref and is
considered pushed. Any --amend in this state is destructive.

Pure stdlib + subprocess(git). No network, no third-party deps.
"""

from __future__ import annotations

import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class AmendVerdict:
    """Outcome of classifying a `git commit --amend` invocation.

    is_destructive is True iff the command is an amend AND HEAD is pushed.
    head_sha + remote_refs are populated when we successfully probed git;
    remote_refs may be empty (truly unpushed) or contain the refs whose tip
    matches HEAD.
    """

    is_amend: bool
    is_destructive: bool
    head_sha: str | None
    remote_refs_containing_head: list[str]
    reason: str


def _run_git(args: list[str], repo_path: str | Path) -> subprocess.CompletedProcess:
    """Invoke git; never raise, caller inspects returncode."""
    return subprocess.run(
        ["git", *args],
        cwd=str(repo_path),
        capture_output=True,
        text=True,
        check=False,
    )


def is_amend_invocation(argv: list[str]) -> bool:
    """True iff argv is `git commit ... --amend ...` (flag anywhere after `commit`).

    Accepts:
      git commit --amend
      git commit --amend --no-edit
      git commit -a --amend
      git commit --amend -m "new msg"

    Rejects non-commit subcommands and plain `git commit` without --amend.
    """
    if len(argv) < 3:
        return False
    if argv[0] != "git" or argv[1] != "commit":
        return False
    # --amend may appear anywhere after `commit`. Match the flag exactly —
    # we don't want a substring hit on e.g. --amendable (no such flag, but
    # defensive against future flags).
    return "--amend" in argv[2:]


def is_head_pushed(repo_path: str | Path) -> tuple[bool, str | None, list[str]]:
    """Probe whether HEAD has been pushed to any remote-tracking ref.

    Returns (pushed, head_sha, remote_refs_containing_head).

    Semantics:
      - No remotes at all       → (False, <sha>, [])   — local-only repo, safe
      - HEAD has commits not on any remote → (False, <sha>, [])  — unpushed, safe
      - HEAD reachable from a remote ref   → (True,  <sha>, [<ref>, ...])

    If git invocation fails (not a repo, missing git, etc.) we fail closed on
    the "pushed" bit — better to ask once than to let a rewrite slip through —
    except when we can positively determine there are no remotes at all.
    """
    # Resolve HEAD sha; also confirms we're in a repo.
    head = _run_git(["rev-parse", "HEAD"], repo_path)
    if head.returncode != 0:
        # Not a repo, or no commits yet. Amend is impossible → treat as safe.
        return (False, None, [])
    head_sha = head.stdout.strip()

    # Count commits reachable from HEAD that are not on any remote-tracking ref.
    # Output is a single integer on stdout.
    count = _run_git(
        ["rev-list", "--count", "HEAD", "--not", "--remotes"],
        repo_path,
    )
    if count.returncode != 0:
        # --remotes with no remotes returns 0 (it just means "no excludes") —
        # the count equals all commits reachable from HEAD, which is > 0 for
        # any non-empty repo → correctly classified as not-pushed.
        # A nonzero exit is an unexpected git failure; fail safe.
        return (False, head_sha, [])

    try:
        n_unpushed = int(count.stdout.strip())
    except ValueError:
        return (False, head_sha, [])

    if n_unpushed > 0:
        # HEAD has at least one commit that isn't on any remote-tracking ref.
        # The amend targets the tip, but if the tip itself is one of those
        # unpushed commits the rewrite is local. Confirm by checking whether
        # HEAD itself is reachable from any remote ref.
        pass

    # Which remote refs (if any) contain HEAD? This is the authoritative answer:
    # if any remote ref contains HEAD, amending HEAD rewrites shared history.
    refs = _run_git(
        ["for-each-ref", "--contains", head_sha, "--format=%(refname)", "refs/remotes/"],
        repo_path,
    )
    if refs.returncode != 0:
        # for-each-ref shouldn't fail on a valid repo; treat as "no containing refs"
        # rather than misclassifying.
        return (False, head_sha, [])

    containing = [line.strip() for line in refs.stdout.splitlines() if line.strip()]
    return (len(containing) > 0, head_sha, containing)


def classify_amend(cmd_argv: list[str], repo_path: str | Path) -> AmendVerdict:
    """Classify a parsed argv for the amend-of-pushed-HEAD anti-pattern.

    If the command isn't `git commit --amend`, returns is_amend=False and
    is_destructive=False — the main classifier (destructive_patterns) owns
    everything else.

    If it IS an amend, probes the repo and fills in the verdict.
    """
    if not is_amend_invocation(cmd_argv):
        return AmendVerdict(
            is_amend=False,
            is_destructive=False,
            head_sha=None,
            remote_refs_containing_head=[],
            reason="not a git commit --amend invocation",
        )

    pushed, head_sha, refs = is_head_pushed(repo_path)

    if not pushed:
        return AmendVerdict(
            is_amend=True,
            is_destructive=False,
            head_sha=head_sha,
            remote_refs_containing_head=refs,
            reason=(
                "HEAD is not reachable from any remote-tracking ref; "
                "amend rewrites local history only (safe)"
            ),
        )

    return AmendVerdict(
        is_amend=True,
        is_destructive=True,
        head_sha=head_sha,
        remote_refs_containing_head=refs,
        reason=(
            "HEAD is reachable from remote-tracking refs "
            f"({', '.join(refs)}); amend rewrites shared history "
            "(anti-pattern #2 in CLAUDE.md). Use a follow-up commit instead."
        ),
    )


def classify_command_string(command: str, repo_path: str | Path) -> AmendVerdict:
    """Convenience: tokenize a shell command string and classify.

    On tokenization failure returns a not-amend verdict (the outer hook will
    fail-open the same way destructive_patterns.classify does).
    """
    try:
        argv = shlex.split(command)
    except ValueError:
        return AmendVerdict(
            is_amend=False,
            is_destructive=False,
            head_sha=None,
            remote_refs_containing_head=[],
            reason="command failed to tokenize",
        )
    return classify_amend(argv, repo_path)


def __main_cli():
    """CLI entry for bash hook.

    Usage: python amend_safety.py <repo_path> "<shell command>"
    Exits:
       0 = not destructive (amend on unpushed HEAD, or not an amend at all)
       1 = destructive (amend on pushed HEAD — anti-pattern #2)
       3 = usage error

    Emits JSON verdict on stdout.
    """
    import json
    import sys

    if len(sys.argv) < 3:
        print(json.dumps({"error": "usage: amend_safety.py <repo_path> <command>"}))
        sys.exit(3)

    repo_path = sys.argv[1]
    command = sys.argv[2]

    verdict = classify_command_string(command, repo_path)
    print(json.dumps({
        "is_amend": verdict.is_amend,
        "is_destructive": verdict.is_destructive,
        "head_sha": verdict.head_sha,
        "remote_refs_containing_head": verdict.remote_refs_containing_head,
        "reason": verdict.reason,
    }))

    sys.exit(1 if verdict.is_destructive else 0)


if __name__ == "__main__":
    __main_cli()
