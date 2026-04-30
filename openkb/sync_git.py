"""Git-based sync for OpenKB knowledge bases.

Enables self-hosted sync between devices via git remote.
"""
from __future__ import annotations

import subprocess
from pathlib import Path


def init_git(kb_dir: Path) -> bool:
    """Initialize a git repository in the KB directory if not already one."""
    if (kb_dir / ".git").is_dir():
        return True
    try:
        subprocess.run(
            ["git", "init"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=15,
            check=True,
        )
        _ensure_gitignore(kb_dir)
        return True
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return False


def _ensure_gitignore(kb_dir: Path) -> None:
    gitignore = kb_dir / ".gitignore"
    needed = [
        ".env",
        ".openkb/history/",
        ".openkb/chats/",
        ".openkb/chat_history",
        "__pycache__/",
        ".venv/",
        "*.pyc",
    ]
    existing = set()
    if gitignore.exists():
        existing = set(
            line.strip()
            for line in gitignore.read_text(encoding="utf-8").split("\n")
            if line.strip() and not line.strip().startswith("#")
        )
    missing = [l for l in needed if l not in existing]
    if missing:
        with gitignore.open("a", encoding="utf-8") as fh:
            for line in missing:
                fh.write(f"{line}\n")


def get_remote(kb_dir: Path) -> str | None:
    """Return the configured git remote URL, or None."""
    try:
        result = subprocess.run(
            ["git", "remote", "get-url", "origin"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=10,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return None


def set_remote(kb_dir: Path, url: str) -> bool:
    """Configure the origin remote. Creates one if none exists."""
    try:
        existing = get_remote(kb_dir)
        if existing:
            subprocess.run(
                ["git", "remote", "set-url", "origin", url],
                capture_output=True, text=True, cwd=str(kb_dir), timeout=10,
            )
        else:
            subprocess.run(
                ["git", "remote", "add", "origin", url],
                capture_output=True, text=True, cwd=str(kb_dir), timeout=10,
            )
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def commit(kb_dir: Path, message: str = "auto: wiki update") -> bool:
    """Stage wiki changes and commit."""
    try:
        subprocess.run(
            ["git", "add", "wiki/"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=30,
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=30,
        )
        return result.returncode == 0 or "nothing to commit" in result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def push(kb_dir: Path) -> tuple[bool, str]:
    """Push commits to the remote."""
    if not get_remote(kb_dir):
        return False, "No remote configured. Run `openkb sync set-remote <url>`."
    try:
        result = subprocess.run(
            ["git", "push", "origin", "HEAD"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=60,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def pull(kb_dir: Path) -> tuple[bool, str]:
    """Pull changes from the remote. Performs a merge."""
    if not get_remote(kb_dir):
        return False, "No remote configured. Run `openkb sync set-remote <url>`."
    try:
        subprocess.run(
            ["git", "fetch", "origin"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=60,
        )
        result = subprocess.run(
            ["git", "merge", "origin/HEAD"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=30,
        )
        if result.returncode == 0:
            return True, result.stdout.strip()
        return False, result.stderr.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def sync(kb_dir: Path, message: str = "auto: wiki sync") -> tuple[bool, str]:
    """Commit local changes, then push and pull (bidirectional sync).

    Returns:
        (success, message)
    """
    if not init_git(kb_dir):
        return False, "Git not available."

    has_remote = get_remote(kb_dir) is not None
    if not has_remote:
        commit(kb_dir, message)
        return True, "Committed locally (no remote configured)."

    commit(kb_dir, message)
    ok_pull, msg_pull = pull(kb_dir)
    ok_push, msg_push = push(kb_dir)

    parts = []
    if ok_pull:
        parts.append("pulled")
    else:
        parts.append(f"pull: {msg_pull[:100]}")
    if ok_push:
        parts.append("pushed")
    else:
        parts.append(f"push: {msg_push[:100]}")

    return True, "; ".join(parts)


def status(kb_dir: Path) -> str:
    """Return git status for the wiki."""
    try:
        result = subprocess.run(
            ["git", "status", "--short", "wiki/"],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=15,
        )
        if result.returncode == 0:
            return result.stdout.strip() or "No changes."
        return f"Git error: {result.stderr.strip()}"
    except FileNotFoundError:
        return "Git not installed."
    except subprocess.TimeoutExpired:
        return "Git timeout."
