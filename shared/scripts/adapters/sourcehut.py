"""
SourceHut adapter — mailing-list PRs.

SourceHut is philosophically different from every other host: there is
no `POST /pulls` endpoint. Contributions happen via `git send-email` to
the project's mailing list. The review loop is literal email threads,
tracked at https://lists.sr.ht/~owner/repo.

Weaver's mapping:
  - open_pr → `git format-patch` → compose a RFC822 multipart email →
    send via smtplib to the configured list address. Returns a
    PullRequest with `number=0`, `state="open"`, and the mailing-list
    thread URL if configured (else the raw patch series).
  - get_pr / update_pr / merge_pr / close_pr → raise. Reviewers live in
    mailing-list archives; Weaver can't track those without scraping.
  - list_checks → builds.sr.ht status via sr.ht GraphQL (not implemented
    in this adapter; ci-reader handles it separately).

Configuration (`repo` arg is "owner/repo"):
  - SourceHut username + PAT for the sr.ht API (write access to git.sr.ht):
      $SOURCEHUT_TOKEN  (OAuth personal token)
  - Mailing list address for patch submission. Resolution order:
      1. adapter constructor `list_address=` kwarg
      2. `[weaver]\n\tsrht-list = ...` in .git/config
      3. $WEAVER_SRHT_LIST env var
      4. raise — no list to send to.
  - SMTP config: either SOURCEHUT_SMTP_HOST / PORT / USER / PASS env vars,
    or fall back to `git send-email` if available (it reads ~/.gitconfig).

Implementation note: this is a deliberately minimal outbound-patch path.
Full round-trip (reading review replies) requires a mailing-list scraper
which is out of scope.
"""

from __future__ import annotations

import os
import smtplib
import subprocess
import tempfile
from email.message import EmailMessage
from pathlib import Path
from typing import Any

from . import HostAdapter, NotImplementedHostOp, PullRequest
from registry_loader import get_host


class SourceHutAdapter(HostAdapter):
    host_id = "sourcehut"

    def __init__(
        self,
        list_address: str | None = None,
        sender: str | None = None,
        smtp_host: str | None = None,
        smtp_port: int | None = None,
        smtp_user: str | None = None,
        smtp_password: str | None = None,
    ):
        # SourceHut has no PR REST endpoint; adapter composes patches
        # against a mailing list. We snapshot the registry entry so
        # callers can inspect merge_strategies / support_level / etc.
        # without a second registry lookup.
        self.registry = get_host("sourcehut")
        self._list_explicit = list_address
        self._sender = sender or self._git_config("user.email") or "weaver@localhost"
        self._smtp_host = smtp_host or os.environ.get("SOURCEHUT_SMTP_HOST")
        self._smtp_port = smtp_port or int(os.environ.get("SOURCEHUT_SMTP_PORT") or 0) or None
        self._smtp_user = smtp_user or os.environ.get("SOURCEHUT_SMTP_USER")
        self._smtp_password = smtp_password or os.environ.get("SOURCEHUT_SMTP_PASSWORD")

    def _git_config(self, key: str) -> str:
        try:
            r = subprocess.run(
                ["git", "config", "--get", key],
                capture_output=True, text=True, timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return ""
        return r.stdout.strip() if r.returncode == 0 else ""

    def _resolve_list(self, repo: str) -> str | None:
        if self._list_explicit:
            return self._list_explicit
        cfg = self._git_config("weaver.srht-list")
        if cfg:
            return cfg
        env = os.environ.get("WEAVER_SRHT_LIST")
        if env:
            return env
        return None

    def is_authenticated(self) -> bool:
        """'Authenticated' here means we can send patches: either SMTP creds
        are configured, or `git send-email` is present and configured."""
        if self._smtp_host and self._sender:
            return True
        # Fall back to git send-email availability.
        try:
            r = subprocess.run(
                ["git", "send-email", "--version"],
                capture_output=True, text=True, timeout=5,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            return False
        return r.returncode == 0

    # ── PR ops ─────────────────────────────────────────────────────────

    def open_pr(self, repo, base, head, title, body, draft=True, reviewers=None):
        """Generate a patch series with git format-patch and email it to
        the project's mailing list. Returns a PullRequest with number=0
        and url pointing at the list archive (if resolvable)."""
        list_addr = self._resolve_list(repo)
        if not list_addr:
            raise NotImplementedHostOp(
                self.host_id,
                "open_pr: no mailing list address configured. Set via "
                "constructor list_address=, `git config weaver.srht-list`, "
                "or $WEAVER_SRHT_LIST.",
            )

        # Generate patches in a tmpdir.
        with tempfile.TemporaryDirectory(prefix="weaver-srht-") as td:
            tdp = Path(td)
            try:
                subprocess.run(
                    [
                        "git", "format-patch",
                        "--subject-prefix", f"PATCH {repo}",
                        "-o", str(tdp),
                        f"{base}..{head}",
                    ],
                    check=True, capture_output=True, text=True, timeout=30,
                )
            except subprocess.CalledProcessError as e:
                raise RuntimeError(f"git format-patch failed: {e.stderr}")

            patches = sorted(tdp.glob("*.patch"))
            if not patches:
                raise RuntimeError(
                    f"git format-patch produced no patches for range {base}..{head}"
                )

            # Compose a cover letter + send each patch.
            cover = self._build_cover_letter(title, body, patches, list_addr, repo)
            self._send_emails(list_addr, cover, patches)

        # Build the list-archive URL when the list is on sr.ht.
        archive_url = ""
        if list_addr.endswith("@lists.sr.ht") or list_addr.endswith("@lists.sr.ht>"):
            addr = list_addr.strip("<>")
            local = addr.split("@", 1)[0]
            archive_url = f"https://lists.sr.ht/~{local.replace('/', '/')}"

        return PullRequest(
            host=self.host_id,
            repo=repo,
            number=0,  # mailing-list threads have no number
            url=archive_url,
            state="open",
            title=title,
            body=body,
            base=base,
            head=head,
            reviewers=list(reviewers or []),
        )

    def update_pr(self, repo, number, **kw):
        raise NotImplementedHostOp(
            self.host_id,
            "update_pr: SourceHut PRs are email threads — resend a v2 patch "
            "series via open_pr() instead.",
        )

    def get_pr(self, repo, number):
        raise NotImplementedHostOp(
            self.host_id,
            "get_pr: not implemented (would require mailing-list archive scraping).",
        )

    def merge_pr(self, repo, number, strategy="merge-commit"):
        raise NotImplementedHostOp(
            self.host_id,
            "merge_pr: SourceHut merges happen locally via `git am` + push by "
            "the maintainer. Weaver cannot automate this.",
        )

    def close_pr(self, repo, number):
        raise NotImplementedHostOp(
            self.host_id, "close_pr: mailing-list threads don't have an API close."
        )

    def list_checks(self, repo, ref):
        return []  # builds.sr.ht handled by ci-reader (future)

    def enqueue_merge(self, repo, number):
        return False

    # ── helpers ────────────────────────────────────────────────────────

    def _build_cover_letter(
        self, title: str, body: str, patches: list[Path], list_addr: str, repo: str
    ) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = f"[PATCH {repo} 0/{len(patches)}] {title}"
        msg["From"] = self._sender
        msg["To"] = list_addr
        msg["X-Mailer"] = "weaver/0.1.0"
        msg.set_content(
            f"{body}\n\n"
            f"---\n"
            f"This patch series was generated by Weaver "
            f"(https://github.com/enchanted-plugins/weaver).\n"
            f"Repository: {repo}\n"
        )
        return msg

    def _send_emails(
        self, list_addr: str, cover: EmailMessage, patches: list[Path]
    ) -> None:
        """Send the cover letter + each patch via SMTP or `git send-email`."""
        if self._smtp_host:
            self._send_via_smtp(list_addr, cover, patches)
        else:
            self._send_via_git(list_addr, cover, patches)

    def _send_via_smtp(
        self, list_addr: str, cover: EmailMessage, patches: list[Path]
    ) -> None:
        port = self._smtp_port or 587
        with smtplib.SMTP(self._smtp_host, port, timeout=30) as s:
            s.starttls()
            if self._smtp_user:
                s.login(self._smtp_user, self._smtp_password or "")
            s.send_message(cover)
            for p in patches:
                msg = EmailMessage()
                msg["From"] = self._sender
                msg["To"] = list_addr
                msg["Subject"] = p.stem
                msg["X-Mailer"] = "weaver/0.1.0"
                msg.set_content(p.read_text(encoding="utf-8", errors="replace"))
                s.send_message(msg)

    def _send_via_git(
        self, list_addr: str, cover: EmailMessage, patches: list[Path]
    ) -> None:
        # git send-email does its own composition; pass the patch dir + the
        # list address. Cover letter is auto-generated by git from the
        # patch series if --cover-letter was passed to format-patch; we
        # didn't pass it (to keep the flow simple), so we write our own
        # cover as a .eml and include it.
        patch_dir = patches[0].parent
        try:
            subprocess.run(
                [
                    "git", "send-email",
                    "--to", list_addr,
                    "--from", self._sender,
                    "--no-chain-reply-to",
                    "--confirm=never",
                    str(patch_dir),
                ],
                check=True, capture_output=True, text=True, timeout=120,
            )
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"git send-email failed: {e.stderr}")
