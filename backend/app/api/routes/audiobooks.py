"""Audiobook retrieval and playback API endpoints."""
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pathlib import Path
import logging

from app.config import settings
from app.services.task_manager import task_manager
from app.services.edge_tts_generator import list_voices
from app.models import TaskStatus

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/audiobooks", tags=["audiobooks"])


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

    return {
        "task_id": task_id,
        "title": result.get("metadata", {}).get("title"),
        "author": result.get("metadata", {}).get("author"),
        "page_count": result.get("metadata", {}).get("page_count"),
        "language": result.get("language"),
        "summary": result.get("summary"),
        "key_points": result.get("key_points", []),
        "chapters": result.get("chapters", []),
        "audio": result.get("audio", []),
        "created_at": task_status["created_at"],
        "text_available": True,
    }


@router.get("/{task_id}/audio/{filename}")
async def stream_audio(task_id: str, filename: str):
    """Serve a generated MP3 file for a chapter."""
    # Prevent path traversal
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
