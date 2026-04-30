"""OpenKB MCP server — expose knowledge base as MCP tools for AI agents.

Usage:
    openkb mcp                  # stdio transport (for Claude Desktop, Kilo, etc.)
    OPENKB_MCP_SSE=1 openkb mcp  # SSE transport on http://localhost:8001
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from openkb.agent.tools import (
    get_wiki_page_content,
    list_wiki_files,
    read_wiki_file,
    write_wiki_file,
)
from openkb.config import DEFAULT_CONFIG, load_config
from openkb.lint import run_structural_lint


def _setup_mcp_key(kb_dir: Path | None) -> None:
    """Set up LLM key for MCP tools that need the LLM."""
    if kb_dir is None:
        return

    import os
    from dotenv import load_dotenv
    from openkb.config import GLOBAL_CONFIG_DIR
    import litellm

    env_file = kb_dir / ".env"
    if env_file.exists():
        load_dotenv(env_file, override=False)

    global_env = GLOBAL_CONFIG_DIR / ".env"
    if global_env.exists():
        load_dotenv(global_env, override=False)

    api_key = os.environ.get("LLM_API_KEY", "")
    if api_key:
        litellm.api_key = api_key
        for env_var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "OPENROUTER_API_KEY"):
            if not os.environ.get(env_var):
                os.environ[env_var] = api_key


def _find_kb_dir() -> Path | None:
    current = Path.cwd().resolve()
    while True:
        if (current / ".openkb").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    from openkb.config import load_global_config
    gc = load_global_config()
    default = gc.get("default_kb")
    if default:
        p = Path(default)
        if (p / ".openkb").is_dir():
            return p
    return None


def _get_wiki_root() -> str:
    env = os.environ.get("OPENKB_DIR")
    if env:
        return str(Path(env).resolve() / "wiki")
    kb = _find_kb_dir()
    if kb is None:
        raise RuntimeError(
            "No knowledge base found. Run `openkb init` or set OPENKB_DIR."
        )
    return str(kb / "wiki")


def _get_kb_dir() -> Path:
    env = os.environ.get("OPENKB_DIR")
    if env:
        return Path(env).resolve()
    kb = _find_kb_dir()
    if kb is None:
        raise RuntimeError(
            "No knowledge base found. Run `openkb init` or set OPENKB_DIR."
        )
    return kb


mcp = FastMCP(
    "openkb",
    instructions=(
        "OpenKB — knowledge base tools. "
        "Query documents, concepts, and summaries stored as Markdown files with [[wikilinks]]."
    ),
)


@mcp.tool()
def kb_list(directory: str = "") -> str:
    """List Markdown files in a wiki subdirectory.

    Args:
        directory: Subdirectory name (e.g. 'summaries', 'concepts', 'explorations'). Empty string lists wiki root.
    """
    wiki_root = _get_wiki_root()
    return list_wiki_files(directory or ".", wiki_root)


@mcp.tool()
def kb_read(path: str) -> str:
    """Read a Markdown file from the wiki.

    Args:
        path: File path relative to wiki root (e.g. 'summaries/paper.md').
    """
    wiki_root = _get_wiki_root()
    return read_wiki_file(path, wiki_root)


@mcp.tool()
def kb_read_index() -> str:
    """Read the knowledge base index page (index.md) with all documents and concepts."""
    wiki_root = _get_wiki_root()
    return read_wiki_file("index.md", wiki_root)


@mcp.tool()
def kb_read_concept(name: str) -> str:
    """Read a concept page by name.

    Args:
        name: Concept slug (e.g. 'attention-mechanism').
    """
    wiki_root = _get_wiki_root()
    return read_wiki_file(f"concepts/{name}.md", wiki_root)


@mcp.tool()
def kb_read_summary(name: str) -> str:
    """Read a document summary page by name.

    Args:
        name: Document slug (e.g. 'attention-is-all-you-need').
    """
    wiki_root = _get_wiki_root()
    return read_wiki_file(f"summaries/{name}.md", wiki_root)


@mcp.tool()
def kb_get_pages(doc_name: str, pages: str) -> str:
    """Get text content of specific pages from a PageIndex (long) document.

    Args:
        doc_name: Document name without extension (e.g. 'attention-is-all-you-need').
        pages: Page specification (e.g. '3-5,7,10-12').
    """
    wiki_root = _get_wiki_root()
    return get_wiki_page_content(doc_name, pages, wiki_root)


@mcp.tool()
def kb_write(path: str, content: str) -> str:
    """Write or overwrite a Markdown file in the wiki.

    Args:
        path: File path relative to wiki root (e.g. 'concepts/new-topic.md').
        content: Full Markdown content to write.
    """
    wiki_root = _get_wiki_root()
    return write_wiki_file(path, content, wiki_root)


@mcp.tool()
def kb_status() -> str:
    """Show knowledge base statistics: document count, concepts, summaries, last compile/lint times."""
    kb_dir = _get_kb_dir()
    wiki = kb_dir / "wiki"
    subdirs = ["sources", "summaries", "concepts", "reports", "explorations"]
    lines = ["Knowledge Base Status:"]
    lines.append(f"  Path: {kb_dir}")
    lines.append(f"  {'Directory':<20} {'Files':<10}")
    lines.append(f"  {'-'*20} {'-'*10}")
    for subdir in subdirs:
        path = wiki / subdir
        count = len(list(path.glob("*.md"))) if path.exists() else 0
        lines.append(f"  {subdir:<20} {count:<10}")

    raw_dir = kb_dir / "raw"
    if raw_dir.exists():
        raw_count = len([f for f in raw_dir.iterdir() if f.is_file()])
        lines.append(f"  {'raw':<20} {raw_count:<10}")

    openkb_dir = kb_dir / ".openkb"
    hashes_file = openkb_dir / "hashes.json"
    if hashes_file.exists():
        hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
        lines.append(f"\n  Total indexed: {len(hashes)} document(s)")

    return "\n".join(lines)


@mcp.tool()
def kb_lint() -> str:
    """Run structural lint checks: broken links, orphaned pages, missing entries, index sync."""
    kb_dir = _get_kb_dir()
    return run_structural_lint(kb_dir)


@mcp.tool()
def kb_search(pattern: str) -> str:
    """Search wiki content for a text pattern.

    Args:
        pattern: Text pattern to search for (case-insensitive).
    """
    import re
    kb_dir = _get_kb_dir()
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
                rel = str(md.relative_to(wiki))
                snippet = line.strip()[:150]
                matches.append(f"  {rel}:{i}: {snippet}")
        if len(matches) >= 30:
            break
    if not matches:
        return f"No matches for '{pattern}'."
    return f"Found {len(matches)} matches for '{pattern}':\n" + "\n".join(matches)


@mcp.tool()
def kb_query(question: str, save: bool = False) -> str:
    """Ask a question against the knowledge base using the LLM agent.

    Args:
        question: The question to ask.
        save: Whether to save the answer to wiki/explorations/.
    """
    import warnings
    warnings.filterwarnings("ignore")
    from agents import set_tracing_disabled
    set_tracing_disabled(True)

    kb_dir = _get_kb_dir()
    from openkb.config import load_config, DEFAULT_CONFIG
    from openkb.agent.query import run_query

    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    model = config.get("model", DEFAULT_CONFIG["model"])

    try:
        answer = run_query(question, kb_dir, model, stream=False, raw=True)
        import asyncio
        answer = asyncio.get_event_loop().run_until_complete(
            asyncio.ensure_future(answer)
        )
    except Exception as exc:
        return f"Query failed: {exc}"

    if save and answer:
        import re
        from openkb.log import append_log
        slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60]
        explore_dir = kb_dir / "wiki" / "explorations"
        explore_dir.mkdir(parents=True, exist_ok=True)
        explore_path = explore_dir / f"{slug}.md"
        explore_path.write_text(
            f"---\nquery: \"{question}\"\n---\n\n{answer}\n", encoding="utf-8"
        )
        append_log(kb_dir / "wiki", "query", question)
        return f"{answer}\n\nSaved to {explore_path}"

    return answer or ""


@mcp.tool()
def kb_history(limit: int = 10) -> str:
    """Show recent history of wiki changes.

    Args:
        limit: Maximum number of entries to show (default 10).
    """
    kb_dir = _get_kb_dir()
    from openkb.history import list_snapshots, git_log

    lines = ["## Wiki History\n"]

    snapshots = list_snapshots(kb_dir, limit=5)
    if snapshots:
        lines.append("### Snapshots")
        for s in snapshots:
            label = f" — {s.get('label', '')}" if s.get("label") else ""
            lines.append(f"- `{s['id']}` {s['created_at']}{label} ({s.get('files', '?')} files)")

    git = git_log(kb_dir, max_count=limit)
    if git:
        lines.append("\n### Git Log")
        for line in git.split("\n")[:limit]:
            lines.append(f"- {line}")

    if not snapshots and not git:
        lines.append("No history available. Snapshots are created automatically on writes.")

    return "\n".join(lines)


@mcp.resource(uri="wiki://concepts", name="Concept Pages", description="All concept pages with brief descriptions")
def resource_concepts() -> str:
    wiki_root = _get_wiki_root()
    concepts_dir = Path(wiki_root) / "concepts"
    if not concepts_dir.exists():
        return "(no concepts)"
    lines = []
    for md in sorted(concepts_dir.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        brief = ""
        for line in text.split("\n")[:10]:
            if line.startswith("brief:"):
                brief = line[len("brief:"):].strip()
                break
        if not brief:
            body = text.split("---", 2)[-1] if "---" in text else text
            brief = body.strip().replace("\n", " ")[:100]
        lines.append(f"- {md.stem}: {brief}")
    return "\n".join(lines)


@mcp.resource(uri="wiki://summaries", name="Summary Pages", description="All document summary pages with brief descriptions")
def resource_summaries() -> str:
    wiki_root = _get_wiki_root()
    summaries_dir = Path(wiki_root) / "summaries"
    if not summaries_dir.exists():
        return "(no summaries)"
    lines = []
    for md in sorted(summaries_dir.glob("*.md")):
        lines.append(f"- {md.stem}")
    return "\n".join(lines)


@mcp.resource(uri="wiki://index", name="Knowledge Base Index", description="Master index of all documents, concepts, and explorations")
def resource_index() -> str:
    wiki_root = _get_wiki_root()
    return read_wiki_file("index.md", wiki_root)


@mcp.resource(uri="wiki://schema", name="Wiki Schema", description="AGENTS.md — wiki structure and conventions")
def resource_schema() -> str:
    wiki_root = _get_wiki_root()
    return read_wiki_file("AGENTS.md", wiki_root)


@mcp.resource(uri="wiki://log", name="Operations Log", description="Chronological record of operations")
def resource_log() -> str:
    wiki_root = _get_wiki_root()
    return read_wiki_file("log.md", wiki_root)


def run_stdio():
    _setup_mcp_key(_find_kb_dir())
    mcp.run()


async def run_sse(host: str = "0.0.0.0", port: int = 8001):
    _setup_mcp_key(_find_kb_dir())
    await mcp.run_sse_async(host=host, port=port)
