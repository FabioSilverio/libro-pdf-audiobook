"""PDF text extraction and processing service."""
import pdfplumber
from typing import Dict, Any, List
from pathlib import Path
import re
import logging

from app.core.exceptions import PDFProcessingError, EncryptedPDFError, EmptyPDFError

logger = logging.getLogger(__name__)


def extract_text(pdf_path: str) -> str:
    """Extract all text from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Extracted text content

    Raises:
        PDFProcessingError: If PDF cannot be read
        EncryptedPDFError: If PDF is password protected
        EmptyPDFError: If no text is found
    """
    try:
        text_parts = []

        try:
            pdf_ctx = pdfplumber.open(pdf_path)
        except Exception as e:
            msg = str(e).lower()
            if "encrypt" in msg or "password" in msg:
                raise EncryptedPDFError()
            raise

        with pdf_ctx as pdf:
            # Extract text from each page
            for page_num, page in enumerate(pdf.pages, 1):
                try:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
                except Exception as e:
                    logger.warning(f"Failed to extract text from page {page_num}: {e}")
                    continue

        # Combine all text
        full_text = "\n\n".join(text_parts)

        # Clean and normalize text
        cleaned_text = clean_text(full_text)

        # Verify we extracted something
        if not cleaned_text or len(cleaned_text.strip()) < 10:
            raise EmptyPDFError()

        logger.info(f"Successfully extracted {len(cleaned_text)} characters from PDF")
        return cleaned_text

    except EncryptedPDFError:
        raise
    except EmptyPDFError:
        raise
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise PDFProcessingError(f"Failed to extract text: {str(e)}")


def extract_metadata(pdf_path: str) -> Dict[str, Any]:
    """Extract metadata from a PDF file.

    Args:
        pdf_path: Path to the PDF file

    Returns:
        Dictionary containing metadata (title, author, page_count)
    """
    metadata = {
        "title": None,
        "author": None,
        "page_count": 0
    }

    try:
        with pdfplumber.open(pdf_path) as pdf:
            # Get page count
            metadata["page_count"] = len(pdf.pages)

            # Try to extract metadata from PDF info
            if pdf.metadata:
                metadata["title"] = pdf.metadata.get("Title")
                metadata["author"] = pdf.metadata.get("Author")

            # If no title in metadata, try to infer from first page
            if not metadata["title"] and pdf.pages:
                first_page_text = pdf.pages[0].extract_text()
                if first_page_text:
                    # Take first non-empty line as potential title
                    lines = [line.strip() for line in first_page_text.split("\n") if line.strip()]
                    if lines:
                        metadata["title"] = lines[0][:100]  # Limit length

    except Exception as e:
        logger.warning(f"Failed to extract metadata: {e}")

    return metadata


def clean_text(text: str) -> str:
    """Clean and normalize extracted text.

    Removes artifacts, fixes encoding issues, normalizes whitespace.

    Args:
        text: Raw extracted text

    Returns:
        Cleaned text
    """
    if not text:
        return ""

    # Replace multiple newlines with double newline
    text = re.sub(r'\n{3,}', '\n\n', text)

    # Remove excessive spaces
    text = re.sub(r' {2,}', ' ', text)

    # Remove common PDF artifacts
    text = text.replace('\ufeff', '')  # BOM character
    text = text.replace('\xad', '')   # Soft hyphen

    # Fix common encoding issues
    text = text.replace('â€"', '"')
    text = text.replace('â€"', '"')
    text = text.replace('â€™', "'")
    text = text.replace('â€"', '—')

    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # Strip leading/trailing whitespace
    text = text.strip()

    return text


def split_into_chapters(text: str) -> List[Dict[str, Any]]:
    """Detect and split text into chapters with titles.

    Returns a list of {"title": str, "text": str}. Always returns at least one chapter.
    If no chapter markers are found for long texts, splits into roughly equal parts.
    """
    # Multilingual chapter heading patterns (EN, PT, ES)
    patterns = [
        r'(?im)^\s*(Chapter\s+\d+[^\n]{0,80})$',
        r'(?im)^\s*(CHAPTER\s+[IVXLCDM]+[^\n]{0,80})$',
        r'(?im)^\s*(Cap[ií]tulo\s+\d+[^\n]{0,80})$',
        r'(?im)^\s*(Cap[ií]tulo\s+[IVXLCDM]+[^\n]{0,80})$',
        r'(?im)^\s*(CAP[IÍ]TULO\s+\d+[^\n]{0,80})$',
        r'(?m)^\s*(\d{1,3}\.\s+[A-ZÁÉÍÓÚÂÊÔÀÃÕÇ][^\n]{3,80})$',
    ]

    best_matches: List[re.Match] = []
    for pat in patterns:
        matches = list(re.finditer(pat, text))
        if len(matches) >= 2 and len(matches) > len(best_matches):
            best_matches = matches

    chapters: List[Dict[str, Any]] = []
    if best_matches:
        for i, m in enumerate(best_matches):
            start = m.start()
            end = best_matches[i + 1].start() if i + 1 < len(best_matches) else len(text)
            title = m.group(1).strip()
            body = text[start:end].strip()
            # strip the repeated title from body start
            body = re.sub(r'^' + re.escape(title) + r'\s*', '', body).strip()
            if body:
                chapters.append({"title": title, "text": body})

    if chapters:
        return chapters

    # Fallback: split long texts into ~N parts of ~15k chars each.
    if len(text) > 20000:
        target = max(1, min(20, len(text) // 15000))
        size = len(text) // target
        parts = []
        for i in range(target):
            chunk = text[i * size:(i + 1) * size if i < target - 1 else len(text)]
            parts.append({"title": f"Part {i + 1}", "text": chunk.strip()})
        return parts

    return [{"title": "Full Text", "text": text}]
