"""
Circa Survivor 2026 — Git-backed state sync (cloud only)
=========================================================
Makes season_state.json durable and synchronized when the app runs on an
ephemeral cloud host (Render): pull the latest committed state before a read,
commit + push after a write. The git repo is the single source of truth, so
the cloud URL and the local Mac stay in sync automatically.

STRICTLY OPT-IN: everything here is a no-op unless the env var
GIT_BACKED_STATE is set (only on the cloud). Locally the state file is used
exactly as before — no git operations, no behavior change.

Safety: every git call is wrapped so a failure NEVER breaks the app — on any
error we silently fall back to the on-disk file. Pulls are throttled so a
burst of reads doesn't hammer git.

Cloud env vars expected:
    GIT_BACKED_STATE=1
    GITHUB_TOKEN=<PAT with contents:write on the repo>
    GIT_REMOTE=Jacob-dashboard/circa-survivor   (owner/repo)
"""
import os
import subprocess
import time

_REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_REL = "survivor/season_state.json"
_LAST_PULL = {"t": 0.0}
_PULL_THROTTLE_SEC = 20.0


def enabled():
    return bool(os.environ.get("GIT_BACKED_STATE"))


def _run(args, timeout=25):
    return subprocess.run(args, cwd=_REPO_DIR, capture_output=True,
                          text=True, timeout=timeout)


def _ensure_identity_and_remote():
    """Point origin at a token-authenticated URL and set a commit identity.
    Idempotent; safe to call every push."""
    token = os.environ.get("GITHUB_TOKEN", "")
    slug = os.environ.get("GIT_REMOTE", "Jacob-dashboard/circa-survivor")
    if token:
        url = f"https://x-access-token:{token}@github.com/{slug}.git"
        _run(["git", "remote", "set-url", "origin", url])
    _run(["git", "config", "user.email", "circa-cloud@users.noreply.github.com"])
    _run(["git", "config", "user.name", "circa-survivor-cloud"])


def pull_state():
    """Throttled `git pull --rebase` so the cloud sees changes pushed from the
    Mac (or a prior cloud write). No-op locally; never raises."""
    if not enabled():
        return
    now = time.time()
    if now - _LAST_PULL["t"] < _PULL_THROTTLE_SEC:
        return
    _LAST_PULL["t"] = now
    try:
        _ensure_identity_and_remote()
        # Prefer the remote copy on conflict — the repo is the source of truth.
        _run(["git", "fetch", "origin", "main"])
        _run(["git", "checkout", "origin/main", "--", _STATE_REL])
    except Exception:
        pass  # fall back to whatever is on disk


def push_state(message="cloud: update season state [skip render]"):
    """Commit + push the state file after a cloud write. No-op locally; never
    raises. The "[skip render]" tag tells Render NOT to redeploy on these
    state commits, so Auto-Deploy can stay ON for code pushes without every
    pick/elo write bouncing the service."""
    if not enabled():
        return
    try:
        _ensure_identity_and_remote()
        add = _run(["git", "add", _STATE_REL])
        if add.returncode != 0:
            return
        # Nothing staged? git commit would error; check first.
        status = _run(["git", "status", "--porcelain", _STATE_REL])
        if not status.stdout.strip():
            return
        _run(["git", "commit", "-m", message])
        _run(["git", "push", "origin", "HEAD:main"])
    except Exception:
        pass
