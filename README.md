<div align="center">

<a href="https://openkb.ai">
  <img src="https://docs.pageindex.ai/images/openkb.png" alt="OpenKB (by PageIndex)" />
</a>

# OpenKB — Open LLM Knowledge Base

<p align="center"><i>Scale to long documents&nbsp; • &nbsp;Reasoning-based retrieval&nbsp; • &nbsp;Native multi-modality&nbsp; • &nbsp;No Vector DB</i></p>

</div>

---

# 📑 What is OpenKB

**OpenKB (Open Knowledge Base)** is an open-source system (in CLI) that compiles raw documents into a structured, interlinked wiki-style knowledge base using LLMs, powered by [**PageIndex**](https://github.com/VectifyAI/PageIndex) for vectorless long document retrieval.

The idea is based on a [concept](https://x.com/karpathy/status/2039805659525644595) described by Andrej Karpathy: LLMs generate summaries, concept pages, and cross-references, all maintained automatically. Knowledge compounds over time instead of being re-derived on every query.

### Why not traditional RAG?

Traditional RAG rediscovers knowledge from scratch on every query. Nothing accumulates. OpenKB compiles knowledge once into a persistent wiki, then keeps it current. Cross-references already exist. Contradictions are flagged. Synthesis reflects everything consumed.

### Core Features

- **Broad format support** — PDF, Word, Markdown, PowerPoint, HTML, Excel, text, and more via markitdown
- **Scale to long documents** — Long and complex documents are handled via [PageIndex](https://github.com/VectifyAI/PageIndex) tree indexing, enabling accurate, vectorless long-context retrieval
- **Native multi-modality** — Retrieves and understands figures, tables, and images, not just text
- **Compiled Wiki** — LLM manages and compiles your documents into summaries, concept pages, and cross-links, all kept in sync
- **Query** — Ask questions (one-off) against your wiki. The LLM navigates your compiled knowledge to answer
- **Interactive Chat** — Multi-turn conversations with persisted sessions you can resume across runs
- **Lint** — Health checks find contradictions, gaps, orphans, and stale content
- **Watch mode** — Drop files into `raw/`, wiki updates automatically
- **Obsidian compatible** — Wiki is plain `.md` files with `[[wikilinks]]`. Open in Obsidian for graph view and browsing

### Extensions

- **MCP Server** — Expose your knowledge base as MCP tools for AI agents (Claude Desktop, Kilo, Cursor, etc.). 12 tools: `kb_query`, `kb_search`, `kb_lint`, `kb_list`, `kb_read`, `kb_write`, `kb_status`, `kb_history`, and more. 5 dynamic resources. stdio and SSE transports.
- **REST API** — HTTP API with 7 endpoints (`/api/status`, `/api/list`, `/api/read`, `/api/query`, `/api/add`, `/api/lint`, `/api/search`) + WebSocket chat. Use from any language.
- **Agent Skills** — 9 built-in slash commands: `/summarize`, `/compare`, `/export`, `/search`, `/diff`, `/snapshot`, `/history`, `/revert`, `/sync`. Extensible via plugins.
- **Page History** — Automatic snapshots on every wiki write. `openkb history snapshot`, `list`, `show`, `restore` (with `--dry-run`), `prune`. Git log integration.
- **Git Sync** — Self-hosted sync between devices. `openkb sync init`, `remote <url>`, `commit`, `push`, `pull`, `sync`. Bidirectional commit-pull-push in one command.
- **Graph Visualization** — `openkb graph` generates an interactive force-directed HTML graph of all wiki connections + optional Markdown adjacency list.
- **Markdown Mirror** — `openkb mirror <source-dir>` watches an external directory of `.md` files and syncs into the wiki.
- **Plugin System** — Drop Python plugins into `.openkb/plugins/`. Register lifecycle hooks (`pre_compile`, `post_query`, etc.) and custom slash commands.

# 🚀 Getting Started

### Install

```bash
pip install openkb
```

<details>
<summary><i>Other install options</i></summary>

- **Latest from GitHub:**

  ```bash
  pip install git+https://github.com/VectifyAI/OpenKB.git
  ```

- **Install from source** (editable, for development):

  ```bash
  git clone https://github.com/VectifyAI/OpenKB.git
  cd OpenKB
  pip install -e .
  ```

</details>

### Quick Start

```bash
# 1. Create a directory for your knowledge base
mkdir my-kb && cd my-kb

# 2. Initialize the knowledge base
openkb init

# 3. Add documents
openkb add paper.pdf
openkb add ~/papers/  # Add a whole directory

# 4. Ask a question
openkb query "What are the main findings?"

# 5. Or chat interactively
openkb chat
```

### Set up your LLM

OpenKB comes with [multi-LLM support](https://docs.litellm.ai/docs/providers) (e.g., OpenAI, Claude, Gemini) via [LiteLLM](https://github.com/BerriAI/litellm) (pinned to a [safe version](https://docs.litellm.ai/blog/security-update-march-2026)).

Set your model during `openkb init`, or in [`.openkb/config.yaml`](#configuration), using `provider/model` LiteLLM format (like `anthropic/claude-sonnet-4-6`). OpenAI models can omit the prefix (like `gpt-5.4`).

Create a `.env` file with your LLM API key:

```bash
LLM_API_KEY=your_llm_api_key
```

# 🧩 How OpenKB Works

### Architecture

```
raw/                              You drop files here
 │
 ├─ Short docs ──→ markitdown ──→ LLM reads full text
 │                                     │
 ├─ Long PDFs ──→ PageIndex ────→ LLM reads document trees
 │                                     │
 │                                     ▼
 │                         Wiki Compilation (using LLM)
 │                                     │
 ▼                                     ▼
wiki/
 ├── index.md            Knowledge base overview
 ├── log.md              Operations timeline
 ├── AGENTS.md           Wiki schema (LLM instructions)
 ├── sources/            Full-text conversions
 ├── summaries/          Per-document summaries
 ├── concepts/           Cross-document synthesis ← the good stuff
 ├── explorations/       Saved query results
 └── reports/            Lint reports
```

### Short vs. Long Document Handling

| | Short documents | Long documents (PDF ≥ 20 pages) |
|---|---|---|
| **Convert** | markitdown → Markdown | PageIndex → tree index + summaries |
| **Images** | Extracted inline (pymupdf) | Extracted by PageIndex |
| **LLM reads** | Full text | Document trees |
| **Result** | summary + concepts | summary + concepts |

Short docs are read in full by the LLM. Long PDFs are indexed by PageIndex into a hierarchical tree with summaries. The LLM reads the tree instead of the full text, enabling better retrieval from long documents.

### Knowledge Compilation

When you add a document, the LLM:

1. Generates a **summary** page
2. Reads existing **concept** pages
3. Creates or updates concepts with cross-document synthesis
4. Updates the **index** and **log**

A single source might touch 10-15 wiki pages. Knowledge accumulates: each document enriches the existing wiki rather than sitting in isolation.

# ⚙️ Usage

### Commands

| Command | Description |
|---|---|
| `openkb init` | Initialize a new knowledge base (interactive) |
| <code>openkb&nbsp;add&nbsp;&lt;file_or_dir&gt;</code> | Add documents and compile to wiki |
| <code>openkb&nbsp;query&nbsp;"question"</code> | Ask a question over the knowledge base (use `--save` to save the answer to `wiki/explorations/`) |
| `openkb chat` | Start an interactive multi-turn chat (use `--resume`, `--list`, `--delete` to manage sessions) |
| `openkb watch` | Watch `raw/` and auto-compile new files |
| `openkb lint` | Run structural + knowledge health checks |
| `openkb list` | List indexed documents and concepts |
| `openkb status` | Show knowledge base stats |
| `openkb mcp` | Start MCP server (stdio by default, SSE with `OPENKB_MCP_SSE=1`) |
| `openkb api` | Start REST API server on `http://localhost:8000` |
| `openkb graph [output.html]` | Generate interactive graph visualization |
| `openkb mirror <source-dir>` | Mirror external `.md` directory into wiki |
| `openkb sync <subcommand>` | Git-based sync: `init`, `remote`, `commit`, `push`, `pull`, `sync`, `status` |
| `openkb history <subcommand>` | Page versioning: `snapshot`, `list`, `show`, `restore`, `prune` |

### Interactive Chat

`openkb chat` opens an interactive chat session over your wiki knowledge base. Unlike the one-shot `openkb query`, each turn carries the conversation history, so you can dig into a topic without re-typing context.

```bash
openkb chat                       # start a new session
openkb chat --resume              # resume the most recent session
openkb chat --resume 20260411     # resume by id (unique prefix works)
openkb chat --list                # list all sessions
openkb chat --delete <id>         # delete a session
```

Inside a chat, type `/` to access slash commands (Tab to complete):

**Built-in:**
- `/help` — list available commands
- `/status` — show knowledge base status
- `/list` — list all documents
- `/add <path>` — add a document or directory without leaving the chat
- `/save [name]` — export the transcript to `wiki/explorations/`
- `/clear` — start a fresh session (the current one stays on disk)
- `/lint` — run knowledge base lint
- `/exit` — exit (Ctrl-D also works)

**Skills (LLM-powered):**
- `/summarize <page>` — summarize a wiki page
- `/compare <p1> <p2>` — compare two wiki pages side by side
- `/export <file> [concepts|summaries|all]` — export wiki to a single Markdown file
- `/search <pattern>` — full-text search across all wiki pages
- `/diff` — show recent git changes
- `/snapshot [label]` — create a named wiki snapshot
- `/history` — list snapshots and git log
- `/revert <id> [--dry-run]` — restore wiki to a previous snapshot
- `/sync` — commit, push, and pull in one step

### Configuration

Settings are initialized by `openkb init`, and stored in `.openkb/config.yaml`:

```yaml
model: gpt-5.4                   # LLM model (any LiteLLM-supported provider)
language: en                     # Wiki output language
pageindex_threshold: 20          # PDF pages threshold for PageIndex
```

Model names use `provider/model` LiteLLM [format](https://docs.litellm.ai/docs/providers) (OpenAI models can omit the prefix):

| Provider | Model example |
|---|---|
| OpenAI | `gpt-5.4` |
| Anthropic | `anthropic/claude-sonnet-4-6` |
| Gemini | `gemini/gemini-3.1-pro-preview` |

### MCP Server

OpenKB can run as an MCP (Model Context Protocol) server, exposing your knowledge base to any MCP-compatible AI agent (Claude Desktop, Kilo, Cursor, Windsurf, etc.).

```bash
openkb mcp                        # stdio transport (for Claude Desktop / Kilo)
OPENKB_MCP_SSE=1 openkb mcp      # SSE transport on http://localhost:8001
```

**Available tools (12):**
`kb_list`, `kb_read`, `kb_read_index`, `kb_read_concept`, `kb_read_summary`, `kb_get_pages`, `kb_write`, `kb_status`, `kb_lint`, `kb_search`, `kb_query`, `kb_history`

**Available resources (5):**
`wiki://index`, `wiki://schema`, `wiki://log`, `wiki://concepts`, `wiki://summaries`

Example Claude Desktop config (`claude_desktop_config.json`):
```json
{
  "mcpServers": {
    "openkb": {
      "command": "openkb",
      "args": ["mcp", "--kb-dir", "/home/user/my-kb"]
    }
  }
}
```

### REST API

Start an HTTP API to access your knowledge base from any client:

```bash
openkb api                       # start on http://0.0.0.0:8000
OPENKB_API_PORT=3000 openkb api  # custom port
```

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/status` | KB statistics |
| `GET` | `/api/list` | All pages (summaries, concepts, explorations) |
| `GET` | `/api/read?path=<path>` | Read a wiki page |
| `POST` | `/api/query` | Ask a question (`{"question": "..."}`) |
| `POST` | `/api/add` | Add a document (`{"path": "..."}`) |
| `POST` | `/api/lint` | Run structural + semantic lint |
| `GET` | `/api/search?q=<pattern>` | Full-text search |
| `WS` | `/ws/chat` | WebSocket multi-turn chat |

### Page History

OpenKB automatically snapshots your wiki before every write (summary generation, concept updates). You can also create snapshots manually.

```bash
openkb history snapshot -l "before big change"  # create named snapshot
openkb history list                              # list recent snapshots
openkb history show <id>                         # view snapshot contents
openkb history restore <id> --dry-run            # preview restore
openkb history restore <id>                      # restore full wiki
openkb history prune -k 50                       # keep newest 50 snapshots
```

### Git Sync

Sync your knowledge base across devices via git:

```bash
openkb sync init                   # initialize git repo
openkb sync remote <url>           # set remote (GitHub, GitLab, private)
openkb sync status                 # check for uncommitted changes
openkb sync commit -m "message"    # commit wiki changes
openkb sync push                   # push to remote
openkb sync pull                   # pull from remote
openkb sync sync                   # commit + pull + push in one step
```

### Graph Visualization

Generate an interactive force-directed graph of all wiki connections:

```bash
openkb graph wiki/graph.html                    # HTML only
openkb graph graph.html wiki/adjacency.md       # HTML + Markdown adjacency list
```

The HTML file opens a full-screen interactive graph where you can drag nodes, hover for descriptions, and filter by page type (concepts, summaries, explorations).

### Markdown Mirror

Mirror an external directory of Markdown files into your wiki. Useful for integrating with tools that export to `.md`:

```bash
openkb mirror ~/my-notes           # sync ~/my-notes into wiki/mirror/
openkb mirror ~/projects project   # sync into wiki/project/
```

### Plugin System

Extend OpenKB with custom plugins. Create a `.py` file or package in `.openkb/plugins/`:

```python
# .openkb/plugins/translator.py
def setup(register_hook):
    register_hook("post_compile", lambda **kw: print("Compilation done!"))

def get_slash_commands():
    return [{"name": "hello", "description": "Say hello",
             "handler": hello_handler, "needs_arg": False}]

async def hello_handler(arg="", kb_dir=None, style=None, fmt_fn=None, **kwargs):
    fmt_fn(style, ("class:slash.ok", "Hello from plugin!\n"))
```

Available hooks: `pre_compile`, `post_compile`, `pre_query`, `post_query`, `pre_lint`, `post_lint`, `on_startup`.

### PageIndex Integration

Long documents are challenging for LLMs due to context limits, context rot, and summarization loss.
[PageIndex](https://github.com/VectifyAI/PageIndex) solves this with vectorless, reasoning-based retrieval — building a hierarchical tree index that lets LLMs reason over the index for context-aware retrieval.

PageIndex runs locally by default using the [open-source version](https://github.com/VectifyAI/PageIndex), with no external dependencies required.

#### Optional: Cloud Support

For large or complex PDFs, [PageIndex Cloud](https://docs.pageindex.ai/) can be used to access additional capabilities, including:

- OCR support for scanned PDFs (via hosted VLM models)
- Faster structure generation
- Scalable indexing for large documents

Set `PAGEINDEX_API_KEY` in your `.env` to enable cloud features:

```
PAGEINDEX_API_KEY=your_pageindex_api_key
```

### AGENTS.md

The `wiki/AGENTS.md` file defines wiki structure and conventions. It's the LLM's instruction manual for maintaining the wiki. Customize it to change how your wiki is organized.

At runtime, the LLM reads `AGENTS.md` from disk, so your edits take effect immediately.

### Using with Obsidian

OpenKB's wiki is a directory of Markdown files with `[[wikilinks]]`. Obsidian renders it natively.

1. Open `wiki/` as an Obsidian vault
2. Browse summaries, concepts, and explorations
3. Use graph view to see knowledge connections
4. Use Obsidian Web Clipper to add web articles to `raw/`

# 🧭 Learn More

### Compared to Karpathy's Approach

| | Karpathy's workflow | OpenKB |
|---|---|---|
| Short documents | LLM reads directly | markitdown → LLM reads |
| Long documents | Context limits, context rot | PageIndex tree index |
| Supported formats | Web clipper → .md | PDF, Word, PPT, Excel, HTML, text, CSV, .md |
| Wiki compilation | LLM agent | LLM agent (same) |
| Q&A | Query over wiki | Wiki + PageIndex retrieval |

### The Stack

- [PageIndex](https://github.com/VectifyAI/PageIndex) — Vectorless, reasoning-based document indexing and retrieval
- [markitdown](https://github.com/microsoft/markitdown) — Universal file-to-markdown conversion
- [OpenAI Agents SDK](https://github.com/openai/openai-agents-python) — Agent framework (supports non-OpenAI models via LiteLLM)
- [LiteLLM](https://github.com/BerriAI/litellm) — Multi-provider LLM gateway
- [MCP](https://modelcontextprotocol.io/) — Model Context Protocol server for AI agent integration
- [Starlette](https://www.starlette.io/) — HTTP API server with WebSocket support
- [Uvicorn](https://www.uvicorn.org/) — ASGI server
- [Click](https://click.palletsprojects.com/) — CLI framework
- [watchdog](https://github.com/gorakhargosh/watchdog) — Filesystem monitoring
- [prompt_toolkit](https://python-prompt-toolkit.readthedocs.io/) — Interactive chat REPL
- [Rich](https://rich.readthedocs.io/) — Terminal markdown rendering

### Roadmap

- [x] MCP server (stdio + SSE) — expose KB to AI agents
- [x] REST API + WebSocket chat — HTTP interface for any client
- [x] Agent skills — extensible slash commands in chat REPL
- [x] Page history & snapshots — versioning with restore
- [x] Git-based sync — self-hosted multi-device sync
- [x] Graph visualization — interactive knowledge graph
- [x] Markdown mirror — sync external .md directories
- [x] Plugin system — hooks and custom commands
- [ ] Extend long document handling to non-PDF formats
- [ ] Scale to large document collections with nested folder support
- [ ] Hierarchical concept (topic) indexing for massive knowledge bases
- [ ] Database-backed storage engine
- [ ] Web UI for browsing and managing wikis

### Contributing

Contributions are welcome! Please submit a pull request, or open an [issue](https://github.com/VectifyAI/OpenKB/issues) for bugs or feature requests. For larger changes, consider opening an issue first to discuss the approach.

### License

Apache 2.0. See [LICENSE](LICENSE).

### Support Us

If you find OpenKB useful, please give us a star 🌟 — and check out [PageIndex](https://github.com/VectifyAI/PageIndex) too!  

<div>

[![Twitter](https://img.shields.io/badge/Twitter-000000?style=for-the-badge&logo=x&logoColor=white)](https://x.com/PageIndexAI)&ensp;
[![LinkedIn](https://img.shields.io/badge/LinkedIn-0077B5?style=for-the-badge&logo=linkedin&logoColor=white)](https://www.linkedin.com/company/vectify-ai/)&ensp;
[![Contact Us](https://img.shields.io/badge/Contact_Us-3B82F6?style=for-the-badge&logo=envelope&logoColor=white)](https://ii2abc2jejf.typeform.com/to/tK3AXl8T)

</div>
