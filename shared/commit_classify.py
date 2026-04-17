"""
W1 Stage 2 — Myers-Diff Conventional Classifier, validator half.

Takes a draft commit message (from Stage 1 Sonnet agent) and validates it
against the Conventional Commits 1.0 spec + Weaver-specific policy.

Stage 1 (drafting) is LLM work; Stage 2 (validating) is pure rules and lives
here in Python stdlib so it runs without an LLM call. This is the cost-control
lever: Haiku agent for LLM re-check only when the rules say the message is
borderline.

Usage from hook: python commit_classify.py validate <message_file>
Returns exit 0 on valid, 1 on invalid (with JSON diagnostics on stdout).
"""

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

# Conventional Commits 1.0 canonical types.
CANONICAL_TYPES = frozenset([
    "feat", "fix", "docs", "style", "refactor", "perf",
    "test", "build", "ci", "chore", "revert",
])

SUBJECT_MAX = 72
BODY_LINE_MAX = 72

# Subject pattern: type(scope)?!?: subject
# scope is optional, ! marks breaking change.
SUBJECT_RE = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z0-9\-_./]+)\))?"
    r"(?P<breaking>!)?"
    r":\s+"
    r"(?P<subject>.+)$"
)


@dataclass
class ValidationResult:
    valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    type: str | None = None
    scope: str | None = None
    breaking: bool = False
    subject: str | None = None
    body_present: bool = False
    footers: list[dict] = field(default_factory=list)  # {key, value}

    def to_dict(self) -> dict:
        return {
            "valid": self.valid,
            "errors": self.errors,
            "warnings": self.warnings,
            "type": self.type,
            "scope": self.scope,
            "breaking": self.breaking,
            "subject": self.subject,
            "body_present": self.body_present,
            "footers": self.footers,
        }


def _parse_footers(body_lines: list[str]) -> list[dict]:
    """Parse trailer lines (Key: value or BREAKING CHANGE: value) from the end."""
    if not body_lines:
        return []

    # Trailers are contiguous lines matching "Token: value" or "Token #issue" at the end,
    # after a blank line.
    footer_re = re.compile(r"^(?P<key>[A-Za-z][A-Za-z0-9\-]*(?:\s[A-Z]+)?|BREAKING CHANGE|BREAKING-CHANGE):\s+(?P<value>.+)$")
    footers: list[dict] = []

    # Scan from the end.
    i = len(body_lines) - 1
    found: list[dict] = []
    while i >= 0:
        line = body_lines[i].rstrip()
        if line == "":
            break
        m = footer_re.match(line)
        if m:
            found.append({"key": m.group("key"), "value": m.group("value")})
            i -= 1
        else:
            break

    footers = list(reversed(found))
    return footers


def validate(message: str) -> ValidationResult:
    """Validate a Conventional Commits message. Returns a structured result."""
    result = ValidationResult(valid=False)

    lines = message.replace("\r\n", "\n").split("\n")
    if not lines or not lines[0].strip():
        result.errors.append("Message is empty")
        return result

    subject_line = lines[0]

    # Subject line length
    if len(subject_line) > SUBJECT_MAX:
        result.errors.append(
            f"Subject line is {len(subject_line)} chars (max {SUBJECT_MAX})"
        )

    # Subject format
    m = SUBJECT_RE.match(subject_line)
    if not m:
        result.errors.append(
            'Subject does not match Conventional Commits: "<type>(<scope>)?!?: <subject>"'
        )
        return result

    result.type = m.group("type")
    result.scope = m.group("scope")
    result.breaking = bool(m.group("breaking"))
    result.subject = m.group("subject").strip()

    if result.type not in CANONICAL_TYPES:
        result.errors.append(
            f'Unknown type "{result.type}". Canonical set: {sorted(CANONICAL_TYPES)}'
        )

    # Subject should not end with a period.
    if result.subject.endswith("."):
        result.warnings.append("Subject ends with a period; Conventional Commits prefers no trailing period")

    # Subject should start lowercase by convention.
    if result.subject and result.subject[0].isupper():
        result.warnings.append("Subject starts with uppercase; lowercase is conventional")

    # Blank line after subject if there's a body.
    if len(lines) >= 2 and lines[1].strip() != "":
        result.errors.append("Missing blank line between subject and body")

    # Body + footers
    if len(lines) > 2:
        body_lines = lines[2:]
        result.body_present = any(ln.strip() for ln in body_lines)

        # Line-length policy on body (warn only, don't fail).
        for idx, ln in enumerate(body_lines, start=3):
            if len(ln) > BODY_LINE_MAX and not ln.startswith(("    ", "\t", "> ", "```")):
                result.warnings.append(f"Line {idx} is {len(ln)} chars (soft max {BODY_LINE_MAX})")

        result.footers = _parse_footers(body_lines)

        # BREAKING CHANGE footer: surfaces breaking even without ! in subject.
        for footer in result.footers:
            if footer["key"] in ("BREAKING CHANGE", "BREAKING-CHANGE"):
                if not result.breaking:
                    result.warnings.append(
                        'BREAKING CHANGE footer present but "!" missing in subject; '
                        'prefer explicit "!" for machine-readability'
                    )
                result.breaking = True

    result.valid = not result.errors
    return result


def __main_cli():
    """CLI for hook use.

    Usage:
      python commit_classify.py validate <path-to-message-file>
      python commit_classify.py validate-stdin
    """
    if len(sys.argv) < 2:
        print(json.dumps({"error": "usage: commit_classify.py (validate <path>|validate-stdin)"}))
        sys.exit(3)

    action = sys.argv[1]

    if action == "validate" and len(sys.argv) >= 3:
        path = Path(sys.argv[2])
        if not path.exists():
            print(json.dumps({"error": f"not found: {path}"}))
            sys.exit(3)
        message = path.read_text(encoding="utf-8")
    elif action == "validate-stdin":
        message = sys.stdin.read()
    else:
        print(json.dumps({"error": "unknown action"}))
        sys.exit(3)

    result = validate(message)
    print(json.dumps(result.to_dict(), indent=2))
    sys.exit(0 if result.valid else 1)


if __name__ == "__main__":
    __main_cli()
