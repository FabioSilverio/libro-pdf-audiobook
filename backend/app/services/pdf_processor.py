"""PDF text extraction and processing service."""
import pdfplumber
from typing import Dict, Any, List
from pathlib import Path
import re
import logging
import shutil

from app.core.exceptions import PDFProcessingError, EncryptedPDFError, EmptyPDFError

logger = logging.getLogger(__name__)

# OCR configuration
OCR_LANGS = "por+eng+spa"  # combine common languages
OCR_DPI = 200
OCR_MIN_CHARS_PER_PAGE = 40  # below this, treat as scanned and OCR
OCR_MAX_PAGES = 2000  # hard cap to avoid running OCR forever


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

        page_count = 0
        with pdf_ctx as pdf:
            page_count = len(pdf.pages)
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
        cleaned_text = clean_text(full_text)

        # Decide whether we need OCR: either nothing came out, or way too little
        # per page (likely a scanned PDF).
        chars_per_page = len(cleaned_text) / max(page_count, 1)
        if not cleaned_text or chars_per_page < OCR_MIN_CHARS_PER_PAGE:
            if _ocr_available():
                logger.info(
                    f"Text extraction sparse ({len(cleaned_text)} chars over "
                    f"{page_count} pages). Falling back to OCR."
                )
                ocr_text = _ocr_pdf(pdf_path)
                ocr_cleaned = clean_text(ocr_text)
                if ocr_cleaned and len(ocr_cleaned) > len(cleaned_text):
                    cleaned_text = ocr_cleaned
            else:
                logger.warning("Sparse text and OCR not available on this host.")

        if not cleaned_text or len(cleaned_text.strip()) < 10:
            raise EmptyPDFError()

        logger.info(f"Extracted {len(cleaned_text)} characters from PDF")
        return cleaned_text

    except EncryptedPDFError:
        raise
    except EmptyPDFError:
        raise
    except Exception as e:
        logger.error(f"PDF extraction failed: {e}")
        raise PDFProcessingError(f"Failed to extract text: {str(e)}")


def _ocr_available() -> bool:
    """Check if OCR stack is available (tesseract + poppler + python libs)."""
    try:
        import pytesseract  # noqa: F401
        import pdf2image  # noqa: F401
    except Exception as e:
        logger.info(f"OCR python libs missing: {e}")
        return False
    if not shutil.which("tesseract"):
        logger.info("tesseract binary not found in PATH")
        return False
    # pdf2image requires pdftoppm from poppler
    if not shutil.which("pdftoppm"):
        logger.info("pdftoppm (poppler) not found in PATH")
        return False
    return True


def _ocr_pdf(pdf_path: str) -> str:
    """Run Tesseract OCR over every page of the PDF.

    Converts each page to an image via pdf2image (poppler) then extracts text.
    This is slow — expect seconds per page.
    """
    import pytesseract
    from pdf2image import convert_from_path

    texts: List[str] = []
    # Process in batches to keep memory bounded.
    batch = 5
    page = 1
    while page <= OCR_MAX_PAGES:
        try:
            images = convert_from_path(
                pdf_path,
                dpi=OCR_DPI,
                first_page=page,
                last_page=page + batch - 1,
                fmt="png",
                thread_count=2,
            )
        except Exception as e:
            logger.warning(f"pdf2image failed at page {page}: {e}")
            break

        if not images:
            break

        for i, img in enumerate(images):
            try:
                text = pytesseract.image_to_string(img, lang=OCR_LANGS)
                if text:
                    texts.append(text)
            except Exception as e:
                logger.warning(f"OCR failed at page {page + i}: {e}")
            finally:
                try:
                    img.close()
                except Exception:
                    pass

        if len(images) < batch:
            break
        page += batch

    result = "\n\n".join(texts)
    logger.info(f"OCR produced {len(result)} characters across {page - 1} pages")
    return result


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

    # Fallback: always split long texts into ~N parts so TTS/progress stay responsive.
    # Aim for parts of ~8k chars (~5-10 min of audio each).
    if len(text) > 8000:
        target_size = 8000
        target = max(2, min(40, -(-len(text) // target_size)))  # ceil
        size = -(-len(text) // target)
        parts = []
        for i in range(target):
            chunk = text[i * size:(i + 1) * size]
            if chunk.strip():
                parts.append({"title": f"Part {i + 1}", "text": chunk.strip()})
        return parts or [{"title": "Full Text", "text": text}]

    return [{"title": "Full Text", "text": text}]
