"""Document conversion pipeline for OpenKB."""
from __future__ import annotations

import logging
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf
from markitdown import MarkItDown

from openkb.config import load_config
from openkb.images import copy_relative_images, extract_base64_images, convert_pdf_with_images
from openkb.state import HashRegistry

logger = logging.getLogger(__name__)


@dataclass
class ConvertResult:
    """Result returned by :func:`convert_document`."""

    raw_path: Path | None = None
    source_path: Path | None = None
    is_long_doc: bool = False
    long_doc_type: str = ""  # "pageindex" for PDF, "chunked" for non-PDF
    skipped: bool = False
    file_hash: str | None = None  # For deferred hash registration


def get_pdf_page_count(path: Path) -> int:
    """Return the number of pages in the PDF at *path* using pymupdf."""
    with pymupdf.open(str(path)) as doc:
        return doc.page_count


def convert_document(src: Path, kb_dir: Path, subpath: str = "") -> ConvertResult:
    """Convert a document and integrate it into the knowledge base.

    Steps:
    1. Hash-check — skip if already known.
    2. Copy source to ``raw/`` (preserving subpath structure).
    3. If PDF and page count >= threshold → return :attr:`ConvertResult.is_long_doc`.
    4. If non-PDF and large after conversion → chunk into pseudo-pages.
    5. If ``.md`` — read, process relative images, save to ``wiki/sources/``.
    6. Otherwise — run MarkItDown, extract base64 images, save to ``wiki/sources/``.
    """
    openkb_dir = kb_dir / ".openkb"
    config = load_config(openkb_dir / "config.yaml")
    threshold: int = config.get("pageindex_threshold", 20)
    text_threshold: int = config.get("large_doc_char_threshold", 40000)
    registry = HashRegistry(openkb_dir / "hashes.json")

    file_hash = HashRegistry.hash_file(src)
    if registry.is_known(file_hash):
        logger.info("Skipping already-known file: %s", src.name)
        return ConvertResult(skipped=True)

    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    if subpath:
        raw_dest = raw_dir / subpath / src.name
    else:
        raw_dest = raw_dir / src.name

    raw_dest.parent.mkdir(parents=True, exist_ok=True)
    if raw_dest.resolve() != src.resolve():
        shutil.copy2(src, raw_dest)

    doc_name = src.stem
    if subpath:
        doc_name = subpath.replace("/", "-") + "-" + doc_name

    if src.suffix.lower() == ".pdf":
        page_count = get_pdf_page_count(src)
        if page_count >= threshold:
            logger.info(
                "Long PDF detected (%d pages >= %d threshold): %s",
                page_count, threshold, src.name,
            )
            return ConvertResult(raw_path=raw_dest, is_long_doc=True, long_doc_type="pageindex", file_hash=file_hash)

    sources_dir = kb_dir / "wiki" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)
    images_dir = kb_dir / "wiki" / "sources" / "images" / doc_name
    images_dir.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() == ".md":
        markdown = src.read_text(encoding="utf-8")
        markdown = copy_relative_images(markdown, src.parent, doc_name, images_dir)
    elif src.suffix.lower() == ".pdf":
        markdown = convert_pdf_with_images(src, doc_name, images_dir)
    else:
        mid = MarkItDown()
        result = mid.convert(str(src))
        markdown = result.text_content
        markdown = extract_base64_images(markdown, doc_name, images_dir)

    from openkb.large_doc import is_large_markdown, write_large_doc_pages

    if is_large_markdown(markdown, text_threshold):
        logger.info("Large non-PDF detected (%d chars >= %d): %s", len(markdown), text_threshold, src.name)
        write_large_doc_pages(markdown, doc_name, images_dir, kb_dir)

        dest_md = sources_dir / f"{doc_name}.md"
        dest_md.write_text(markdown, encoding="utf-8")
        return ConvertResult(raw_path=raw_dest, source_path=dest_md, is_long_doc=True, long_doc_type="chunked", file_hash=file_hash)

    dest_md = sources_dir / f"{doc_name}.md"
    dest_md.write_text(markdown, encoding="utf-8")

    return ConvertResult(raw_path=raw_dest, source_path=dest_md, file_hash=file_hash)
