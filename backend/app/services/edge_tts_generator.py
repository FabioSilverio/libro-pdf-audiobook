"""Audiobook generation using Microsoft Edge Neural TTS (edge-tts).

Free, no API key, high quality. Supports many languages including pt-BR, en-US, es-ES.
"""
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Callable, List, Optional

logger = logging.getLogger(__name__)

# Curated voice list (language -> (voice_id, display name))
VOICES = {
    "pt-BR": [
        ("pt-BR-AntonioNeural", "Antônio (masc.)"),
        ("pt-BR-FranciscaNeural", "Francisca (fem.)"),
        ("pt-BR-ThalitaNeural", "Thalita (fem.)"),
    ],
    "en-US": [
        ("en-US-AriaNeural", "Aria (fem.)"),
        ("en-US-GuyNeural", "Guy (masc.)"),
        ("en-US-JennyNeural", "Jenny (fem.)"),
    ],
    "es-ES": [
        ("es-ES-AlvaroNeural", "Álvaro (masc.)"),
        ("es-ES-ElviraNeural", "Elvira (fem.)"),
    ],
}

# Edge-TTS has a ~10 min per request limit. We split long text into chunks.
# Characters per chunk — keep under ~5000 to be safe.
CHUNK_CHARS = 4500


def list_voices() -> List[dict]:
    out = []
    for locale, voices in VOICES.items():
        for vid, name in voices:
            out.append({"id": vid, "name": name, "locale": locale})
    return out


def detect_voice_for_language(language: str) -> str:
    """Pick a default voice id for a given detected language."""
    mapping = {
        "portuguese": "pt-BR-AntonioNeural",
        "english": "en-US-AriaNeural",
        "spanish": "es-ES-ElviraNeural",
    }
    return mapping.get(language, "pt-BR-AntonioNeural")


def _chunk_text(text: str, max_chars: int = CHUNK_CHARS) -> List[str]:
    """Split text into chunks at sentence boundaries under `max_chars`."""
    text = text.strip()
    if not text:
        return []

    sentences = re.split(r"(?<=[\.\!\?])\s+", text)
    chunks: List[str] = []
    buf = ""
    for s in sentences:
        if not s:
            continue
        if len(buf) + len(s) + 1 > max_chars and buf:
            chunks.append(buf.strip())
            buf = s
        else:
            buf = (buf + " " + s).strip() if buf else s
    if buf:
        chunks.append(buf.strip())

    # Safety: if any chunk is still too large (no sentence boundaries), hard-split.
    final: List[str] = []
    for c in chunks:
        if len(c) <= max_chars:
            final.append(c)
        else:
            for i in range(0, len(c), max_chars):
                final.append(c[i:i + max_chars])
    return final


async def synthesize_to_file(
    text: str,
    output_path: Path,
    voice: str = "pt-BR-AntonioNeural",
    rate: str = "+0%",
    on_chunk: Optional[Callable[[int, int], None]] = None,
) -> Path:
    """Synthesize `text` into a single MP3 at `output_path`.

    Splits into chunks and concatenates raw MP3 streams (MP3 is stream-safe).
    """
    import edge_tts  # lazy import

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    chunks = _chunk_text(text)
    if not chunks:
        raise ValueError("No text to synthesize")

    with open(output_path, "wb") as out:
        for idx, chunk in enumerate(chunks):
            attempt = 0
            while True:
                try:
                    communicate = edge_tts.Communicate(chunk, voice, rate=rate)
                    async for event in communicate.stream():
                        if event["type"] == "audio":
                            out.write(event["data"])
                    break
                except Exception as e:
                    attempt += 1
                    logger.warning(
                        f"edge-tts chunk {idx + 1}/{len(chunks)} attempt {attempt} failed: {e}"
                    )
                    if attempt >= 3:
                        raise
                    await asyncio.sleep(2 * attempt)

            if on_chunk:
                try:
                    on_chunk(idx + 1, len(chunks))
                except Exception:
                    pass

    logger.info(f"edge-tts wrote {output_path} ({output_path.stat().st_size} bytes)")
    return output_path
