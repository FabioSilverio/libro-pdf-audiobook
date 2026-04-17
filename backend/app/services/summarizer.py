"""Summarization service.

Two backends available, with graceful degradation:

1. **LLM backend** (preferred when configured) — uses any OpenAI-compatible
   chat-completions API. Set the following env vars to enable:
       OPENAI_API_KEY        required
       OPENAI_BASE_URL       default: https://api.openai.com/v1
                             (also works for Groq / DeepSeek / OpenRouter)
       OPENAI_MODEL          default: gpt-4o-mini
   Produces genuine abstractive summaries that actually feel written,
   rather than a re-ordering of existing sentences.

2. **sumy backend** (always available, no API key needed) — extractive
   LexRank summarizer over cleaned-up text. Better than LSA on noisy PDFs
   because it picks representative sentences rather than a latent-semantic
   average.
"""
from __future__ import annotations

import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

from app.config import settings

logger = logging.getLogger(__name__)

_NLTK_READY = False


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _detect_language(text: str) -> str:
    """Very lightweight language detection (PT vs EN vs ES)."""
    sample = text[:4000].lower()
    pt_hits = sum(sample.count(w) for w in (" de ", " que ", " não ", " para ", " uma ", " com ", " são "))
    en_hits = sum(sample.count(w) for w in (" the ", " and ", " that ", " with ", " from ", " this "))
    es_hits = sum(sample.count(w) for w in (" de ", " que ", " los ", " las ", " para ", " una "))
    best = max(("portuguese", pt_hits), ("english", en_hits), ("spanish", es_hits), key=lambda x: x[1])
    return best[0] if best[1] > 0 else "english"


def _length_to_sentences(length: str) -> int:
    """How many sentences the extractive summarizer should return."""
    return {"short": 4, "medium": 10, "long": 20}.get(length, 10)


def _length_to_words(length: str) -> int:
    """Approximate target word count for the LLM summary."""
    return {"short": 90, "medium": 220, "long": 450}.get(length, 220)


# --- text cleaning for extractive summarization --------------------------

_NUMBER_LINE = re.compile(r"^\s*[\divxIVX\.\-–—:\s]+$")
_ALL_CAPS_SHORT = re.compile(r"^[^a-záéíóúâêîôûãõç]{1,80}$")
_PAGE_NUMBER = re.compile(r"^\s*(page|p\.|pág\.?)?\s*\d{1,4}\s*$", re.IGNORECASE)
_HEADER_FOOTER = re.compile(r"^\s*\d+\s*(\|\s*)?.{0,60}$")

_STRIP_SENT_PREFIX = re.compile(r"^\s*(\d+\.\s*|[IVX]+\.\s*|[A-Z]\)\s*|—\s*|-\s*)")


def _clean_for_summary(text: str) -> str:
    """Pre-process PDF text so the summarizer doesn't latch onto headers,
    page numbers, TOC-style lines, or other visual noise."""
    lines = text.splitlines()
    cleaned: List[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            cleaned.append("")
            continue
        if _PAGE_NUMBER.match(line):
            continue
        if _NUMBER_LINE.match(line) and len(line) < 10:
            continue
        # Short, no punctuation, looks like a header/heading → drop it
        if (
            len(line) < 40
            and not line.endswith((".", "!", "?", ":", ","))
            and line == line.upper()
        ):
            continue
        cleaned.append(line)

    # Join preserving paragraph breaks but collapsing soft wraps.
    joined = "\n".join(cleaned)
    # Collapse multiple blank lines.
    joined = re.sub(r"\n{3,}", "\n\n", joined)
    # Join lines that were visually wrapped mid-sentence (no terminator).
    joined = re.sub(r"(?<![\.\!\?:\"\)])\n(?!\n)", " ", joined)
    # Normalize whitespace.
    joined = re.sub(r"[ \t]+", " ", joined).strip()
    return joined


def _postprocess_sentence(s: str) -> str:
    s = s.strip()
    s = _STRIP_SENT_PREFIX.sub("", s)
    # Collapse hyphenated line breaks ("exem- plo" -> "exemplo")
    s = re.sub(r"(\w+)-\s+(\w+)", r"\1\2", s)
    return s.strip()


# ---------------------------------------------------------------------------
# LLM backend (abstractive, high-quality)
# ---------------------------------------------------------------------------

def _llm_is_configured() -> bool:
    return bool(os.getenv("OPENAI_API_KEY"))


def _llm_call(system: str, user: str, *, max_tokens: int = 900) -> Optional[str]:
    """Call any OpenAI-compatible chat-completions endpoint. Returns None on
    failure so the caller can fall back to the extractive backend."""
    try:
        import httpx
    except Exception as e:
        logger.warning(f"httpx not available for LLM call: {e}")
        return None

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return None
    base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    try:
        r = httpx.post(
            f"{base_url}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "temperature": 0.3,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            },
            timeout=60.0,
        )
        r.raise_for_status()
        payload = r.json()
        return payload["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.warning(f"LLM call failed ({model}): {e}")
        return None


_LLM_SYSTEM_PROMPT = (
    "You are an expert literary analyst. Your job is to produce high-quality, "
    "faithful summaries of book chapters and books. Never invent facts that "
    "aren't supported by the source text. Write in the same language as the "
    "source. Prefer clear, active prose over jargon. Return *only* valid "
    "JSON in the requested schema — no markdown fences, no preamble."
)


def _llm_summarize(text: str, *, length: str, language: str) -> Optional[Dict[str, Any]]:
    """Abstractive summary via LLM. Returns {summary, key_points} or None on failure."""
    word_target = _length_to_words(length)
    # LLM input budget — keep well under typical 16k-context limits.
    snippet = text[:45_000]
    user_prompt = (
        f"Summarize the following text. Target length: about {word_target} words. "
        f"Write in {language}. Then list 4–6 concise, concrete key points "
        f"(each a single sentence capturing a distinct idea — avoid repeating "
        f"the summary). Do NOT include the book's title, author, or metadata "
        f"as key points.\n\n"
        f"Return JSON with this exact shape:\n"
        f'{{"summary": "<string>", "key_points": ["<string>", ...]}}\n\n'
        f"--- TEXT START ---\n{snippet}\n--- TEXT END ---"
    )

    raw = _llm_call(_LLM_SYSTEM_PROMPT, user_prompt, max_tokens=1200)
    if not raw:
        return None

    # Strip accidental code fences.
    raw = raw.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw)
        raw = re.sub(r"\s*```$", "", raw)

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        # Try to locate the first JSON object in the string.
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if not m:
            logger.warning("LLM returned non-JSON output; falling back")
            return None
        try:
            data = json.loads(m.group(0))
        except Exception:
            return None

    summary = (data.get("summary") or "").strip()
    kp_raw = data.get("key_points") or []
    key_points = [str(x).strip().rstrip(".") + "." for x in kp_raw if str(x).strip()][:6]
    if not summary:
        return None
    return {"summary": summary, "key_points": key_points, "language": language}


# ---------------------------------------------------------------------------
# Extractive backend (LexRank via sumy, always available)
# ---------------------------------------------------------------------------

def _sumy_lexrank(text: str, sentence_count: int, language: str) -> List[str]:
    """Return N representative sentences using LexRank."""
    _ensure_nltk()
    from sumy.parsers.plaintext import PlaintextParser
    from sumy.nlp.tokenizers import Tokenizer
    from sumy.summarizers.lex_rank import LexRankSummarizer
    from sumy.nlp.stemmers import Stemmer
    from sumy.utils import get_stop_words

    for lang in (language, "english"):
        try:
            parser = PlaintextParser.from_string(text, Tokenizer(lang))
            stemmer = Stemmer(lang)
            summarizer = LexRankSummarizer(stemmer)
            try:
                summarizer.stop_words = get_stop_words(lang)
            except Exception:
                pass
            sentences = summarizer(parser.document, sentence_count)
            out = [str(s).strip() for s in sentences if str(s).strip()]
            if out:
                return out
        except Exception as e:
            logger.debug(f"lexrank lang={lang} failed: {e}")
            continue

    # Naive fallback: first N sentences.
    parts = re.split(r"(?<=[\.\!\?])\s+", text)
    return [p.strip() for p in parts[:sentence_count] if p.strip()]


def _extractive_summarize(text: str, length: str, language: str) -> Dict[str, Any]:
    cleaned = _clean_for_summary(text)
    if not cleaned or len(cleaned) < 200:
        return {"summary": cleaned.strip(), "key_points": [], "language": language}

    n_summary = _length_to_sentences(length)
    # Ask for a bigger pool so we can split summary vs key_points.
    pool_size = max(n_summary + 6, 10)
    pool = _sumy_lexrank(cleaned, pool_size, language)
    pool = [_postprocess_sentence(s) for s in pool if len(s.split()) >= 4]

    summary_sents = pool[:n_summary]
    used = {s.lower()[:80] for s in summary_sents}
    # Key points: pick sentences that don't overlap with the summary and look
    # like complete, concrete ideas (6-40 words).
    kp: List[str] = []
    for s in pool[n_summary:]:
        key = s.lower()[:80]
        if key in used:
            continue
        words = s.split()
        if not (6 <= len(words) <= 40):
            continue
        kp.append(s)
        used.add(key)
        if len(kp) >= 5:
            break

    # If we couldn't find distinct ones, fall back to slicing the summary itself.
    if not kp and summary_sents:
        kp = [s for s in summary_sents if 6 <= len(s.split()) <= 40][:4]

    return {
        "summary": " ".join(summary_sents).strip(),
        "key_points": kp,
        "language": language,
    }


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def _sample_long_text(text: str, max_chars: int = 40_000) -> str:
    """For very long texts, take representative slices from beginning, middle,
    and end. Prevents the summarizer from drowning in filler material."""
    if len(text) <= max_chars:
        return text
    third = max_chars // 3
    middle_start = len(text) // 2 - third // 2
    return (
        text[:third]
        + "\n\n[...]\n\n"
        + text[middle_start:middle_start + third]
        + "\n\n[...]\n\n"
        + text[-third:]
    )


def summarize_sync(text: str, length: str = "medium", language: str = "auto") -> Dict[str, Any]:
    """Summarize a chunk of text. Uses LLM if configured, else extractive."""
    if not text or len(text.strip()) < 100:
        return {"summary": text.strip(), "key_points": [], "language": language}

    lang = language
    if lang == "auto" or not lang:
        lang = _detect_language(text)

    # Keep summarizer input bounded; sample from long texts.
    text = _sample_long_text(text, max_chars=40_000)

    if _llm_is_configured():
        res = _llm_summarize(text, length=length, language=lang)
        if res is not None:
            return res
        logger.info("LLM summarization failed; falling back to LexRank.")

    try:
        return _extractive_summarize(text, length, lang)
    except Exception as e:
        logger.warning(f"Extractive summarize failed: {e}")
        n = _length_to_sentences(length)
        parts = re.split(r"(?<=[\.\!\?])\s+", text)
        return {
            "summary": " ".join(parts[:n]).strip(),
            "key_points": [],
            "language": lang,
        }


async def summarize(text: str, length: str = "medium", language: str = "auto") -> Dict[str, Any]:
    """Async wrapper that runs the CPU-bound summarizer in a thread."""
    import asyncio
    return await asyncio.to_thread(summarize_sync, text, length, language)


async def generate_chapter_summaries(
    chapters: List[Dict[str, Any]] | List[str],
    length: str = "medium",
    language: str = "auto",
) -> List[Dict[str, Any]]:
    """Summarize each chapter. Accepts dicts with 'title'/'text' or plain strings."""
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
            "full_text": text,
        })
    return results
