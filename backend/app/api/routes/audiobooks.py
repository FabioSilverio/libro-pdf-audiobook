"""Audiobook retrieval and playback API endpoints."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import json
import logging

from app.config import settings
from app.services.task_manager import task_manager
from app.services.edge_tts_generator import list_voices
from app.models import TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audiobooks", tags=["audiobooks"])


def _norm_chapter_num(value) -> int | None:
    """Coerce JSON/primitive chapter_number to int for reliable comparisons."""
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _same_chapter_number(a, b) -> bool:
    """True if a and b refer to the same chapter index (handles str vs int in JSON)."""
    na, nb = _norm_chapter_num(a), _norm_chapter_num(b)
    if na is not None and nb is not None:
        return na == nb
    return (a is not None and b is not None) and (str(a) == str(b))


def _chapter_text_path(task_id: str) -> Path:
    return Path(settings.OUTPUT_DIR) / task_id / "chapter_texts.json"


def _load_chapter_texts(task_id: str) -> list[dict]:
    path = _chapter_text_path(task_id)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        chapters = data.get("chapters", [])
        return chapters if isinstance(chapters, list) else []
    except Exception as e:
        logger.warning(f"Could not read chapter text manifest for {task_id}: {e}")
        return []


def _load_summary_file(task_id: str) -> dict | None:
    p = Path(settings.OUTPUT_DIR) / task_id / "summary.json"
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.debug(f"Could not read summary.json for {task_id}: {e}")
        return None


def _find_chapter_text(task_id: str, chapter_number: int) -> str:
    raw = _load_chapter_texts(task_id)
    n = _norm_chapter_num(chapter_number) or chapter_number
    for ch in raw:
        if _same_chapter_number(ch.get("chapter_number"), n):
            t = (ch.get("text") or "").strip()
            if t:
                return t
    # Last resort: manifest is ordered; some legacy files use inconsistent keys.
    if raw and isinstance(n, int) and 1 <= n <= len(raw):
        t = (raw[n - 1].get("text") or "").strip()
        if t:
            return t
    return ""


def _without_full_text(chapter: dict) -> dict:
    return {k: v for k, v in chapter.items() if k != "full_text"}


@router.get("/voices")
async def get_voices():
    """List available TTS voices."""
    return {"voices": list_voices()}


@router.get("/{task_id}")
async def get_audiobook_metadata(task_id: str):
    """Get metadata for a completed audiobook.

    Args:
        task_id: Task identifier

    Returns:
        Audiobook metadata including summary
    """
    task_status = task_manager.get_task_status(task_id)

    if not task_status:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Task {task_id} not found", "code": "TASK_NOT_FOUND"}
        )

    if task_status["status"] != TaskStatus.COMPLETED:
        raise HTTPException(
            status_code=400,
            detail={
                "error": f"Task is not completed. Current status: {task_status['status']}",
                "code": "TASK_NOT_COMPLETED"
            }
        )

    result = task_status.get("result", {})

    # Build on-demand audio manifest from chapters (even if pre-gen audio
    # exists we also include the on-demand URLs as a fallback).
    chapters = [_without_full_text(ch) for ch in result.get("chapters", [])]
    audio = result.get("audio", [])
    if not audio and chapters:
        audio = [
            {
                "index": ch.get("chapter_number", i + 1),
                "title": ch.get("title", f"Chapter {i + 1}"),
                "url": f"/api/v1/audiobooks/{task_id}/audio/chapter/{ch.get('chapter_number', i + 1)}",
                "on_demand": True,
            }
            for i, ch in enumerate(chapters)
        ]

    return {
        "task_id": task_id,
        "title": result.get("metadata", {}).get("title"),
        "author": result.get("metadata", {}).get("author"),
        "page_count": result.get("metadata", {}).get("page_count"),
        "language": result.get("language"),
        "summary": result.get("summary"),
        "key_points": result.get("key_points", []),
        "chapters": chapters,
        "audio": audio,
        "created_at": task_status["created_at"],
        "text_available": True,
    }


@router.post("/{task_id}/resummarize")
async def resummarize_audiobook(task_id: str, length: str = "medium"):
    """Re-generate summaries and key points for an already-processed book.

    Uses the extracted text still on disk (or re-reads the source PDF if
    needed) and runs the current, improved summarizer. The task's result is
    updated in-place so the frontend can refresh its cached library entry.
    """
    from app.services.pdf_processor import split_into_chapters, extract_text
    from app.services.summarizer import summarize, generate_chapter_summaries, _detect_language

    task_status = task_manager.get_task_status(task_id)
    if not task_status:
        raise HTTPException(status_code=404, detail={
            "error": f"Task {task_id} not found", "code": "TASK_NOT_FOUND",
        })

    task = task_manager.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"error": "Task state unavailable"})

    output_dir = Path(settings.OUTPUT_DIR) / task_id
    text_file = output_dir / "extracted_text.txt"

    # Prefer the cached extracted text; fall back to re-extracting the PDF
    # (handles older tasks whose extracted_text.txt was wiped before the
    # persistent volume was added).
    text = ""
    if text_file.exists():
        try:
            text = text_file.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Couldn't read cached text for {task_id}: {e}")

    if not text or len(text.strip()) < 200:
        pdf_path = task.get("file_path")
        if pdf_path and Path(pdf_path).exists():
            try:
                text = extract_text(pdf_path)
                try:
                    output_dir.mkdir(parents=True, exist_ok=True)
                    text_file.write_text(text, encoding="utf-8")
                except Exception:
                    pass
            except Exception as e:
                logger.warning(f"Re-extract failed for {task_id}: {e}")

    if not text or len(text.strip()) < 200:
        raise HTTPException(status_code=410, detail={
            "error": "Source text no longer available for this book. Please re-upload.",
            "code": "TEXT_UNAVAILABLE",
        })

    language = task.get("options", {}).get("language", "auto")
    if language == "auto":
        language = _detect_language(text)

    # Re-summarize overall + per chapter.
    overall = await summarize(text, length=length, language=language)
    chapters = split_into_chapters(text)
    chapter_summaries = await generate_chapter_summaries(
        chapters, length=length, language=language,
    )
    try:
        _chapter_text_path(task_id).write_text(
            json.dumps({
                "chapters": [
                    {
                        "chapter_number": i + 1,
                        "title": ch.get("title", f"Chapter {i + 1}"),
                        "text": ch.get("text", ""),
                    }
                    for i, ch in enumerate(chapters)
                ]
            }, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception as e:
        logger.warning(f"Could not persist chapter texts for {task_id}: {e}")

    # Merge back into the stored result, preserving audio + metadata.
    result = task.get("result") or {}
    result["summary"] = overall["summary"]
    result["key_points"] = overall.get("key_points", [])
    result["chapters"] = [_without_full_text(ch) for ch in chapter_summaries]
    result["language"] = language
    task["result"] = result
    task_manager._persist_task(task_id)
    logger.info(f"Re-summarized task {task_id}: {len(chapter_summaries)} chapters")

    return {
        "task_id": task_id,
        "title": result.get("metadata", {}).get("title"),
        "author": result.get("metadata", {}).get("author"),
        "page_count": result.get("metadata", {}).get("page_count"),
        "language": language,
        "summary": result["summary"],
        "key_points": result["key_points"],
        "chapters": [_without_full_text(ch) for ch in result["chapters"]],
        "audio": result.get("audio", []),
        "created_at": task_status["created_at"],
    }


@router.post("/{task_id}/recover")
async def recover_failed_task(task_id: str):
    """Recover a failed task that already has extracted text / summaries on disk.

    Marks the task as completed so the user can access whatever was generated
    before the failure (summaries, partial audio, etc.).  Optionally retries
    audio generation if space is available.
    """
    import json as _json

    task = task_manager.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail={"error": "Task not found"})

    if task["status"] == TaskStatus.COMPLETED:
        return {"recovered": False, "message": "Task is already completed"}

    output_dir = Path(settings.OUTPUT_DIR) / task_id

    # 1) Try to load existing summary.json
    summary_path = output_dir / "summary.json"
    result = task.get("result") or {}
    if summary_path.exists():
        try:
            result = _json.loads(summary_path.read_text(encoding="utf-8"))
        except Exception:
            pass

    # 2) If no result at all, try to rebuild from extracted text.
    #    Uses ONLY the fast extractive summarizer (_extractive_summarize)
    #    to avoid blocking the server with slow LLM calls.
    text_file = output_dir / "extracted_text.txt"
    if not result.get("chapters") and text_file.exists():
        from app.services.pdf_processor import split_into_chapters
        from app.services.summarizer import _extractive_summarize, _detect_language

        text = text_file.read_text(encoding="utf-8")
        if text and len(text.strip()) > 100:
            language = _detect_language(text)
            chapters = split_into_chapters(text)
            overall = _extractive_summarize(text[:200_000], length="medium", language=language)
            ch_summaries = []
            for i, ch in enumerate(chapters):
                ch_text = ch.get("text", "")
                if ch_text.strip():
                    ch_sum = _extractive_summarize(ch_text[:30_000], length="medium", language=language)
                else:
                    ch_sum = {"summary": "", "key_points": []}
                ch_summaries.append({
                    "chapter_number": i + 1,
                    "title": ch.get("title", f"Chapter {i + 1}"),
                    "summary": ch_sum.get("summary", ""),
                    "key_points": ch_sum.get("key_points", []),
                })
            result["summary"] = overall["summary"]
            result["key_points"] = overall.get("key_points", [])
            result["chapters"] = ch_summaries
            result["language"] = language

    if not result.get("chapters"):
        raise HTTPException(status_code=410, detail={
            "error": "No recoverable data found. Please re-upload the file.",
            "code": "NOTHING_TO_RECOVER",
        })

    # 3) Collect whatever audio already exists
    audio_dir = output_dir / "audio"
    audio_manifest = result.get("audio", [])
    if audio_dir.exists() and not audio_manifest:
        for mp3 in sorted(audio_dir.glob("*.mp3")):
            audio_manifest.append({
                "file": mp3.name,
                "url": f"/api/v1/audiobooks/{task_id}/audio/{mp3.name}",
                "size": mp3.stat().st_size,
            })
        result["audio"] = audio_manifest

    # 4) Mark as completed
    task["result"] = result
    task["status"] = TaskStatus.COMPLETED
    task["progress"] = 100
    task["message"] = "Recovered from failed state"
    task_manager._persist_task(task_id)

    # Persist the (possibly updated) summary.json too.
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(
            _json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8",
        )
    except Exception:
        pass

    logger.info(f"Recovered task {task_id}: {len(result.get('chapters', []))} chapters, {len(audio_manifest)} audio files")

    return {
        "recovered": True,
        "task_id": task_id,
        "title": result.get("metadata", {}).get("title"),
        "chapters": len(result.get("chapters", [])),
        "audio_files": len(audio_manifest),
    }


@router.get("/{task_id}/audio/chapter/{chapter_number}")
async def stream_chapter_audio(task_id: str, chapter_number: int):
    """Generate and serve audio for a single chapter on-demand.

    The MP3 is synthesized the first time it is requested (cached on disk
    for subsequent plays).  Old cached files are automatically cleaned up
    by the disk-management system when space runs low.
    """
    from app.services.edge_tts_generator import synthesize_to_file, detect_voice_for_language

    task = task_manager.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Task not completed yet")

    result = task.get("result") or {}
    chapters = result.get("chapters", [])

    n = _norm_chapter_num(chapter_number)
    if n is None:
        n = chapter_number
    ch = None
    for c in chapters:
        if _same_chapter_number(c.get("chapter_number"), n):
            ch = c
            break
    n_idx = _norm_chapter_num(n) if n is not None else None
    if not ch and chapters and n_idx is not None and 1 <= n_idx <= len(chapters):
        ch = chapters[n_idx - 1]
    if not ch:
        raise HTTPException(status_code=404, detail=f"Chapter {chapter_number} not found")

    # Build filename
    title = ch.get("title", f"Chapter {chapter_number}")
    import re
    safe_title = re.sub(r"[^A-Za-z0-9_\- ]+", "", title).strip().replace(" ", "_")[:60] or f"chapter_{chapter_number}"
    filename = f"{chapter_number:03d}_{safe_title}.mp3"

    audio_dir = Path(settings.OUTPUT_DIR) / task_id / "audio"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / filename

    # Return cached file if it exists
    if audio_path.exists() and audio_path.stat().st_size > 0:
        return FileResponse(
            str(audio_path), media_type="audio/mpeg",
            filename=filename, headers={"Accept-Ranges": "bytes"},
        )

    # Need the chapter text from the lightweight sidecar manifest. Older tasks
    # may still have full_text in summary.json or only extracted_text.txt.
    text = _find_chapter_text(task_id, chapter_number) or ch.get("full_text", "")
    if not text:
        text_file = Path(settings.OUTPUT_DIR) / task_id / "extracted_text.txt"
        if text_file.exists():
            full = text_file.read_text(encoding="utf-8")
            # Re-split to get this chapter's text
            from app.services.pdf_processor import split_into_chapters
            splits = split_into_chapters(full)
            ni = _norm_chapter_num(chapter_number) or 1
            idx = int(ni) - 1
            if 0 <= idx < len(splits):
                text = splits[idx].get("text", "")

    if not text or len(text.strip()) < 10:
        raise HTTPException(status_code=410, detail="Chapter text not available for TTS")

    text = text[:settings.TTS_MAX_CHARS_PER_CHAPTER]
    voice = result.get("voice") or detect_voice_for_language(result.get("language", "pt"))

    # Free disk space before generating
    task_manager.ensure_disk_space(needed_mb=30)

    try:
        await synthesize_to_file(text, audio_path, voice=voice)
    except OSError as e:
        if "No space left" in str(e):
            # Emergency cleanup + retry once
            task_manager.ensure_disk_space(needed_mb=80)
            await synthesize_to_file(text, audio_path, voice=voice)
        else:
            raise

    logger.info(f"Generated audio for {task_id} ch {chapter_number} ({audio_path.stat().st_size} bytes)")

    return FileResponse(
        str(audio_path), media_type="audio/mpeg",
        filename=filename, headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{task_id}/chapters/{chapter_number}/text")
async def get_chapter_text(task_id: str, chapter_number: int):
    """Return one chapter's full text for the reader UI."""
    task = task_manager.tasks.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
    if task["status"] != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Task not completed yet")

    result = task.get("result") or {}
    n = _norm_chapter_num(chapter_number) if _norm_chapter_num(chapter_number) is not None else chapter_number
    title = f"Chapter {chapter_number}"
    for ch in result.get("chapters", []):
        if _same_chapter_number(ch.get("chapter_number"), n):
            title = ch.get("title") or title
            break

    text = _find_chapter_text(task_id, chapter_number)
    if not text:
        for ch in result.get("chapters", []):
            if _same_chapter_number(ch.get("chapter_number"), n):
                text = ch.get("full_text", "")
                break

    if not text:
        disk = _load_summary_file(task_id)
        if disk:
            for ch in (disk.get("chapters") or []):
                if _same_chapter_number(ch.get("chapter_number"), n):
                    text = (ch.get("full_text") or ch.get("text") or "")
                    if text:
                        break

    if not text:
        text_file = Path(settings.OUTPUT_DIR) / task_id / "extracted_text.txt"
        if text_file.exists():
            full = text_file.read_text(encoding="utf-8")
            from app.services.pdf_processor import split_into_chapters
            splits = split_into_chapters(full)
            ni = _norm_chapter_num(chapter_number) or 1
            idx = int(ni) - 1
            if 0 <= idx < len(splits):
                text = splits[idx].get("text", "")

    if not text:
        raise HTTPException(status_code=404, detail="Chapter text not found")

    return {
        "task_id": task_id,
        "chapter_number": chapter_number,
        "title": title,
        "text": text,
        "length": len(text),
    }


@router.get("/{task_id}/audio/{filename}")
async def stream_audio(task_id: str, filename: str):
    """Serve a pre-generated MP3 file (legacy path for older tasks)."""
    safe_name = Path(filename).name
    audio_path = Path(settings.OUTPUT_DIR) / task_id / "audio" / safe_name
    if not audio_path.exists() or audio_path.suffix.lower() != ".mp3":
        raise HTTPException(status_code=404, detail="Audio not found")
    return FileResponse(
        str(audio_path),
        media_type="audio/mpeg",
        filename=safe_name,
        headers={"Accept-Ranges": "bytes"},
    )


@router.get("/{task_id}/summary")
async def get_summary(task_id: str):
    """Get just the summary for an audiobook.

    Args:
        task_id: Task identifier

    Returns:
        Summary data
    """
    task_status = task_manager.get_task_status(task_id)

    if not task_status:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_status["status"] != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Task not completed")

    result = task_status.get("result", {})

    return {
        "summary": result.get("summary"),
        "key_points": result.get("key_points", []),
        "chapters": result.get("chapters", [])
    }


@router.get("/{task_id}/text")
async def get_extracted_text(task_id: str):
    """Get the extracted text for browser-based TTS.

    Args:
        task_id: Task identifier

    Returns:
        Extracted text content
    """
    task_status = task_manager.get_task_status(task_id)

    if not task_status:
        raise HTTPException(status_code=404, detail="Task not found")

    if task_status["status"] != TaskStatus.COMPLETED:
        raise HTTPException(status_code=400, detail="Task not completed")

    # Read extracted text file
    text_file = Path(settings.OUTPUT_DIR) / task_id / "extracted_text.txt"

    if not text_file.exists():
        raise HTTPException(status_code=404, detail="Text file not found")

    text_content = text_file.read_text(encoding='utf-8')

    return {
        "task_id": task_id,
        "text": text_content,
        "length": len(text_content)
    }


@router.delete("/{task_id}")
async def delete_audiobook(task_id: str):
    """Delete an audiobook and its associated files.

    Args:
        task_id: Task identifier

    Returns:
        Deletion result
    """
    success = task_manager.delete_task(task_id)

    if not success:
        raise HTTPException(status_code=404, detail="Task not found")

    return {"success": True, "message": "Audiobook deleted successfully"}


@router.get("")
async def list_audiobooks():
    """List all completed audiobooks.

    Returns:
        List of audiobook summaries
    """
    audiobooks = []

    for task_id, task in task_manager.tasks.items():
        if task["status"] == TaskStatus.COMPLETED and task.get("result"):
            result = task["result"]
            audiobooks.append({
                "task_id": task_id,
                "title": result.get("metadata", {}).get("title", "Unknown"),
                "author": result.get("metadata", {}).get("author", "Unknown"),
                "summary_preview": result.get("summary", "")[:200] + "...",
                "created_at": task["created_at"]
            })

    # Sort by created_at (newest first)
    audiobooks.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "audiobooks": audiobooks,
        "total": len(audiobooks)
    }
