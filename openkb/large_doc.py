"""Non-PDF large document handler.

For documents that aren't PDF but exceed the LLM context limit after
conversion to markdown, they are chunked into pseudo-pages and stored
as JSON arrays (same format as PageIndex output) so the query agent can
do targeted page retrieval.
"""
from __future__ import annotations

import json
from pathlib import Path

CHUNK_SIZE_CHARS = 8000
LARGE_DOC_CHAR_THRESHOLD = 40000


def is_large_markdown(text: str, threshold: int = LARGE_DOC_CHAR_THRESHOLD) -> bool:
    """Check if markdown text is too large for LLM context."""
    return len(text) > threshold


def chunk_markdown(text: str, chunk_size: int = CHUNK_SIZE_CHARS) -> list[str]:
    """Split markdown into chunks at paragraph boundaries.

    Tries to break at paragraph boundaries (double newline). Falls back
    to sentence boundaries (period + space), then character count.
    """
    chunks: list[str] = []
    paragraphs = text.split("\n\n")

    current = ""
    for para in paragraphs:
        if len(current) + len(para) < chunk_size:
            current = current + "\n\n" + para if current else para
        else:
            if current:
                chunks.append(current)
            # If a single paragraph is still too large, split by sentences
            if len(para) > chunk_size:
                sentences = para.replace(". ", ".\n").split("\n")
                sub_current = ""
                for sent in sentences:
                    if len(sub_current) + len(sent) < chunk_size:
                        sub_current = sub_current + " " + sent if sub_current else sent
                    else:
                        if sub_current:
                            chunks.append(sub_current)
                        sub_current = sent
                if sub_current:
                    current = sub_current
            else:
                current = para

    if current:
        chunks.append(current)

    return chunks


def build_fake_tree(chunks: list[str], doc_name: str) -> dict:
    """Build a minimal tree structure mimicking PageIndex output.

    Each chunk becomes a pseudo-section in the tree, with page ranges
    mapping 1:1 to chunk indices.
    """
    structure = []
    for i, chunk in enumerate(chunks):
        title = chunk.strip().split("\n")[0].lstrip("#").strip()[:80] or f"Section {i + 1}"
        structure.append({
            "title": title,
            "page_range": (i + 1, i + 1),
            "children": [],
            "summary": chunk[:500] + ("..." if len(chunk) > 500 else ""),
        })

    return {
        "doc_name": doc_name,
        "doc_description": f"Large document split into {len(chunks)} chunks",
        "structure": structure,
    }


def write_large_doc_pages(
    text: str,
    doc_name: str,
    images_dir: Path,
    kb_dir: Path,
) -> int:
    """Chunk a large markdown document and write as JSON pages.

    Args:
        text: Full markdown content.
        doc_name: Document stem name.
        images_dir: Directory for extracted images.
        kb_dir: Knowledge base root.

    Returns:
        Number of chunks (pages) created.
    """
    from openkb.images import extract_base64_images, copy_relative_images

    text = extract_base64_images(text, doc_name, images_dir)
    chunks = chunk_markdown(text)

    pages = []
    for i, chunk in enumerate(chunks):
        pages.append({
            "page": i + 1,
            "content": chunk,
            "images": [],
        })

    sources_dir = kb_dir / "wiki" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    json_path = sources_dir / f"{doc_name}.json"
    json_path.write_text(json.dumps(pages, ensure_ascii=False, indent=2), encoding="utf-8")

    return len(pages)


def index_large_nonpdf(
    doc_name: str,
    source_path: Path,
    kb_dir: Path,
) -> dict:
    """Create summary and tree for a large non-PDF document.

    Args:
        doc_name: Document stem name.
        source_path: Path to the markdown source file.
        kb_dir: Knowledge base root.

    Returns:
        dict with 'doc_id', 'description', 'tree' keys.
    """
    from openkb.tree_renderer import render_summary_md

    text = source_path.read_text(encoding="utf-8")
    chunks = chunk_markdown(text)

    tree = build_fake_tree(chunks, doc_name)
    doc_id = f"chunked-{doc_name}"

    summaries_dir = kb_dir / "wiki" / "summaries"
    summaries_dir.mkdir(parents=True, exist_ok=True)
    summary_md = render_summary_md(tree, doc_name, doc_id)
    (summaries_dir / f"{doc_name}.md").write_text(summary_md, encoding="utf-8")

    return {
        "doc_id": doc_id,
        "description": f"Large document ({len(chunks)} sections)",
        "tree": tree,
    }
