"""
Circa Survivor 2026 — Git-backed state sync (cloud only)
=========================================================
Makes season_state.json durable on an ephemeral cloud host (Render): seed the
local file from the git repo once at startup, then commit + push after each
write so state survives restarts and syncs to the Mac.

STRICTLY OPT-IN: everything here is a no-op unless the env var
GIT_BACKED_STATE is set (only on the cloud). Locally the state file is used
exactly as before — no git operations, no behavior change.

Durability model (IMPORTANT):
  - The pull is SEED-ONCE. On the first read of a fresh process we adopt the
    committed state from origin. After that the in-instance file is the source
    of truth and a read NEVER overwrites it. The old behavior — `git checkout
    origin/main -- state` on every read — destroyed any in-session write that
    hadn't been pushed yet (e.g. when GITHUB_TOKEN is missing and the push
    fails), which showed up to the user as picks "reverting" on tab changes.
  - The push is best-effort and needs a write credential (GITHUB_TOKEN). If it
    fails, picks still persist while the instance is warm, but are NOT durable
    across a restart/redeploy. `sync_status()` reports whether pushes work so
    the app (and a curl of the X-State-Sync header) can surface it.

Cloud env vars expected:
    GIT_BACKED_STATE=1
    GITHUB_TOKEN=<PAT with contents:write on the repo>   # required for durability
    GIT_REMOTE=Jacob-dashboard/circa-survivor             # owner/repo
"""
import os
import subprocess
import time

_REPO_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_STATE_REL = "survivor/season_state.json"

# Seed the file from origin exactly once per process.
_SEEDED = {"done": False}
# True once this instance has written state that isn't confirmed on origin.
# While dirty, a read must never adopt origin over the local file.
_LOCAL_AHEAD = {"dirty": False}
# Last push outcome, for diagnostics / the X-State-Sync header.
_LAST_PUSH = {"ok": None, "detail": "", "t": 0.0}


def enabled():
    return bool(os.environ.get("GIT_BACKED_STATE"))


def token_present():
    return bool(os.environ.get("GITHUB_TOKEN"))


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
    """Seed the local state from origin ONCE, at process start. After that the
    in-instance file is authoritative and a read never overwrites it, so an
    unpushed pick can't be clobbered back to the committed value. External
    changes (a push from the Mac) are adopted on the next restart/redeploy.
    No-op locally; never raises."""
    if not enabled() or _SEEDED["done"]:
        return
    _SEEDED["done"] = True
    # Never overwrite a local write, even on the very first call, if somehow a
    # write already happened (defensive).
    if _LOCAL_AHEAD["dirty"]:
        return
    try:
        _ensure_identity_and_remote()
        _run(["git", "fetch", "origin", "main"])
        _run(["git", "checkout", "origin/main", "--", _STATE_REL])
    except Exception:
        pass  # fall back to whatever is on disk


def push_state(message="cloud: update season state [skip render]"):
    """Commit + push the state file after a cloud write. Records the outcome in
    _LAST_PUSH. Marks the instance dirty up front so a concurrent read can
    never revert this write. No-op locally; never raises."""
    if not enabled():
        return
    _LOCAL_AHEAD["dirty"] = True
    _LAST_PUSH["t"] = time.time()
    if not token_present():
        _LAST_PUSH["ok"] = False
        _LAST_PUSH["detail"] = ("no GITHUB_TOKEN set — cannot push; picks persist "
                                "while the instance is awake but reset on restart")
        return
    try:
        _ensure_identity_and_remote()
        add = _run(["git", "add", _STATE_REL])
        if add.returncode != 0:
            _LAST_PUSH["ok"] = False
            _LAST_PUSH["detail"] = f"git add failed: {add.stderr[:150]}"
            return
        status = _run(["git", "status", "--porcelain", _STATE_REL])
        if not status.stdout.strip():
            _LAST_PUSH["ok"] = True
            _LAST_PUSH["detail"] = "nothing to commit (already in sync)"
            _LOCAL_AHEAD["dirty"] = False
            return
        commit = _run(["git", "commit", "-m", message])
        if commit.returncode != 0:
            _LAST_PUSH["ok"] = False
            _LAST_PUSH["detail"] = f"git commit failed: {commit.stderr[:150]}"
            return
        push = _run(["git", "push", "origin", "HEAD:main"])
        if push.returncode != 0:
            _LAST_PUSH["ok"] = False
            _LAST_PUSH["detail"] = f"git push failed: {push.stderr[:150]}"
            return
        _LAST_PUSH["ok"] = True
        _LAST_PUSH["detail"] = "pushed"
        _LOCAL_AHEAD["dirty"] = False  # origin now matches local
    except Exception as ex:
        _LAST_PUSH["ok"] = False
        _LAST_PUSH["detail"] = f"exception: {ex}"[:180]


def sync_status():
    """Runtime durability snapshot for diagnostics and the UI."""
    return {
        "enabled": enabled(),
        "token": token_present(),
        "seeded": _SEEDED["done"],
        "dirty": _LOCAL_AHEAD["dirty"],
        "last_push_ok": _LAST_PUSH["ok"],
        "last_push_detail": _LAST_PUSH["detail"][:200],
    }
