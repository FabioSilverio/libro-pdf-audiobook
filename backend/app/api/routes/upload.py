"""File upload API endpoints with streaming to disk (handles up to 400MB)."""
import uuid
from pathlib import Path
from fastapi import APIRouter, UploadFile, File, HTTPException, Form
import logging

from app.config import settings
from app.models import UploadResponse
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/upload", tags=["upload"])

CHUNK_SIZE = 1024 * 1024  # 1MB chunks


@router.post("", response_model=UploadResponse)
async def upload_pdf(
    file: UploadFile = File(...),
    summarize: bool = Form(True),
    summary_length: str = Form("medium"),
    voice: str = Form("pt-BR-AntonioNeural"),
    generate_audio: bool = Form(True),
    language: str = Form("auto"),
):
    """Upload a PDF file (streamed to disk) and start processing.

    Supports up to MAX_FILE_SIZE bytes (default 400MB).
    """
    if not file.filename or not file.filename.lower().endswith('.pdf'):
        raise HTTPException(
            status_code=422,
            detail={"error": "Only PDF files are accepted", "code": "INVALID_FILE_TYPE"}
        )

    file_id = str(uuid.uuid4())
    file_path = Path(settings.UPLOAD_DIR) / f"{file_id}.pdf"
    file_path.parent.mkdir(parents=True, exist_ok=True)

    total_size = 0
    first_chunk_checked = False
    try:
        with open(file_path, 'wb') as out:
            while True:
                chunk = await file.read(CHUNK_SIZE)
                if not chunk:
                    break
                # Validate PDF magic bytes on first chunk
                if not first_chunk_checked:
                    first_chunk_checked = True
                    if not chunk.startswith(b'%PDF-'):
                        out.close()
                        file_path.unlink(missing_ok=True)
                        raise HTTPException(
                            status_code=422,
                            detail={"error": "Invalid PDF file format", "code": "INVALID_PDF"}
                        )
                total_size += len(chunk)
                if total_size > settings.MAX_FILE_SIZE:
                    out.close()
                    file_path.unlink(missing_ok=True)
                    max_mb = settings.MAX_FILE_SIZE // (1024 * 1024)
                    raise HTTPException(
                        status_code=413,
                        detail={
                            "error": f"File too large. Maximum size is {max_mb}MB",
                            "code": "FILE_TOO_LARGE"
                        }
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save uploaded file: {e}", exc_info=True)
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail={"error": "Failed to save file", "code": "SAVE_ERROR"}
        )

    if total_size < 1024:
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail={"error": "File too small or corrupted", "code": "FILE_TOO_SMALL"}
        )

    logger.info(f"Saved uploaded file {file.filename} -> {file_path} ({total_size} bytes)")

    options = {
        "summarize": summarize,
        "summary_length": summary_length,
        "voice": voice,
        "generate_audio": generate_audio,
        "language": language,
        "original_filename": file.filename,
        "file_size": total_size,
    }

    task_id = task_manager.create_task(str(file_path), options)

    return UploadResponse(
        task_id=task_id,
        status="queued",
        message="File uploaded successfully. Processing started.",
        estimated_time="2-10 minutes depending on size"
    )


@router.get("/validate")
async def validate_upload(filename: str, size: int):
    """Client-side validation helper."""
    errors = []
    if not filename.lower().endswith('.pdf'):
        errors.append("Only PDF files are accepted")
    if size > settings.MAX_FILE_SIZE:
        errors.append(f"File exceeds maximum size of {settings.MAX_FILE_SIZE // (1024*1024)}MB")
    if size < 1024:
        errors.append("File is too small")
    return {"valid": len(errors) == 0, "errors": errors or None}
