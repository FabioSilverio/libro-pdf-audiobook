"""Language-agnostic summarization service.

Primary backend: sumy (extractive, offline, no API key, any language).
Optional backend: HuggingFace Inference API (English only, no key for public models,
but may be rate-limited).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List

from app.config import settings

logger = logging.getLogger(__name__)

# Keep sumy imports lazy so startup is fast and the backend tolerates missing extras.
_SUMY_READY = False
_NLTK_READY = False


def _ensure_nltk() -> None:
    global _NLTK_READY
    if _NLTK_READY:
        return
    try:
        import nltk

        for pkg in ("punkt", "punkt_tab"):
            try:
                nltk.data.find(f"tokenizers/{pkg}")
            except LookupError:
                try:
                    nltk.download(pkg, quiet=True)
                except Exception as e:  # pragma: no cover - network failure
                    logger.warning(f"nltk download {pkg} failed: {e}")
        _NLTK_READY = True
    except Exception as e:  # pragma: no cover
        logger.warning(f"nltk init failed: {e}")


def _sumy_summarize(text: str, sentence_count: int, language: str = "portuguese") -> str:
    """Run sumy LSA summarizer with a graceful language fallback."""
    _ensure_nltk()
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.lsa import LsaSummarizer
    from sumy.nlp.stemmers import Stemmer
    from sumy.utils import get_stop_words

    # Try requested language, fall back to english, then tokenize naively.
    for lang in (language, "english"):
        try:
            parser = PlaintextParser.from_string(text, Tokenizer(lang))
            stemmer = Stemmer(lang)
            summarizer = LsaSummarizer(stemmer)
            try:
                summarizer.stop_words = get_stop_words(lang)
            except Exception:
                pass
            sentences = summarizer(parser.document, sentence_count)
            out = " ".join(str(s) for s in sentences).strip()
            if out:
                return out
        except Exception as e:
            logger.debug(f"sumy lang={lang} failed: {e}")
            continue

    # Last-resort: first N sentences.
    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    return " ".join(parts[:sentence_count]).strip()


def _detect_language(text: str) -> str:
    """Very lightweight language detection (PT vs EN vs ES)."""
    sample = text[:4000].lower()
    pt_hits = sum(sample.count(w) for w in (" de ", " que ", " não ", " para ", " uma ", " com ", " são "))
    en_hits = sum(sample.count(w) for w in (" the ", " and ", " that ", " with ", " from ", " this "))
    es_hits = sum(sample.count(w) for w in (" de ", " que ", " los ", " las ", " para ", " una "))
    best = max(("portuguese", pt_hits), ("english", en_hits), ("spanish", es_hits), key=lambda x: x[1])
    return best[0] if best[1] > 0 else "english"


def _length_to_sentences(length: str) -> int:
    # Sentences in the *per-chapter* / overall summary. Sumy trims to available.
    return {"short": 4, "medium": 10, "long": 20}.get(length, 10)


def summarize_sync(text: str, length: str = "medium", language: str = "auto") -> Dict[str, Any]:
    """Synchronous summarization using sumy. Safe to call inside threads."""
    if not text or len(text.strip()) < 100:
        return {"summary": text.strip(), "key_points": []}

    lang = language
    if lang == "auto" or not lang:
        lang = _detect_language(text)

    n = _length_to_sentences(length)

    try:
        summary = _sumy_summarize(text, sentence_count=n, language=lang)
    except Exception as e:
        logger.warning(f"sumy summarize failed, using naive fallback: {e}")
        summary = " ".join(re.split(r"(?<=[\.\!\?])\s+", text)[:n])

    # Key points: shorter extractive pass.
    try:
        key_raw = _sumy_summarize(text, sentence_count=5, language=lang)
        key_points = [s.strip() for s in re.split(r"(?<=[\.\!\?])\s+", key_raw) if s.strip()]
    except Exception:
        key_points = []

    return {"summary": summary, "key_points": key_points[:5], "language": lang}


async def summarize(text: str, length: str = "medium", language: str = "auto") -> Dict[str, Any]:
    """Async wrapper that runs the CPU-bound summarizer in a thread."""
    import asyncio

    return await asyncio.to_thread(summarize_sync, text, length, language)


async def generate_chapter_summaries(
    chapters: List[Dict[str, Any]] | List[str],
    length: str = "short",
    language: str = "auto",
) -> List[Dict[str, Any]]:
    """Summarize each chapter. Accepts list of dicts (with 'title'/'text') or plain strings."""
    results: List[Dict[str, Any]] = []
    for i, ch in enumerate(chapters):
        if isinstance(ch, dict):
            title = ch.get("title") or f"Chapter {i + 1}"
            text = ch.get("text", "")
        else:
            title = f"Chapter {i + 1}"
            text = ch

        if not text or len(text.strip()) < 200:
            summary = text.strip()
            key_points: List[str] = []
        else:
            res = await summarize(text, length=length, language=language)
            summary = res["summary"]
            key_points = res.get("key_points", [])[:5]

        results.append({
            "chapter_number": i + 1,
            "title": title,
            "summary": summary,
            "key_points": key_points,
            "full_text": text,  # UI lets the user expand to read the whole chapter
        })
    return results
