"""EPUB text extraction and processing service.

EPUBs are ZIP archives containing XHTML content — no OCR needed.
This module mirrors the pdf_processor interface so the task manager
can treat both formats identically.
"""
import logging
import re
from pathlib import Path
from typing import Any, Dict, List

import ebooklib
from ebooklib import epub
from bs4 import BeautifulSoup, Tag

from app.core.exceptions import PDFProcessingError, EmptyPDFError
from app.services.pdf_processor import clean_text

logger = logging.getLogger(__name__)

# Minimum text length per spine item to be considered a real chapter
# (filters out cover pages, copyright notices, etc.)
_MIN_CHAPTER_CHARS = 200


def _spine_html_items(book: epub.EpubBook):
    """Yield each spine item that is an HTML document, in *reading* order.

    ``get_items_of_type(ITEM_DOCUMENT)`` follows manifest order, which is often
    **not** the book's linear reading order (commonly close to filename sort).
    The EPUB ``<spine>`` defines the real sequence; without it, chapters can
    look shuffled and titles may repeat in illogical order.
    """
    for spine_entry in book.spine:
        if not spine_entry:
            continue
        # ebooklib: spine is [(idref, linear), ...] — see EpubReader._load_spine
        item_id = spine_entry[0] if isinstance(spine_entry, (list, tuple)) else spine_entry
        item = book.get_item_with_id(item_id)
        if item is None:
            continue
        if item.get_type() != ebooklib.ITEM_DOCUMENT:
            continue
        yield item


# ---------------------------------------------------------------------------
# Public API (mirrors pdf_processor)
# ---------------------------------------------------------------------------

def extract_text(epub_path: str, *, on_progress=None, **_kw) -> str:
    """Extract all text from an EPUB file.

    Args:
        epub_path: Path to the .epub file.
        on_progress: Optional ``fn(stage, done, total, message)`` callback.

    Returns:
        Full extracted text.

    Raises:
        PDFProcessingError / EmptyPDFError on failure.
    """
    try:
        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
    except Exception as e:
        raise PDFProcessingError(f"Failed to read EPUB: {e}")

    items = list(_spine_html_items(book))
    total = len(items)
    if total == 0:
        raise EmptyPDFError()

    if on_progress:
        try:
            on_progress("extracting", 0, total, f"Reading EPUB ({total} spine sections)")
        except Exception:
            pass

    text_parts: List[str] = []
    for idx, item in enumerate(items):
        try:
            html = item.get_content().decode("utf-8", errors="replace")
            soup = BeautifulSoup(html, "lxml")
            # Remove script/style noise
            for tag in soup(["script", "style", "svg"]):
                tag.decompose()
            txt = soup.get_text(separator="\n", strip=True)
            if txt:
                text_parts.append(txt)
        except Exception as e:
            logger.warning(f"EPUB item {idx} extraction failed: {e}")

        if on_progress and (idx % 5 == 0 or idx == total - 1):
            try:
                on_progress("extracting", idx + 1, total,
                            f"Reading section {idx + 1}/{total}")
            except Exception:
                pass

    full_text = "\n\n".join(text_parts)
    cleaned = clean_text(full_text)

    if not cleaned or len(cleaned.strip()) < 10:
        raise EmptyPDFError()

    logger.info(f"Extracted {len(cleaned)} chars from EPUB ({total} items)")
    return cleaned


def extract_metadata(epub_path: str) -> Dict[str, Any]:
    """Extract metadata from an EPUB file."""
    metadata: Dict[str, Any] = {
        "title": None,
        "author": None,
        "page_count": 0,
    }
    try:
        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        # Title
        titles = book.get_metadata("DC", "title")
        if titles:
            metadata["title"] = titles[0][0]
        # Author
        creators = book.get_metadata("DC", "creator")
        if creators:
            metadata["author"] = creators[0][0]
        # "page_count" → use number of spine items as a proxy
        metadata["page_count"] = len(list(_spine_html_items(book)))
    except Exception as e:
        logger.warning(f"EPUB metadata extraction failed: {e}")
    return metadata


def split_into_chapters(epub_path: str, full_text: str) -> List[Dict[str, Any]]:
    """Split EPUB into chapters using its internal spine/TOC.

    Falls back to the generic regex splitter in pdf_processor when
    the EPUB has no usable structure.
    """
    chapters: List[Dict[str, Any]] = []

    try:
        book = epub.read_epub(epub_path, options={"ignore_ncx": True})
        toc_titles = _extract_toc_titles(book)
        items = list(_spine_html_items(book))
        logger.info("EPUB chapter split: %d spine item(s) in reading order", len(items))

        for idx, item in enumerate(items):
            try:
                html = item.get_content().decode("utf-8", errors="replace")
                soup = BeautifulSoup(html, "lxml")
                for tag in soup(["script", "style", "svg"]):
                    tag.decompose()
                txt = soup.get_text(separator="\n", strip=True)
            except Exception:
                continue

            if not txt or len(txt) < _MIN_CHAPTER_CHARS:
                continue

            # Try to find a title: first from TOC map, then from <title> or
            # first heading in the HTML.
            item_name = Path(item.get_name()).stem
            title = (
                toc_titles.get(item.get_name())
                or toc_titles.get(item_name)
                or _title_from_html(soup)
                or f"Chapter {len(chapters) + 1}"
            )

            chapters.append({"title": title.strip(), "text": clean_text(txt)})
    except Exception as e:
        logger.warning(f"EPUB chapter split failed: {e}")

    if chapters:
        return chapters

    # Fallback — use the same regex-based splitter as PDF.
    from app.services.pdf_processor import split_into_chapters as pdf_split
    return pdf_split(full_text)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _extract_toc_titles(book: epub.EpubBook) -> Dict[str, str]:
    """Build a mapping of spine-item filename → TOC title."""
    mapping: Dict[str, str] = {}

    def _walk_toc(toc_items):
        for item in toc_items:
            if isinstance(item, tuple):
                # Nested: (section, [children])
                section, children = item
                if hasattr(section, "href") and hasattr(section, "title"):
                    href = section.href.split("#")[0]
                    if section.title:
                        mapping[href] = section.title
                        mapping[Path(href).stem] = section.title
                _walk_toc(children)
            elif hasattr(item, "href") and hasattr(item, "title"):
                href = item.href.split("#")[0]
                if item.title:
                    mapping[href] = item.title
                    mapping[Path(href).stem] = item.title

    try:
        _walk_toc(book.toc)
    except Exception as e:
        logger.debug(f"TOC walk failed: {e}")
    return mapping


def _title_from_html(soup: BeautifulSoup) -> str | None:
    """Try to pull a chapter title from the HTML content."""
    # 1) <title> tag
    if soup.title and soup.title.string:
        t = soup.title.string.strip()
        if t and len(t) < 120:
            return t
    # 2) First heading (h1-h3)
    for level in ("h1", "h2", "h3"):
        h = soup.find(level)
        if h:
            t = h.get_text(strip=True)
            if t and len(t) < 120:
                return t
    return None
