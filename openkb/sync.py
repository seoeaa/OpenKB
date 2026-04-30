"""Markdown mirror sync for OpenKB.

Watches an external directory and syncs .md files into the wiki.
"""
from __future__ import annotations

import shutil
from pathlib import Path


class MirrorSync:
    """Bidirectional mirror between an external directory and the wiki.

    Copies .md files from source to target, preserving directory structure.
    Does not delete files in target that don't exist in source (safe sync).
    """

    def __init__(self, source: Path, target: Path):
        self.source = source
        self.target = target

    def full_sync(self) -> list[str]:
        """Copy all .md files from source to target that are newer or missing."""
        synced = []
        for md in sorted(self.source.rglob("*.md")):
            rel = md.relative_to(self.source)
            dest = self.target / rel
            if dest.exists() and dest.stat().st_mtime >= md.stat().st_mtime:
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(md), str(dest))
            synced.append(str(rel))
        return synced

    def sync_paths(self, paths: list[Path]) -> list[str]:
        """Sync specific files that changed."""
        synced = []
        for md in paths:
            if md.suffix.lower() != ".md":
                continue
            try:
                rel = md.relative_to(self.source)
            except ValueError:
                continue
            dest = self.target / rel
            if not md.exists():
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(md), str(dest))
            synced.append(str(rel))
        return synced
