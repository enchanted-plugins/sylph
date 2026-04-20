---
name: weaver:setup
description: Detect the git host from the current project's `origin` remote, then install / configure only the credentials + tooling that host needs. One interactive pass per project. Covers all 10 supported hosts.
allowed-tools: Bash(git remote get-url *), Bash(git config *), Bash(git credential *), Bash(git credential-manager *), Bash(gh *), Bash(glab *), Bash(aws *), Bash(kubectl *), Bash(winget *), Bash(brew *), Bash(apt *), Bash(apt-get *), Bash(dnf *), Bash(pacman *), Bash(python3 ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/*), Bash(python ${CLAUDE_PLUGIN_ROOT}/../../shared/scripts/*), Read(.git/config)
---

# /weaver:setup

One-time per-project configuration. Detects which host you're using and
does only the work that host needs.

## Usage

```
/weaver:setup                   # detect + prompt + configure
/weaver:setup --host github     # skip detection, pick manually
/weaver:setup --dry-run         # show the planned setup without executing
/weaver:setup --verify          # re-run the is_authenticated() probe on the current host
```

## Flow

```
1. DETECT
   ├─ Run: git remote get-url origin
   ├─ Pipe through shared/scripts/adapters.detect_host()
   └─ Output: github | gitlab | bitbucket-cloud | bitbucket-dc |
              azure-devops | gitea | forgejo | codeberg |
              codecommit | sourcehut | unknown

2. CONFIRM (unless --host given)
   ├─ Print "Detected: <host> (<owner/repo>)"
   └─ Offer override: show numbered menu of all 10 hosts + skip

3. CONFIGURE per host (next section)

4. VERIFY
   ├─ Import the adapter via shared/scripts/adapters/
   ├─ Call adapter.is_authenticated()
   ├─ If True: print "✓ Weaver can talk to <host> as <user>"
   └─ If False: print the exact reason + the one command that fixes it
```

## Per-host setup

### github

The cleanest path works without `gh` — git-credential-manager already
stores the credential that authenticates `git push`. Weaver's urllib
adapter reads it via `git credential fill`.

```
1. Check for token (in order):
   a. $GH_TOKEN / $GITHUB_TOKEN — skip setup, already authenticated.
   b. `git credential fill` for github.com — skip setup, Weaver uses it.
   c. None of the above → proceed to install gh.

2. Install gh (auto, per-platform):
   - winget:  winget install --id GitHub.cli --silent
   - brew:    brew install gh
   - apt:     sudo apt install gh (with official repo setup if missing)
   - dnf:     sudo dnf install gh
   - pacman:  sudo pacman -S github-cli
   - none:    prompt user to visit https://cli.github.com

3. Run: gh auth login
   - Device flow, stores token via git-credential-manager.
   - After login: Weaver's urllib path picks up the stored credential
     automatically — gh itself becomes optional.
```

### gitlab

```
1. Check for token: $GITLAB_TOKEN / $GL_TOKEN, else git credential fill
   for gitlab.com (or self-managed host).

2. If none:
   - Print the link: https://gitlab.com/-/user_settings/personal_access_tokens
     (or the equivalent for self-managed)
   - Required scopes: api, write_repository
   - Ask for the token; store via `git credential approve` so git-push
     and the urllib adapter share it.
   - For self-managed: ask for the api_base URL and store as
     weaver.gitlab.api-base in git config.

3. Verify via adapter.is_authenticated().
```

### bitbucket-cloud

```
1. Check for token: $BITBUCKET_TOKEN / $BB_TOKEN, else git credential fill.

2. If none:
   - Bitbucket Cloud uses Repository Access Tokens (App Passwords
     deprecated). Point user at:
     https://bitbucket.org/<workspace>/<repo>/admin/access-tokens
   - Scopes: pullrequest:write, repository:write
   - Prompt + store.

3. Verify.
```

### bitbucket-dc

```
1. Prompt for api_base URL (self-hosted — no default).
2. Check env tokens + git credential.
3. If none: point user at the DC Personal Access Tokens page + prompt.
4. Store weaver.bitbucket-dc.api-base in git config.
5. Verify.
```

### azure-devops

```
1. Check $AZURE_DEVOPS_TOKEN / $VSTS_TOKEN.
2. If none:
   - PAT generation: https://dev.azure.com/<org>/_usersSettings/tokens
   - Scopes: Code (read & write), Pull Request (read & write)
   - Prompt + store.
3. Ask for org + project to validate.
4. Verify.
```

### gitea / forgejo / codeberg

```
1. Ask for api_base (e.g., https://codeberg.org/api/v1 — already
   defaulted for Codeberg).
2. Token: Gitea uses simple PATs.
   - https://<host>/user/settings/applications → Generate New Token
3. Store token + api_base.
4. Verify.
```

### codecommit

```
1. Check `aws` CLI + `aws sts get-caller-identity`.
2. If aws missing: auto-install via platform package manager (winget:
   not available; brew: awscli; apt: awscli; dnf: awscli; pacman: aws-cli).
3. If not configured: run `aws configure` (interactive) OR prompt for
   AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY.
4. Verify via `aws codecommit list-repositories`.
```

### sourcehut

```
1. This one is truly different — mailing-list PRs, not an API host.
2. Ask for the project's mailing list address:
   - Check `git config weaver.srht-list`
   - If unset: prompt for the list address (e.g.,
     ~user/project-devel@lists.sr.ht)
   - Store via `git config weaver.srht-list <addr>`.
3. Check `git send-email --version`:
   - If missing: install git-email (brew: bundled; apt: git-email;
     dnf: git-email; pacman: git).
   - If `user.email` is unset, prompt.
4. OR: ask for SMTP credentials if user prefers smtplib path.
5. Verify: offer to send a test patch (dry-run) via open_pr() with a
   dummy diff to confirm the email path.
```

## Auto-install behavior

Weaver tries the platform's package manager in this order:

| Platform | Manager | Command flavor |
|---|---|---|
| Windows (git-bash / PowerShell) | winget | `winget install --id <pkg> --silent --accept-source-agreements --accept-package-agreements` |
| macOS | brew | `brew install <pkg>` |
| Debian/Ubuntu | apt-get | `sudo apt-get install -y <pkg>` |
| Fedora/RHEL | dnf | `sudo dnf install -y <pkg>` |
| Arch | pacman | `sudo pacman -S --noconfirm <pkg>` |

If no manager matches, Weaver prints the install URL + skips the
auto-install step. Verification still runs — adapter reports unavailable
until the user installs manually.

## What Weaver does not do

- **Does not modify your `.gitconfig` globally.** All stored credentials
  go through the existing credential-manager OR per-repo `git config`.
- **Does not phone home.** The verify step is a local adapter call; the
  only network traffic is the real API call that validates the token.
- **Does not refuse to run in degraded mode.** If you skip /weaver:setup,
  commit drafting + W2 clustering + destructive-op gate still work.
  PR-opening degrades to "manual handoff required" cleanly.

## Exit codes

| Code | Meaning |
|------|---------|
| 0 | Setup complete, is_authenticated() == True |
| 1 | User skipped |
| 2 | Host detected but setup failed (e.g., auto-install blocked) |
| 3 | Unknown host (remote doesn't match any of the 10 supported) |
