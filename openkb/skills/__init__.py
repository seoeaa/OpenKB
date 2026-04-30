"""Agent skills system for OpenKB chat.

Provides extensible slash commands that can be added to the chat REPL.
Skills are defined as simple functions with a name, description, and handler.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Callable, Coroutine


SkillHandler = Callable[..., Coroutine[Any, Any, None]]


class Skill:
    __slots__ = ("name", "description", "handler", "arg_help", "needs_arg")

    def __init__(
        self,
        name: str,
        description: str,
        handler: SkillHandler,
        arg_help: str = "",
        needs_arg: bool = False,
    ):
        self.name = name
        self.description = description
        self.handler = handler
        self.arg_help = arg_help
        self.needs_arg = needs_arg


_builtin_skills: dict[str, Skill] = {}


def register(name: str, description: str, needs_arg: bool = False, arg_help: str = ""):
    def decorator(fn: SkillHandler):
        skill = Skill(
            name=name,
            description=description,
            handler=fn,
            arg_help=arg_help,
            needs_arg=needs_arg,
        )
        _builtin_skills[name] = skill
        return fn
    return decorator


def get_all() -> dict[str, Skill]:
    return dict(_builtin_skills)


def get(name: str) -> Skill | None:
    return _builtin_skills.get(name)


@register(
    name="summarize",
    description="Summarize a wiki page or document",
    needs_arg=True,
    arg_help="<page-path>",
)
async def skill_summarize(arg: str, kb_dir: Path, **kwargs) -> None:
    from openkb.agent.tools import read_wiki_file
    import asyncio
    from prompt_toolkit.formatted_text import FormattedText
    style = kwargs.get("style")

    path = arg.strip()
    content = read_wiki_file(path, str(kb_dir / "wiki"))
    if content.startswith("File not found"):
        if style:
            kwargs["fmt_fn"](style, ("class:error", f"Not found: {path}\n"))
        else:
            print(f"Not found: {path}")
        return

    from openkb.config import load_config, DEFAULT_CONFIG
    config = load_config(kb_dir / ".openkb" / "config.yaml")
    model = config.get("model", DEFAULT_CONFIG["model"])
    language = config.get("language", "en")

    import litellm
    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": f"Summarize the following wiki page concisely in {language}. Write in Markdown."},
            {"role": "user", "content": content},
        ],
    )
    summary = response.choices[0].message.content or ""
    if style:
        kwargs["fmt_fn"](style, ("class:slash.ok", f"Summary of {path}:\n\n"))
    else:
        print(f"Summary of {path}:\n")
    print(summary)


@register(
    name="compare",
    description="Compare two wiki pages side by side",
    needs_arg=True,
    arg_help="<page1> <page2>",
)
async def skill_compare(arg: str, kb_dir: Path, **kwargs) -> None:
    from openkb.agent.tools import read_wiki_file
    from openkb.config import load_config, DEFAULT_CONFIG
    import litellm

    style = kwargs.get("style")
    parts = arg.strip().split(maxsplit=1)
    if len(parts) < 2:
        if style:
            kwargs["fmt_fn"](style, ("class:error", "Usage: /compare <page1> <page2>\n"))
        else:
            print("Usage: /compare <page1> <page2>")
        return

    path1, path2 = parts[0], parts[1]
    content1 = read_wiki_file(path1, str(kb_dir / "wiki"))
    content2 = read_wiki_file(path2, str(kb_dir / "wiki"))

    if content1.startswith("File not found") or content2.startswith("File not found"):
        if style:
            kwargs["fmt_fn"](style, ("class:error", f"Page not found. Check: {path1}, {path2}\n"))
        else:
            print(f"Page not found. Check: {path1}, {path2}")
        return

    config = load_config(kb_dir / ".openkb" / "config.yaml")
    model = config.get("model", DEFAULT_CONFIG["model"])
    language = config.get("language", "en")

    response = await litellm.acompletion(
        model=model,
        messages=[
            {"role": "system", "content": f"Compare the two wiki pages and highlight key differences, similarities, and relationships. Answer in {language}. Write in Markdown."},
            {"role": "user", "content": f"PAGE 1 ({path1}):\n{content1}\n\n---\n\nPAGE 2 ({path2}):\n{content2}"},
        ],
    )
    comparison = response.choices[0].message.content or ""
    if style:
        kwargs["fmt_fn"](style, ("class:slash.ok", f"Comparing {path1} vs {path2}:\n\n"))
    else:
        print(f"Comparing {path1} vs {path2}:\n")
    print(comparison)


@register(
    name="export",
    description="Export wiki pages to a single Markdown file",
    needs_arg=True,
    arg_help="<output-file> [concepts|summaries|all]",
)
async def skill_export(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    parts = arg.strip().split()
    if len(parts) < 1:
        if style:
            kwargs["fmt_fn"](style, ("class:error", "Usage: /export <output.md> [concepts|summaries|all]\n"))
        else:
            print("Usage: /export <output.md> [concepts|summaries|all]")
        return

    output_file = Path(parts[0]).expanduser()
    section = parts[1] if len(parts) > 1 else "all"

    wiki = kb_dir / "wiki"
    lines = [f"# OpenKB Export — {section}\n"]

    sections_to_export = []
    if section in ("concepts", "all"):
        sections_to_export.append(("Concepts", wiki / "concepts"))
    if section in ("summaries", "all"):
        sections_to_export.append(("Summaries", wiki / "summaries"))
    if section in ("explorations", "all"):
        sections_to_export.append(("Explorations", wiki / "explorations"))

    if not sections_to_export:
        if style:
            kwargs["fmt_fn"](style, ("class:error", f"Unknown section: {section}. Use concepts|summaries|all\n"))
        else:
            print(f"Unknown section: {section}")
        return

    for title, directory in sections_to_export:
        if not directory.exists():
            continue
        md_files = sorted(directory.glob("*.md"))
        if not md_files:
            continue
        lines.append(f"\n---\n\n# {title}\n")
        for md in md_files:
            content = md.read_text(encoding="utf-8")
            lines.append(f"\n## {md.stem}\n\n{content}")

    output_file.write_text("\n".join(lines), encoding="utf-8")
    if style:
        kwargs["fmt_fn"](style, ("class:slash.ok", f"Exported to {output_file}\n"))
    else:
        print(f"Exported to {output_file}")


@register(
    name="search",
    description="Search wiki content for a text pattern",
    needs_arg=True,
    arg_help="<pattern>",
)
async def skill_search(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    pattern = arg.strip()
    if not pattern:
        if style:
            kwargs["fmt_fn"](style, ("class:error", "Usage: /search <pattern>\n"))
        else:
            print("Usage: /search <pattern>")
        return

    wiki = kb_dir / "wiki"
    matches = []
    for md in sorted(wiki.rglob("*.md")):
        if md.name in ("AGENTS.md", "SCHEMA.md", "log.md"):
            continue
        try:
            text = md.read_text(encoding="utf-8")
        except OSError:
            continue
        for i, line in enumerate(text.split("\n"), 1):
            if pattern.lower() in line.lower():
                rel = md.relative_to(wiki)
                matches.append((str(rel), i, line.strip()))

    if not matches:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.help", f"No matches for '{pattern}'.\n"))
        else:
            print(f"No matches for '{pattern}'.")
        return

    if style:
        kwargs["fmt_fn"](style, ("class:slash.ok", f"Found {len(matches)} match(es) for '{pattern}':\n\n"))
    else:
        print(f"Found {len(matches)} match(es) for '{pattern}':\n")

    shown = 0
    for path, lineno, line in matches[:50]:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.help", f"  {path}:{lineno}: {line[:120]}\n"))
        else:
            print(f"  {path}:{lineno}: {line[:120]}")
        shown += 1
    if len(matches) > shown:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.help", f"  ... and {len(matches) - shown} more\n"))
        else:
            print(f"  ... and {len(matches) - shown} more")


@register(
    name="diff",
    description="Show recent changes to the knowledge base",
    needs_arg=False,
)
async def skill_diff(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    import subprocess

    wiki = kb_dir / "wiki"
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10", "--", str(wiki)],
            capture_output=True, text=True, cwd=str(kb_dir),
        )
        if result.returncode == 0 and result.stdout.strip():
            if style:
                kwargs["fmt_fn"](style, ("class:slash.ok", "Recent changes:\n"))
                for line in result.stdout.strip().split("\n"):
                    kwargs["fmt_fn"](style, ("class:slash.help", f"  {line}\n"))
            else:
                print("Recent changes:")
                print(result.stdout.strip())
        else:
            if style:
                kwargs["fmt_fn"](style, ("class:slash.help", "No git history found. Initialize with `git init` in KB directory.\n"))
            else:
                print("No git history found.")
    except FileNotFoundError:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.help", "Git not installed.\n"))
        else:
            print("Git not installed.")


@register(
    name="snapshot",
    description="Create a wiki snapshot point",
    needs_arg=False,
)
async def skill_snapshot(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    from openkb.history import snapshot_wiki
    label = arg.strip() if arg else ""
    snap_id = snapshot_wiki(kb_dir, label=label)
    if snap_id:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.ok", f"Snapshot created: {snap_id}\n"))
        else:
            print(f"Snapshot created: {snap_id}")
    else:
        if style:
            kwargs["fmt_fn"](style, ("class:error", "Wiki is empty, nothing to snapshot.\n"))
        else:
            print("Wiki is empty, nothing to snapshot.")


@register(
    name="history",
    description="Show wiki snapshot history",
    needs_arg=False,
)
async def skill_history(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    from openkb.history import list_snapshots, git_log
    snapshots = list_snapshots(kb_dir, limit=10)
    if snapshots:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.ok", f"Snapshots ({len(snapshots)}):\n"))
        else:
            print(f"Snapshots ({len(snapshots)}):")
        for s in snapshots:
            label = f" — {s.get('label')}" if s.get("label") else ""
            if style:
                kwargs["fmt_fn"](style, ("class:slash.help", f"  {s['id']}  {s['created_at']}{label}\n"))
            else:
                print(f"  {s['id']}  {s['created_at']}{label}")
    else:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.help", "No snapshots yet.\n"))
        else:
            print("No snapshots yet.")

    git = git_log(kb_dir, max_count=5)
    if git:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.ok", "\nGit log:\n"))
        else:
            print("\nGit log:")
        for line in git.split("\n"):
            if style:
                kwargs["fmt_fn"](style, ("class:slash.help", f"  {line}\n"))
            else:
                print(f"  {line}")


@register(
    name="revert",
    description="Revert wiki to a snapshot",
    needs_arg=True,
    arg_help="<snapshot-id> [--dry-run]",
)
async def skill_revert(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    parts = arg.strip().split()
    if not parts:
        if style:
            kwargs["fmt_fn"](style, ("class:error", "Usage: /revert <snapshot-id> [--dry-run]\n"))
        else:
            print("Usage: /revert <snapshot-id> [--dry-run]")
        return

    snap_id = parts[0]
    dry_run = "--dry-run" in parts

    from openkb.history import restore_snapshot
    result = restore_snapshot(kb_dir, snap_id, dry_run=dry_run)

    if "error" in result:
        if style:
            kwargs["fmt_fn"](style, ("class:error", f"Error: {result['error']}\n"))
        else:
            print(f"Error: {result['error']}")
    elif dry_run:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.ok", f"Would restore {len(result['restored'])} file(s):\n"))
            for f in result["restored"]:
                kwargs["fmt_fn"](style, ("class:slash.help", f"  - {f}\n"))
        else:
            print(f"Would restore {len(result['restored'])} file(s):")
            for f in result["restored"]:
                print(f"  - {f}")
    else:
        if style:
            kwargs["fmt_fn"](style, ("class:slash.ok", f"Restored {len(result['restored'])} file(s)\n"))
        else:
            print(f"Restored {len(result['restored'])} file(s)")


@register(
    name="sync",
    description="Commit, push and pull wiki changes",
    needs_arg=False,
)
async def skill_sync(arg: str, kb_dir: Path, **kwargs) -> None:
    style = kwargs.get("style")
    from openkb.sync_git import sync
    ok, msg = sync(kb_dir)
    if style:
        if ok:
            kwargs["fmt_fn"](style, ("class:slash.ok", f"Sync: {msg}\n"))
        else:
            kwargs["fmt_fn"](style, ("class:error", f"Sync failed: {msg}\n"))
    else:
        print(f"Sync: {msg}" if ok else f"Sync failed: {msg}")
