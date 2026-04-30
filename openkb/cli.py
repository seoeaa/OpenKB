"""OpenKB CLI — command-line interface for the knowledge base workflow."""
from __future__ import annotations

# Silence import-time warnings (e.g. pydub's missing-ffmpeg warning emitted
# when markitdown pulls it in). markitdown later clobbers the filters during
# its own import, so we re-apply after all imports below.
import warnings
warnings.filterwarnings("ignore")

import asyncio
import json
import logging
import time
from pathlib import Path

import os

from agents import set_tracing_disabled
set_tracing_disabled(True)
# Use local model cost map — skip fetching from GitHub on every invocation
os.environ.setdefault("LITELLM_LOCAL_MODEL_COST_MAP", "True")

import click
import litellm
litellm.suppress_debug_info = True
from dotenv import load_dotenv

from openkb.config import DEFAULT_CONFIG, load_config, save_config, load_global_config, register_kb
from openkb.converter import convert_document
from openkb.log import append_log
from openkb.schema import AGENTS_MD

# Suppress warnings after all imports — markitdown overrides filters at import time
import warnings
warnings.filterwarnings("ignore")

load_dotenv()  # load from cwd (covers running inside the KB dir)


def _setup_llm_key(kb_dir: Path | None = None) -> None:
    """Set LiteLLM API key from LLM_API_KEY env var if present.

    Load order (override=False, so first one wins):
    1. System environment variables (already set)
    2. KB-local .env  (kb_dir/.env)
    3. Global .env    (~/.config/openkb/.env)

    Also propagates to provider-specific env vars (OPENAI_API_KEY, etc.)
    so that the Agents SDK litellm provider can pick them up.
    """
    if kb_dir is not None:
        env_file = kb_dir / ".env"
        if env_file.exists():
            load_dotenv(env_file, override=False)

    from openkb.config import GLOBAL_CONFIG_DIR
    global_env = GLOBAL_CONFIG_DIR / ".env"
    if global_env.exists():
        load_dotenv(global_env, override=False)

    api_key = os.environ.get("LLM_API_KEY", "")
    if not api_key:
        # Check if any provider key is already set
        has_key = any(os.environ.get(k) for k in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"))
        if not has_key:
            click.echo(
                "Warning: No LLM API key found. Set one of:\n"
                f"  1. {kb_dir / '.env' if kb_dir else '<kb_dir>/.env'} — LLM_API_KEY=sk-...\n"
                f"  2. {GLOBAL_CONFIG_DIR / '.env'} — LLM_API_KEY=sk-...\n"
                "  3. Export LLM_API_KEY in your shell profile"
            )
    else:
        litellm.api_key = api_key
        for env_var in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY"):
            if not os.environ.get(env_var):
                os.environ[env_var] = api_key

# Supported document extensions for the `add` command
SUPPORTED_EXTENSIONS = {
    ".pdf", ".md", ".markdown", ".docx", ".pptx", ".xlsx",
    ".html", ".htm", ".txt", ".csv",
}

# Map raw doc types to display types
_TYPE_DISPLAY_MAP = {
    "long_pdf": "pageindex",
}

_SHORT_DOC_TYPES = {"pdf", "docx", "md", "markdown", "html", "htm", "txt", "csv", "pptx", "xlsx"}


def _display_type(raw_type: str) -> str:
    """Map a raw stored doc type to a display type string."""
    if raw_type in _TYPE_DISPLAY_MAP:
        return _TYPE_DISPLAY_MAP[raw_type]
    if raw_type in _SHORT_DOC_TYPES:
        return "short"
    return raw_type


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_kb_dir(override: Path | None = None) -> Path | None:
    """Find the KB root: explicit override → walk up from cwd → global default_kb."""
    # 0. Explicit override (--kb-dir or OPENKB_DIR)
    if override is not None:
        if (override / ".openkb").is_dir():
            return override
        return None
    # 1. Walk up from cwd
    current = Path.cwd().resolve()
    while True:
        if (current / ".openkb").is_dir():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    # 2. Fall back to global config default_kb
    gc = load_global_config()
    default = gc.get("default_kb")
    if default:
        p = Path(default)
        if (p / ".openkb").is_dir():
            return p
    return None


def add_single_file(file_path: Path, kb_dir: Path, subpath: str = "") -> None:
    """Convert, index, and compile a single document into the knowledge base.

    Args:
        file_path: Path to the file to add.
        kb_dir: Knowledge base root directory.
        subpath: Relative subdirectory path within raw/ (for nested folder support).
    """
    from openkb.agent.compiler import compile_long_doc, compile_short_doc
    from openkb.state import HashRegistry

    logger = logging.getLogger(__name__)
    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    _setup_llm_key(kb_dir)
    model: str = config.get("model", DEFAULT_CONFIG["model"])
    registry = HashRegistry(openkb_dir / "hashes.json")

    click.echo(f"Adding: {file_path.name}")
    try:
        result = convert_document(file_path, kb_dir, subpath=subpath)
    except Exception as exc:
        click.echo(f"  [ERROR] Conversion failed: {exc}")
        logger.debug("Conversion traceback:", exc_info=True)
        return

    if result.skipped:
        click.echo(f"  [SKIP] Already in knowledge base: {file_path.name}")
        return

    doc_name = file_path.stem
    if subpath:
        doc_name = subpath.replace("/", "-") + "-" + doc_name

    if result.is_long_doc:
        if result.long_doc_type == "chunked":
            click.echo(f"  Large document detected — chunking into sections...")
            from openkb.large_doc import index_large_nonpdf
            try:
                index_result = index_large_nonpdf(doc_name, result.source_path or (kb_dir / "wiki" / "sources" / f"{doc_name}.md"), kb_dir)
            except Exception as exc:
                click.echo(f"  [ERROR] Chunk indexing failed: {exc}")
                logger.debug("Chunk indexing traceback:", exc_info=True)
                return

            summary_path = kb_dir / "wiki" / "summaries" / f"{doc_name}.md"
            click.echo(f"  Compiling chunked doc (sections={len(index_result.get('tree', {}).get('structure', []))})...")
            for attempt in range(2):
                try:
                    asyncio.run(
                        compile_long_doc(doc_name, summary_path, index_result["doc_id"], kb_dir, model,
                                         doc_description=index_result.get("description", ""))
                    )
                    break
                except Exception as exc:
                    if attempt == 0:
                        click.echo(f"  Retrying compilation in 2s...")
                        time.sleep(2)
                    else:
                        click.echo(f"  [ERROR] Compilation failed: {exc}")
                        logger.debug("Compilation traceback:", exc_info=True)
                        return
            if result.file_hash:
                registry.add(result.file_hash, {"name": file_path.name, "type": "chunked"})
        else:
            click.echo(f"  Long document detected — indexing with PageIndex...")
            try:
                from openkb.indexer import index_long_document
                index_result = index_long_document(result.raw_path or file_path, kb_dir)
            except Exception as exc:
                click.echo(f"  [ERROR] Indexing failed: {exc}")
                logger.debug("Indexing traceback:", exc_info=True)
                return

            summary_path = kb_dir / "wiki" / "summaries" / f"{doc_name}.md"
            click.echo(f"  Compiling long doc (doc_id={index_result.doc_id})...")
            for attempt in range(2):
                try:
                    asyncio.run(
                        compile_long_doc(doc_name, summary_path, index_result.doc_id, kb_dir, model,
                                         doc_description=index_result.description)
                    )
                    break
                except Exception as exc:
                    if attempt == 0:
                        click.echo(f"  Retrying compilation in 2s...")
                        time.sleep(2)
                    else:
                        click.echo(f"  [ERROR] Compilation failed: {exc}")
                        logger.debug("Compilation traceback:", exc_info=True)
                        return
            if result.file_hash:
                doc_type = "long_pdf"
                registry.add(result.file_hash, {"name": file_path.name, "type": doc_type})
    else:
        click.echo(f"  Compiling short doc...")
        for attempt in range(2):
            try:
                asyncio.run(compile_short_doc(doc_name, result.source_path or (kb_dir / "wiki" / "sources" / f"{doc_name}.md"), kb_dir, model))
                break
            except Exception as exc:
                if attempt == 0:
                    click.echo(f"  Retrying compilation in 2s...")
                    time.sleep(2)
                else:
                    click.echo(f"  [ERROR] Compilation failed: {exc}")
                    logger.debug("Compilation traceback:", exc_info=True)
                    return
        if result.file_hash:
            doc_type = file_path.suffix.lstrip(".")
            registry.add(result.file_hash, {"name": file_path.name, "type": doc_type})

    append_log(kb_dir / "wiki", "ingest", file_path.name)
    click.echo(f"  [OK] {file_path.name} added to knowledge base.")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

@click.group()
@click.option("-v", "--verbose", is_flag=True, default=False, help="Enable verbose logging.")
@click.option("--kb-dir", "kb_dir_override", default=None, type=click.Path(exists=True, file_okay=False, resolve_path=True), help="Path to a KB root directory (overrides auto-detection).")
@click.pass_context
def cli(ctx, verbose, kb_dir_override):
    """OpenKB — Karpathy's LLM Knowledge Base workflow, powered by PageIndex."""
    logging.basicConfig(
        format="%(name)s %(levelname)s: %(message)s",
        level=logging.WARNING,
    )
    if verbose:
        logging.getLogger("openkb").setLevel(logging.DEBUG)
    ctx.ensure_object(dict)
    if kb_dir_override:
        ctx.obj["kb_dir_override"] = Path(kb_dir_override)
    else:
        env_kb = os.environ.get("OPENKB_DIR")
        if env_kb:
            ctx.obj["kb_dir_override"] = Path(env_kb).resolve()
        else:
            ctx.obj["kb_dir_override"] = None


@cli.command()
@click.argument("path", default=".")
def use(path):
    """Set PATH as the default knowledge base."""
    target = Path(path).resolve()
    if not (target / ".openkb").is_dir():
        click.echo(f"Not a knowledge base: {target}")
        return
    register_kb(target)
    click.echo(f"Default KB set to: {target}")


@cli.command()
def init():
    """Initialise a new knowledge base in the current directory."""
    openkb_dir = Path(".openkb")
    if openkb_dir.exists():
        click.echo("Knowledge base already initialized.")
        return

    # Interactive prompts
    click.echo("Pick an LLM in `provider/model` LiteLLM format:")
    click.echo("  OpenAI:    gpt-5.4-mini, gpt-5.4")
    click.echo("  Anthropic: anthropic/claude-sonnet-4-6, anthropic/claude-opus-4-6")
    click.echo("  Gemini:    gemini/gemini-3.1-pro-preview, gemini/gemini-3-flash-preview")
    click.echo("  Others:    see https://docs.litellm.ai/docs/providers")
    click.echo()
    model = click.prompt(
        f"Model (enter for default {DEFAULT_CONFIG['model']})",
        default=DEFAULT_CONFIG["model"],
        show_default=False,
    )
    api_key = click.prompt(
        "LLM API Key (saved to .env, enter to skip)",
        default="",
        hide_input=True,
        show_default=False,
    ).strip()
    # Create directory structure
    Path("raw").mkdir(exist_ok=True)
    Path("wiki/sources/images").mkdir(parents=True, exist_ok=True)
    Path("wiki/summaries").mkdir(parents=True, exist_ok=True)
    Path("wiki/concepts").mkdir(parents=True, exist_ok=True)

    # Write wiki files
    Path("wiki/AGENTS.md").write_text(AGENTS_MD, encoding="utf-8")
    Path("wiki/index.md").write_text(
        "# Knowledge Base Index\n\n## Documents\n\n## Concepts\n\n## Explorations\n",
        encoding="utf-8",
    )
    Path("wiki/log.md").write_text("# Operations Log\n\n", encoding="utf-8")

    # Create .openkb/ state directory
    openkb_dir.mkdir()
    config = {
        "model": model,
        "language": DEFAULT_CONFIG["language"],
        "pageindex_threshold": DEFAULT_CONFIG["pageindex_threshold"],
    }
    save_config(openkb_dir / "config.yaml", config)
    (openkb_dir / "hashes.json").write_text(json.dumps({}), encoding="utf-8")

    # Write API key to KB-local .env (0600) if the user provided one
    if api_key:
        env_path = Path(".env")
        if env_path.exists():
            click.echo(".env already exists, skipping write. Add LLM_API_KEY manually if needed.")
        else:
            env_path.write_text(f"LLM_API_KEY={api_key}\n", encoding="utf-8")
            os.chmod(env_path, 0o600)
            click.echo("Saved LLM API key to .env.")

    # Register this KB in the global config
    register_kb(Path.cwd())

    click.echo("Knowledge base initialized.")


@cli.command()
@click.argument("path")
@click.pass_context
def add(ctx, path):
    """Add a document or directory of documents at PATH to the knowledge base."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    target = Path(path)
    if not target.exists():
        click.echo(f"Path does not exist: {path}")
        return

    if target.is_dir():
        files = [
            f for f in sorted(target.rglob("*"))
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            click.echo(f"No supported files found in {path}.")
            return
        total = len(files)
        click.echo(f"Found {total} supported file(s) in {path}.")
        for i, f in enumerate(files, 1):
            rel_to_target = f.parent.relative_to(target)
            subpath = str(rel_to_target) if str(rel_to_target) != "." else ""
            click.echo(f"\n[{i}/{total}] ", nl=False)
            add_single_file(f, kb_dir, subpath=subpath)
    else:
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            click.echo(
                f"Unsupported file type: {target.suffix}. "
                f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
            )
            return
        add_single_file(target, kb_dir)


@cli.command()
@click.argument("question")
@click.option("--save", is_flag=True, default=False, help="Save the answer to wiki/explorations/.")
@click.option(
    "--raw", "raw",
    is_flag=True, default=False,
    help="Show raw markdown source instead of rendered output (keeps tool-call colors).",
)
@click.pass_context
def query(ctx, question, save, raw):
    """Query the knowledge base with QUESTION."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    from openkb.agent.query import run_query

    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    _setup_llm_key(kb_dir)
    model: str = config.get("model", DEFAULT_CONFIG["model"])

    try:
        answer = asyncio.run(run_query(question, kb_dir, model, stream=True, raw=raw))
    except Exception as exc:
        click.echo(f"[ERROR] Query failed: {exc}")
        return

    append_log(kb_dir / "wiki", "query", question)

    if save and answer:
        import re
        slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60]
        explore_dir = kb_dir / "wiki" / "explorations"
        explore_dir.mkdir(parents=True, exist_ok=True)
        explore_path = explore_dir / f"{slug}.md"
        explore_path.write_text(
            f"---\nquery: \"{question}\"\n---\n\n{answer}\n", encoding="utf-8"
        )
        click.echo(f"\nSaved to {explore_path}")


@cli.command()
@click.option(
    "--resume", "-r", "resume",
    is_flag=False, flag_value="__latest__", default=None, metavar="[ID]",
    help="Resume the latest chat session, or a specific one by id or prefix.",
)
@click.option(
    "--list", "list_sessions_flag",
    is_flag=True, default=False,
    help="List chat sessions.",
)
@click.option(
    "--delete", "delete_id",
    default=None, metavar="ID",
    help="Delete a chat session by id or prefix.",
)
@click.option(
    "--no-color", "no_color",
    is_flag=True, default=False,
    help="Disable colored output.",
)
@click.option(
    "--raw", "raw",
    is_flag=True, default=False,
    help="Show raw markdown source instead of rendered output (keeps prompt and tool-call colors).",
)
@click.pass_context
def chat(ctx, resume, list_sessions_flag, delete_id, no_color, raw):
    """Start an interactive chat with the knowledge base."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    from openkb.agent.chat_session import (
        ChatSession,
        delete_session,
        list_sessions,
        load_session,
        relative_time,
        resolve_session_id,
    )

    if list_sessions_flag:
        sessions = list_sessions(kb_dir)
        if not sessions:
            click.echo("No chat sessions yet.")
            return
        click.echo(f"  {'ID':<22} {'TURNS':<6} {'UPDATED':<12} TITLE")
        click.echo(f"  {'-'*22} {'-'*6} {'-'*12} {'-'*30}")
        for s in sessions:
            rel = relative_time(s.get("updated_at", ""))
            title = s.get("title") or "(empty)"
            click.echo(
                f"  {s['id']:<22} {s['turn_count']:<6} {rel:<12} {title}"
            )
        click.echo(
            f"\n{len(sessions)} session(s) in {kb_dir / '.openkb' / 'chats'}"
        )
        return

    if delete_id is not None:
        try:
            resolved = resolve_session_id(kb_dir, delete_id)
        except ValueError as exc:
            click.echo(f"[ERROR] {exc}")
            return
        if not resolved:
            click.echo(f"No matching session: {delete_id}")
            return
        if delete_session(kb_dir, resolved):
            click.echo(f"Deleted session {resolved}")
        else:
            click.echo(f"Could not delete session: {resolved}")
        return

    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    _setup_llm_key(kb_dir)

    if resume is not None:
        try:
            resolved = resolve_session_id(kb_dir, resume)
        except ValueError as exc:
            click.echo(f"[ERROR] {exc}")
            return
        if not resolved:
            if resume == "__latest__":
                click.echo("No previous chat sessions to resume.")
            else:
                click.echo(f"No matching session: {resume}")
            return
        session = load_session(kb_dir, resolved)
    else:
        model: str = config.get("model", DEFAULT_CONFIG["model"])
        language: str = config.get("language", "en")
        session = ChatSession.new(kb_dir, model, language)

    from openkb.agent.chat import run_chat

    try:
        asyncio.run(run_chat(kb_dir, session, no_color=no_color, raw=raw))
    except Exception as exc:
        click.echo(f"[ERROR] Chat failed: {exc}")


@cli.command()
@click.pass_context
def watch(ctx):
    """Watch the raw/ directory for new documents and process them automatically."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    from openkb.watcher import watch_directory

    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(exist_ok=True)

    def on_new_files(paths):
        for p in paths:
            fp = Path(p)
            if fp.suffix.lower() not in SUPPORTED_EXTENSIONS:
                click.echo(
                    f"Skipping unsupported file type: {fp.suffix}. "
                    f"Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"
                )
                continue
            add_single_file(fp, kb_dir, subpath="")

    click.echo(f"Watching {raw_dir} for new documents. Press Ctrl+C to stop.")
    watch_directory(raw_dir, on_new_files)


async def run_lint(kb_dir: Path) -> Path | None:
    """Run structural + knowledge lint, write report, return report path.

    Returns ``None`` if the KB has no indexed documents (nothing to lint).
    Async because knowledge lint uses an LLM agent. Usable from CLI
    (via ``asyncio.run``) and directly from the chat REPL.
    """
    from openkb.lint import run_structural_lint
    from openkb.agent.linter import run_knowledge_lint

    openkb_dir = kb_dir / ".openkb"

    # Skip lint entirely when the KB has no indexed documents
    hashes_file = openkb_dir / "hashes.json"
    if hashes_file.exists():
        hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
    else:
        hashes = {}
    if not hashes:
        click.echo("Nothing to lint — no documents indexed yet. Run `openkb add` first.")
        return

    config = load_config(openkb_dir / "config.yaml")
    _setup_llm_key(kb_dir)
    model: str = config.get("model", DEFAULT_CONFIG["model"])

    click.echo("Running structural lint...")
    structural_report = run_structural_lint(kb_dir)
    click.echo(structural_report)

    click.echo("Running knowledge lint...")
    try:
        knowledge_report = await run_knowledge_lint(kb_dir, model)
    except Exception as exc:
        knowledge_report = f"Knowledge lint failed: {exc}"
    click.echo(knowledge_report)

    # Write combined report
    reports_dir = kb_dir / "wiki" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    import datetime
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = reports_dir / f"lint_{timestamp}.md"
    report_content = f"# Lint Report — {timestamp}\n\n## Structural\n\n{structural_report}\n\n## Semantic\n\n{knowledge_report}\n"
    report_path.write_text(report_content, encoding="utf-8")
    append_log(kb_dir / "wiki", "lint", f"report → {report_path.name}")
    click.echo(f"\nReport written to {report_path}")
    return report_path


@cli.command()
@click.option("--fix", is_flag=True, default=False, help="Automatically fix lint issues (not yet implemented).")
@click.pass_context
def lint(ctx, fix):
    """Lint the knowledge base for structural and semantic inconsistencies."""
    if fix:
        click.echo("Warning: --fix is not yet implemented. Running lint in report-only mode.")
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    asyncio.run(run_lint(kb_dir))


def print_list(kb_dir: Path) -> None:
    """Print all documents in the knowledge base. Usable from CLI and chat REPL."""
    openkb_dir = kb_dir / ".openkb"
    hashes_file = openkb_dir / "hashes.json"
    if not hashes_file.exists():
        click.echo("No documents indexed yet.")
        return

    hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
    if not hashes:
        click.echo("No documents indexed yet.")
        return

    # Display documents table with count in header
    doc_count = len(hashes)
    click.echo(f"Documents ({doc_count}):")
    click.echo(f"  {'Name':<40} {'Type':<12} {'Pages':<8}")
    click.echo(f"  {'-'*40} {'-'*12} {'-'*8}")
    for file_hash, meta in hashes.items():
        name = meta.get("name", "unknown")
        raw_type = meta.get("type", "unknown")
        display = _display_type(raw_type)
        pages = meta.get("pages", "")
        pages_str = str(pages) if pages else ""
        click.echo(f"  {name:<40} {display:<12} {pages_str:<8}")

    # Display summaries
    summaries_dir = kb_dir / "wiki" / "summaries"
    if summaries_dir.exists():
        summaries = sorted(p.stem for p in summaries_dir.glob("*.md"))
        if summaries:
            click.echo(f"\nSummaries ({len(summaries)}):")
            for s in summaries:
                click.echo(f"  - {s}")

    # Display concepts
    concepts_dir = kb_dir / "wiki" / "concepts"
    if concepts_dir.exists():
        concepts = sorted(p.stem for p in concepts_dir.glob("*.md"))
        if concepts:
            click.echo(f"\nConcepts ({len(concepts)}):")
            for c in concepts:
                click.echo(f"  - {c}")

    # Display reports
    reports_dir = kb_dir / "wiki" / "reports"
    if reports_dir.exists():
        reports = sorted(p.name for p in reports_dir.glob("*.md"))
        if reports:
            click.echo(f"\nReports ({len(reports)}):")
            for r in reports:
                click.echo(f"  - {r}")


@cli.command(name="list")
@click.pass_context
def list_cmd(ctx):
    """List all documents in the knowledge base."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    print_list(kb_dir)


def print_status(kb_dir: Path) -> None:
    """Print knowledge base status. Usable from CLI and chat REPL."""
    wiki_dir = kb_dir / "wiki"
    subdirs = ["sources", "summaries", "concepts", "reports"]

    click.echo("Knowledge Base Status:")
    click.echo(f"  {'Directory':<20} {'Files':<10}")
    click.echo(f"  {'-'*20} {'-'*10}")

    for subdir in subdirs:
        path = wiki_dir / subdir
        if path.exists():
            count = len(list(path.glob("*.md")))
        else:
            count = 0
        click.echo(f"  {subdir:<20} {count:<10}")

    # Raw files
    raw_dir = kb_dir / "raw"
    if raw_dir.exists():
        raw_count = len([f for f in raw_dir.iterdir() if f.is_file()])
        click.echo(f"  {'raw':<20} {raw_count:<10}")

    # Hash registry summary
    openkb_dir = kb_dir / ".openkb"
    hashes_file = openkb_dir / "hashes.json"
    if hashes_file.exists():
        hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
        click.echo(f"\n  Total indexed: {len(hashes)} document(s)")

    # Last compile time: newest file in wiki/summaries/
    summaries_dir = wiki_dir / "summaries"
    if summaries_dir.exists():
        summaries = list(summaries_dir.glob("*.md"))
        if summaries:
            newest_summary = max(summaries, key=lambda p: p.stat().st_mtime)
            import datetime
            mtime = datetime.datetime.fromtimestamp(newest_summary.stat().st_mtime)
            click.echo(f"  Last compile:  {mtime.strftime('%Y-%m-%d %H:%M:%S')}")

    # Last lint time: newest file in wiki/reports/
    reports_dir = wiki_dir / "reports"
    if reports_dir.exists():
        reports = list(reports_dir.glob("*.md"))
        if reports:
            newest_report = max(reports, key=lambda p: p.stat().st_mtime)
            import datetime
            mtime = datetime.datetime.fromtimestamp(newest_report.stat().st_mtime)
            click.echo(f"  Last lint:     {mtime.strftime('%Y-%m-%d %H:%M:%S')}")


@cli.command()
@click.pass_context
def status(ctx):
    """Show the current status of the knowledge base."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    print_status(kb_dir)


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host for SSE transport.")
@click.option("--port", default=8001, type=int, help="Port for SSE transport.")
@click.pass_context
def mcp(ctx, host, port):
    """Start the MCP server (stdio or SSE transport)."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is not None:
        os.environ["OPENKB_DIR"] = str(kb_dir)

    if os.environ.get("OPENKB_MCP_SSE"):
        import asyncio
        from openkb.mcp_server import run_sse
        click.echo(f"Starting MCP server (SSE) on {host}:{port}")
        asyncio.run(run_sse(host, port))
    else:
        from openkb.mcp_server import run_stdio
        click.echo("Starting MCP server (stdio). Connect via MCP-compatible client.")
        run_stdio()


@cli.command()
@click.argument("paths", nargs=-1, required=True)
@click.pass_context
def graph(ctx, paths):
    """Generate an interactive graph visualization of wiki connections.

    Outputs an HTML file with an interactive force-directed graph.
    If a .md path is also given, exports an adjacency list in Markdown.
    """
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    from openkb.graph import generate_graph

    output_paths = list(paths)
    html_path = None
    md_path = None

    for p in output_paths:
        p_str = str(p)
        if p_str.endswith(".html"):
            html_path = Path(p_str)
        elif p_str.endswith(".md"):
            md_path = Path(p_str)

    if html_path is None:
        html_path = kb_dir / "wiki" / "graph.html"

    generate_graph(kb_dir, html_path, md_path)
    click.echo(f"Graph generated: {html_path}")
    if md_path:
        click.echo(f"Adjacency list: {md_path}")


@cli.command()
@click.argument("source_dir", type=click.Path(exists=True, file_okay=False))
@click.argument("target_subdir", default="mirror")
@click.pass_context
def mirror(ctx, source_dir, target_subdir):
    """Mirror an external directory of Markdown files into the wiki.

    Watches source_dir for changes and syncs .md files into wiki/<target_subdir>/.
    """
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    from openkb.sync import MirrorSync

    source = Path(source_dir).resolve()
    target = kb_dir / "wiki" / target_subdir

    click.echo(f"Mirroring {source} → {target}")
    click.echo("Press Ctrl+C to stop.")

    sync = MirrorSync(source, target)
    synced = sync.full_sync()
    click.echo(f"Initial sync: {len(synced)} file(s)")

    from openkb.watcher import watch_directory
    watch_directory(source, lambda paths: sync.sync_paths([Path(p) for p in paths]))


@cli.group(name="sync")
@click.pass_context
def sync_group(ctx):
    """Git-based sync commands for the knowledge base."""
    pass


@sync_group.command("init")
@click.pass_context
def sync_init(ctx):
    """Initialize git repository in the knowledge base."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import init_git
    if init_git(kb_dir):
        click.echo(f"Git initialized: {kb_dir}")
    else:
        click.echo("Failed to initialize git.")


@sync_group.command("remote")
@click.argument("url")
@click.pass_context
def sync_remote(ctx, url):
    """Set the git remote URL for sync."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import init_git, set_remote
    init_git(kb_dir)
    if set_remote(kb_dir, url):
        click.echo(f"Remote set to: {url}")
    else:
        click.echo("Failed to set remote.")


@sync_group.command("commit")
@click.option("--message", "-m", default="auto: wiki update", help="Commit message.")
@click.pass_context
def sync_commit(ctx, message):
    """Commit wiki changes to git."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import commit
    if commit(kb_dir, message):
        click.echo("Committed.")
    else:
        click.echo("Nothing to commit or git not available.")


@sync_group.command("push")
@click.pass_context
def sync_push(ctx):
    """Push committed changes to the remote."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import push
    ok, msg = push(kb_dir)
    click.echo(msg if ok else f"[ERROR] {msg}")


@sync_group.command("pull")
@click.pass_context
def sync_pull(ctx):
    """Pull changes from the remote."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import pull
    ok, msg = pull(kb_dir)
    click.echo(msg if ok else f"[ERROR] {msg}")


@sync_group.command(name="sync")
@click.option("--message", "-m", default="auto: wiki sync", help="Commit message.")
@click.pass_context
def sync_sync(ctx, message):
    """Commit, push and pull (bidirectional sync)."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import sync
    ok, msg = sync(kb_dir, message)
    click.echo(msg if ok else f"[ERROR] {msg}")


@sync_group.command("status")
@click.pass_context
def sync_status(ctx):
    """Show git status for the wiki."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.sync_git import status
    click.echo(status(kb_dir))


@cli.command(name="tree")
@click.pass_context
def tree_cmd(ctx):
    """Show concept hierarchy as a tree."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return

    concepts_dir = kb_dir / "wiki" / "concepts"
    if not concepts_dir.exists() or not list(concepts_dir.glob("*.md")):
        click.echo("No concepts yet.")
        return

    parent_map: dict[str, str | None] = {}
    titles: dict[str, str] = {}

    for md in sorted(concepts_dir.glob("*.md")):
        slug = md.stem
        text = md.read_text(encoding="utf-8")
        titles[slug] = slug.replace("-", " ").title()
        parent = None
        if text.startswith("---"):
            end = text.find("---", 3)
            if end != -1:
                fm = text[:end + 3]
                for line in fm.split("\n"):
                    if line.startswith("parent:"):
                        parent = line[len("parent:"):].strip()
                        break
                for line in fm.split("\n"):
                    if line.startswith("title:"):
                        titles[slug] = line[len("title:"):].strip()
                        break
        parent_map[slug] = parent

    roots = [s for s, p in parent_map.items() if not p]
    children: dict[str, list[str]] = {s: [] for s in parent_map}
    for slug, parent in parent_map.items():
        if parent and parent in parent_map:
            children.setdefault(parent, []).append(slug)

    def _print_node(slug: str, indent: int = 0):
        prefix = "  " * indent + ("\u2514\u2500 " if indent > 0 else "")
        click.echo(f"{prefix}[[concepts/{slug}]] \u2014 {titles.get(slug, slug)}")
        for child in sorted(children.get(slug, [])):
            _print_node(child, indent + 1)

    for root in sorted(roots):
        _print_node(root, 0)

    orphans = [s for s in parent_map if s not in roots and not parent_map.get(s)]
    if orphans:
        click.echo("\nOrphaned concepts (no parent):")
        for s in sorted(orphans):
            click.echo(f"  [[concepts/{s}]] \u2014 {titles.get(s, s)}")


@cli.group(name="history")
@click.pass_context
def history_group(ctx):
    """Page history and versioning commands."""
    pass


@history_group.command("snapshot")
@click.option("--label", "-l", default="", help="Label for the snapshot.")
@click.pass_context
def history_snapshot(ctx, label):
    """Create a full wiki snapshot."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.history import snapshot_wiki
    snap_id = snapshot_wiki(kb_dir, label)
    if snap_id:
        click.echo(f"Snapshot created: {snap_id}")
    else:
        click.echo("Wiki directory is empty.")


@history_group.command("list")
@click.option("--limit", "-n", default=20, type=int, help="Number of entries.")
@click.pass_context
def history_list(ctx, limit):
    """List recent snapshots and git history."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.history import list_snapshots, git_log

    snapshots = list_snapshots(kb_dir, limit=limit)
    if snapshots:
        click.echo("Snapshots:")
        for s in snapshots:
            label = f" — {s.get('label', '')}" if s.get("label") else ""
            files = s.get('files', '?')
            click.echo(f"  {s['id']}  {s['created_at']}{label}  ({files} files)")

    git = git_log(kb_dir, max_count=limit)
    if git:
        click.echo("\nGit log:")
        for line in git.split("\n"):
            click.echo(f"  {line}")

    if not snapshots and not git:
        click.echo("No history available.")


@history_group.command("show")
@click.argument("snap_id")
@click.pass_context
def history_show(ctx, snap_id):
    """Show files in a snapshot."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.history import get_snapshot, get_snapshot_files

    snap = get_snapshot(kb_dir, snap_id)
    if snap is None:
        click.echo(f"Snapshot not found: {snap_id}")
        return

    click.echo(f"Snapshot: {snap['id']}")
    click.echo(f"Created:  {snap['created_at']}")
    if snap.get("label"):
        click.echo(f"Label:    {snap['label']}")
    click.echo(f"Type:     {snap.get('type', 'full')}")
    click.echo()
    click.echo("Files:")
    for f in get_snapshot_files(kb_dir, snap["id"]):
        click.echo(f"  - {f}")


@history_group.command("restore")
@click.argument("snap_id")
@click.option("--page", default=None, help="Restore only a specific page (relative to wiki root).")
@click.option("--dry-run", is_flag=True, default=False, help="Show what would be restored without doing it.")
@click.pass_context
def history_restore(ctx, snap_id, page, dry_run):
    """Restore wiki from a snapshot."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.history import restore_snapshot, restore_page

    if page:
        ok = restore_page(kb_dir, snap_id, page)
        if ok:
            click.echo(f"Restored page: {page}")
        else:
            click.echo(f"Failed to restore page: {page}")
    else:
        result = restore_snapshot(kb_dir, snap_id, dry_run=dry_run)
        if "error" in result:
            click.echo(f"Error: {result['error']}")
        elif dry_run:
            click.echo(f"Would restore {len(result['restored'])} file(s):")
            for f in result["restored"]:
                click.echo(f"  - {f}")
        else:
            click.echo(f"Restored {len(result['restored'])} file(s)")


@history_group.command("prune")
@click.option("--keep", "-k", default=50, type=int, help="Number of snapshots to keep.")
@click.pass_context
def history_prune(ctx, keep):
    """Remove old snapshots."""
    kb_dir = _find_kb_dir(ctx.obj.get("kb_dir_override"))
    if kb_dir is None:
        click.echo("No knowledge base found. Run `openkb init` first.")
        return
    from openkb.history import prune_snapshots
    removed = prune_snapshots(kb_dir, keep=keep)
    click.echo(f"Pruned {removed} snapshot(s), kept {keep}.")
