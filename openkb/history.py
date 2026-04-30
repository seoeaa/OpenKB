"""Page history and versioning for OpenKB wiki.

Snapshot-based versioning using a .openkb/history/ directory.
Each page write creates a time-stamped snapshot, enabling rollback.
Also provides git integration for commit-level history.
"""
from __future__ import annotations

import datetime
import json
import shutil
import subprocess
import time
from pathlib import Path

_HISTORY_DIRNAME = "history"


def history_dir(kb_dir: Path) -> Path:
    return kb_dir / ".openkb" / _HISTORY_DIRNAME


def _ensure_history_dir(kb_dir: Path) -> Path:
    d = history_dir(kb_dir)
    d.mkdir(parents=True, exist_ok=True)
    return d


def snapshot_wiki(kb_dir: Path, label: str = "") -> str:
    """Create a full snapshot of the wiki directory.

    Args:
        kb_dir: Knowledge base root.
        label: Optional human-readable label for the snapshot.

    Returns:
        Snapshot ID (timestamp string).
    """
    wiki = kb_dir / "wiki"
    if not wiki.exists():
        return ""

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    micro = int(time.time() * 1_000_000) % 1_000_000
    snap_id = f"{ts}-{micro:06d}"

    snap_dir = _ensure_history_dir(kb_dir) / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)

    for md in wiki.rglob("*.md"):
        rel = md.relative_to(wiki)
        dest = snap_dir / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(md), str(dest))

    meta = {
        "id": snap_id,
        "created_at": datetime.datetime.now().isoformat(),
        "label": label,
        "files": len(list(snap_dir.rglob("*.md"))),
    }
    (snap_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    meta_path = _ensure_history_dir(kb_dir) / "_index.json"
    index = []
    if meta_path.exists():
        index = json.loads(meta_path.read_text(encoding="utf-8"))
    index.insert(0, meta)
    meta_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    return snap_id


def snapshot_page(kb_dir: Path, page_path: str) -> str:
    """Snapshot a single wiki page before modification.

    Args:
        kb_dir: Knowledge base root.
        page_path: Page path relative to wiki root (e.g. 'concepts/attention.md').

    Returns:
        Snapshot ID or empty string if page doesn't exist.
    """
    wiki = kb_dir / "wiki"
    full_path = (wiki / page_path).resolve()
    if not full_path.is_relative_to(wiki.resolve()) or not full_path.exists():
        return ""

    ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    micro = int(time.time() * 1_000_000) % 1_000_000
    snap_id = f"{ts}-{micro:06d}"

    snap_dir = _ensure_history_dir(kb_dir) / snap_id
    snap_dir.mkdir(parents=True, exist_ok=True)
    dest = snap_dir / page_path
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(str(full_path), str(dest))

    meta = {
        "id": snap_id,
        "created_at": datetime.datetime.now().isoformat(),
        "page": page_path,
        "type": "single_page",
    }
    (snap_dir / "_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

    meta_path = _ensure_history_dir(kb_dir) / "_index.json"
    index = []
    if meta_path.exists():
        index = json.loads(meta_path.read_text(encoding="utf-8"))
    index.insert(0, meta)
    meta_path.write_text(json.dumps(index, indent=2), encoding="utf-8")

    return snap_id


def list_snapshots(kb_dir: Path, limit: int = 20) -> list[dict]:
    """Return recent snapshots, newest first."""
    meta_path = history_dir(kb_dir) / "_index.json"
    if not meta_path.exists():
        return []
    index = json.loads(meta_path.read_text(encoding="utf-8"))
    return index[:limit]


def get_snapshot(kb_dir: Path, snap_id: str) -> dict | None:
    """Return a snapshot's metadata by ID (accepts unique prefix)."""
    index = list_snapshots(kb_dir, limit=1000)
    for snap in index:
        if snap["id"] == snap_id:
            return snap
    matches = [s for s in index if s["id"].startswith(snap_id)]
    if len(matches) == 1:
        return matches[0]
    return None


def get_snapshot_files(kb_dir: Path, snap_id: str) -> list[str]:
    """Return list of file paths in a snapshot, relative to wiki root."""
    snap_dir = history_dir(kb_dir) / snap_id
    if not snap_dir.exists():
        return []
    files = []
    for md in snap_dir.rglob("*.md"):
        if md.name == "_meta.json":
            continue
        files.append(str(md.relative_to(snap_dir)))
    return sorted(files)


def read_snapshot_file(kb_dir: Path, snap_id: str, path: str) -> str:
    """Read a specific file from a snapshot."""
    snap_dir = history_dir(kb_dir) / snap_id
    full_path = (snap_dir / path).resolve()
    if not full_path.is_relative_to(snap_dir.resolve()) or not full_path.exists():
        return f"File not found in snapshot: {path}"
    return full_path.read_text(encoding="utf-8")


def restore_snapshot(kb_dir: Path, snap_id: str, dry_run: bool = False) -> dict:
    """Restore wiki to a previous snapshot.

    Args:
        kb_dir: Knowledge base root.
        snap_id: Snapshot ID (or unique prefix).
        dry_run: If True, only show what would be restored.

    Returns:
        Dict with 'restored' (list of paths) and 'dry_run' flag.
    """
    snap = get_snapshot(kb_dir, snap_id)
    if snap is None:
        return {"error": f"Snapshot not found: {snap_id}"}

    snap_dir = history_dir(kb_dir) / snap["id"]
    files = get_snapshot_files(kb_dir, snap["id"])

    if dry_run:
        return {"restored": files, "dry_run": True}

    wiki = kb_dir / "wiki"
    # Snapshot current state before restore
    snapshot_wiki(kb_dir, label=f"auto-before-restore-{snap['id']}")

    for f in files:
        src = snap_dir / f
        dest = wiki / f
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(str(src), str(dest))

    return {"restored": files, "dry_run": False}


def restore_page(kb_dir: Path, snap_id: str, page_path: str) -> bool:
    """Restore a single page from a snapshot."""
    content = read_snapshot_file(kb_dir, snap_id, page_path)
    if content.startswith("File not found"):
        return False

    wiki = kb_dir / "wiki"
    dest = (wiki / page_path).resolve()
    if not dest.is_relative_to(wiki.resolve()):
        return False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(content, encoding="utf-8")
    return True


def prune_snapshots(kb_dir: Path, keep: int = 50) -> int:
    """Remove old snapshots, keeping the ``keep`` most recent."""
    index = list_snapshots(kb_dir, limit=10000)
    removed = 0
    for snap in index[keep:]:
        snap_dir = history_dir(kb_dir) / snap["id"]
        if snap_dir.exists():
            shutil.rmtree(snap_dir)
            removed += 1

    # Rebuild index
    if removed > 0:
        remaining = [s for s in index[:keep]]
        meta_path = history_dir(kb_dir) / "_index.json"
        meta_path.write_text(json.dumps(remaining, indent=2), encoding="utf-8")
    return removed


def git_log(kb_dir: Path, max_count: int = 10) -> str:
    """Return git log for the wiki directory."""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", f"-{max_count}", "--", str(kb_dir / "wiki")],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=10,
        )
        if result.returncode != 0:
            return ""
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return ""


def git_commit(kb_dir: Path, message: str = "auto: wiki snapshot") -> bool:
    """Stage and commit wiki changes."""
    try:
        subprocess.run(
            ["git", "add", str(kb_dir / "wiki")],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=30,
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, cwd=str(kb_dir), timeout=30,
        )
        if result.returncode == 0:
            _update_git_ignore(kb_dir)
            return True
        return "nothing to commit" in result.stdout or "nothing to commit" in result.stderr
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _update_git_ignore(kb_dir: Path) -> None:
    """Ensure .env and sensitive files are in .gitignore."""
    gitignore = kb_dir / ".gitignore"
    existing = set()
    if gitignore.exists():
        existing = set(gitignore.read_text(encoding="utf-8").split("\n"))

    needed = {".env", ".openkb/history/", ".openkb/chats/", "__pycache__/", ".venv/"}
    new_lines = [l for l in needed if l not in existing]
    if new_lines:
        with gitignore.open("a", encoding="utf-8") as fh:
            for line in new_lines:
                fh.write(f"{line}\n")
