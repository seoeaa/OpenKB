"""OpenKB REST API server.

Usage:
    openkb api                  # Start on http://localhost:8000
    OPENKB_API_PORT=3000 openkb api
"""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse, HTMLResponse
from starlette.routing import Route, WebSocket


def _find_kb_dir() -> Path | None:
    env = os.environ.get("OPENKB_DIR")
    if env:
        p = Path(env).resolve()
        if (p / ".openkb").is_dir():
            return p
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


def _require_kb(request: Request):
    kb = request.app.state.kb_dir
    if kb is None:
        return JSONResponse({"error": "No knowledge base found. Set OPENKB_DIR."}, status_code=404)
    return None


async def status_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir
    wiki = kb_dir / "wiki"
    result: dict[str, Any] = {"path": str(kb_dir)}

    for subdir in ["sources", "summaries", "concepts", "reports", "explorations"]:
        path = wiki / subdir
        result[subdir] = len(list(path.glob("*.md"))) if path.exists() else 0

    raw_dir = kb_dir / "raw"
    result["raw"] = len([f for f in raw_dir.iterdir() if f.is_file()]) if raw_dir.exists() else 0

    hashes_file = kb_dir / ".openkb" / "hashes.json"
    if hashes_file.exists():
        hashes = json.loads(hashes_file.read_text(encoding="utf-8"))
        result["indexed_documents"] = len(hashes)
        result["documents"] = [
            {"name": m.get("name", ""), "type": m.get("type", "")}
            for m in hashes.values()
        ]

    return JSONResponse(result)


async def list_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir
    wiki = kb_dir / "wiki"

    result: dict[str, Any] = {"summaries": [], "concepts": [], "explorations": []}

    for subdir in result:
        d = wiki / subdir
        if not d.exists():
            continue
        for md in sorted(d.glob("*.md")):
            text = md.read_text(encoding="utf-8")[:500]
            result[subdir].append({"name": md.stem, "preview": text})

    return JSONResponse(result)


async def read_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir
    path = request.query_params.get("path", "")
    if not path:
        return JSONResponse({"error": "Missing 'path' parameter"}, status_code=400)

    from openkb.agent.tools import read_wiki_file
    content = read_wiki_file(path, str(kb_dir / "wiki"))
    if content.startswith("File not found"):
        return JSONResponse({"error": f"File not found: {path}"}, status_code=404)
    return JSONResponse({"path": path, "content": content})


async def query_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir

    body = await request.json()
    question = body.get("question", "")
    if not question:
        return JSONResponse({"error": "Missing 'question'"}, status_code=400)

    save = body.get("save", False)
    raw = body.get("raw", False)

    from openkb.config import load_config, DEFAULT_CONFIG
    from openkb.agent.query import run_query
    import warnings
    warnings.filterwarnings("ignore")

    from agents import set_tracing_disabled
    set_tracing_disabled(True)

    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    model = config.get("model", DEFAULT_CONFIG["model"])

    try:
        answer = await run_query(question, kb_dir, model, stream=False, raw=raw)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)

    result: dict[str, Any] = {"answer": answer}
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
        result["saved_to"] = str(explore_path)
        append_log(kb_dir / "wiki", "query", question)

    return JSONResponse(result)


async def add_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir

    body = await request.json()
    path = body.get("path", "")
    if not path:
        return JSONResponse({"error": "Missing 'path'"}, status_code=400)

    target = Path(path).expanduser().resolve()
    if not target.exists():
        return JSONResponse({"error": f"Path not found: {path}"}, status_code=404)

    from openkb.cli import add_single_file, SUPPORTED_EXTENSIONS

    if target.is_dir():
        files = [
            f for f in sorted(target.rglob("*"))
            if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
        ]
        if not files:
            return JSONResponse({"error": f"No supported files in {path}"}, status_code=400)
        added = []
        for f in files:
            import asyncio
            await asyncio.to_thread(add_single_file, f, kb_dir)
            added.append(f.name)
        return JSONResponse({"added": added, "count": len(added)})
    else:
        if target.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return JSONResponse(
                {"error": f"Unsupported: {target.suffix}. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}"},
                status_code=400,
            )
        import asyncio
        await asyncio.to_thread(add_single_file, target, kb_dir)
        return JSONResponse({"added": [target.name], "count": 1})


async def lint_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir

    from openkb.cli import run_lint
    import warnings
    warnings.filterwarnings("ignore")
    from agents import set_tracing_disabled
    set_tracing_disabled(True)

    report_path = await run_lint(kb_dir)
    return JSONResponse({"report_path": str(report_path) if report_path else None})


async def search_handler(request: Request) -> JSONResponse:
    err = _require_kb(request)
    if err:
        return err
    kb_dir: Path = request.app.state.kb_dir

    pattern = request.query_params.get("q", "")
    if not pattern:
        return JSONResponse({"error": "Missing 'q' parameter"}, status_code=400)

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
                matches.append({"file": rel, "line": i, "text": line.strip()})
        if len(matches) >= 100:
            break

    return JSONResponse({"pattern": pattern, "matches": matches, "count": len(matches)})


async def index_handler(request: Request) -> HTMLResponse:
    from openkb.web import get_index_html
    return HTMLResponse(get_index_html())


async def chat_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    kb_dir = websocket.app.state.kb_dir
    if kb_dir is None:
        await websocket.send_json({"type": "error", "message": "No knowledge base found"})
        await websocket.close()
        return

    from openkb.agent.chat_session import ChatSession
    from openkb.config import load_config, DEFAULT_CONFIG
    from openkb.agent.query import build_query_agent
    import warnings
    warnings.filterwarnings("ignore")
    from agents import set_tracing_disabled, Runner
    set_tracing_disabled(True)

    config = load_config(kb_dir / ".openkb" / "config.yaml")
    model = config.get("model", DEFAULT_CONFIG["model"])
    language = config.get("language", "en")
    wiki_root = str(kb_dir / "wiki")
    session = ChatSession.new(kb_dir, model, language)

    await websocket.send_json({"type": "session", "id": session.id})

    try:
        while True:
            data = await websocket.receive_json()
            msg_type = data.get("type", "message")
            content = data.get("content", "")

            if msg_type == "close":
                break
            if not content:
                continue

            new_input = session.history + [{"role": "user", "content": content}]
            agent = build_query_agent(wiki_root, model, language=language)
            result = await Runner.run(agent, new_input, max_turns=50)

            answer = result.final_output or ""
            session.record_turn(content, answer, result.to_input_list())
            await websocket.send_json({"type": "response", "content": answer})
    except Exception:
        pass
    finally:
        await websocket.close()


routes = [
    Route("/", index_handler),
    Route("/api/status", status_handler),
    Route("/api/list", list_handler),
    Route("/api/read", read_handler),
    Route("/api/query", query_handler, methods=["POST"]),
    Route("/api/add", add_handler, methods=["POST"]),
    Route("/api/lint", lint_handler, methods=["POST"]),
    Route("/api/search", search_handler),
    Route("/ws/chat", chat_ws),
]


def create_app(kb_dir: Path | None = None) -> Starlette:
    middleware = [
        Middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]),
    ]
    app = Starlette(routes=routes, middleware=middleware)
    app.state.kb_dir = kb_dir or _find_kb_dir()
    return app


def run(host: str = "0.0.0.0", port: int = 8000):
    import uvicorn
    kb = _find_kb_dir()
    if kb is None:
        print("No knowledge base found. Set OPENKB_DIR or run `openkb init`.")
        return
    print(f"OpenKB API: http://{host}:{port}")
    print(f"KB: {kb}")
    print(f"WebSocket: ws://{host}:{port}/ws/chat")
    uvicorn.run(create_app(kb), host=host, port=port)
