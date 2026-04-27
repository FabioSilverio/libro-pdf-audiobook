"""Task orchestration: PDF extraction -> summary -> audiobook (per chapter MP3)."""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
import uuid
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.config import settings
from app.core.exceptions import AppException
from app.models import TaskStatus
from app.services import pdf_processor, epub_processor
from app.services.summarizer import (
    summarize,
    generate_chapter_summaries,
    _detect_language,
)
from app.services.edge_tts_generator import (
    synthesize_to_file,
    detect_voice_for_language,
)

logger = logging.getLogger(__name__)


def _safe_filename(name: str, fallback: str) -> str:
    import re
    clean = re.sub(r"[^A-Za-z0-9_\- ]+", "", name).strip().replace(" ", "_")
    return clean[:60] or fallback


def _chapter_text_manifest(chapters: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Persist full chapter text separately from lightweight metadata."""
    return {
        "chapters": [
            {
                "chapter_number": i + 1,
                "title": ch.get("title", f"Chapter {i + 1}"),
                "text": ch.get("text") or ch.get("full_text") or "",
            }
            for i, ch in enumerate(chapters)
        ]
    }


def _strip_chapter_text(chapters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return chapter metadata without heavyweight full_text payloads."""
    return [{k: v for k, v in ch.items() if k != "full_text"} for ch in chapters]


class TaskManager:
    # Keys persisted to disk (skip WebSocket handles, etc.).
    _PERSIST_KEYS = {
        "task_id", "status", "progress", "stage", "message", "file_path",
        "options", "created_at", "updated_at", "result", "error",
    }

    def __init__(self):
        self.tasks: Dict[str, Dict[str, Any]] = {}
        self.websocket_connections: Dict[str, Any] = {}
        self._load_tasks_from_disk()
        self._cleanup_uploads()

    # ---------------- persistence ----------------
    def _task_file(self, task_id: str) -> Path:
        return Path(settings.OUTPUT_DIR) / task_id / "task.json"

    def _persist_task(self, task_id: str) -> None:
        """Write a task's state to disk atomically."""
        task = self.tasks.get(task_id)
        if not task:
            return
        path = self._task_file(task_id)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            data = {k: task.get(k) for k in self._PERSIST_KEYS}
            tmp = path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(path)
        except Exception as e:
            logger.warning(f"persist failed {task_id}: {e}")

    def _load_tasks_from_disk(self) -> None:
        """On startup, reload task state from disk.

        Any task that was mid-flight is marked failed with a helpful message —
        we can't resume mid-generation after a restart.
        """
        out_dir = Path(settings.OUTPUT_DIR)
        if not out_dir.exists():
            return
        restored = 0
        resurrected_failed = 0
        for sub in out_dir.iterdir():
            if not sub.is_dir():
                continue
            task_file = sub / "task.json"
            if not task_file.exists():
                continue
            try:
                data = json.loads(task_file.read_text(encoding="utf-8"))
                task_id = data.get("task_id") or sub.name
                active = data.get("status") in (
                    TaskStatus.QUEUED, TaskStatus.EXTRACTING,
                    TaskStatus.SUMMARIZING, TaskStatus.GENERATING_AUDIO,
                )
                if active:
                    data["status"] = TaskStatus.FAILED
                    data["progress"] = 0
                    data["message"] = (
                        "Processing was interrupted by a server restart. "
                        "Please upload the PDF again — it was not finished."
                    )
                    data["error"] = {
                        "code": "SERVER_RESTART",
                        "message": "Server restarted mid-processing.",
                    }
                    data["updated_at"] = datetime.utcnow().isoformat()
                    resurrected_failed += 1
                self.tasks[task_id] = {
                    **data,
                    # Required runtime key — might be absent.
                    "file_path": data.get("file_path", ""),
                    "options": data.get("options", {}),
                }
                restored += 1
                # Re-persist so status on disk reflects the change.
                if active:
                    self._persist_task(task_id)
            except Exception as e:
                logger.warning(f"Could not restore task {sub.name}: {e}")
        if restored:
            logger.info(
                f"Restored {restored} task(s) from disk "
                f"({resurrected_failed} were marked failed due to restart)."
            )

    def _cleanup_uploads(self) -> None:
        """Delete any leftover uploaded files to free disk space on startup."""
        upload_dir = Path(settings.UPLOAD_DIR)
        if not upload_dir.exists():
            return
        removed = 0
        for f in upload_dir.iterdir():
            if f.is_file() and f.suffix.lower() in (".pdf", ".epub"):
                try:
                    f.unlink()
                    removed += 1
                except Exception:
                    pass
        if removed:
            logger.info(f"Cleaned up {removed} leftover uploaded file(s)")
        # Also auto-clean completed/failed tasks older than retention period.
        self.cleanup_old_tasks()

    def create_task(self, file_path: str, options: Optional[Dict[str, Any]] = None) -> str:
        # Proactively free disk before heavy processing.
        self.ensure_disk_space(needed_mb=80)

        task_id = str(uuid.uuid4())
        now = datetime.utcnow().isoformat()
        self.tasks[task_id] = {
            "task_id": task_id,
            "status": TaskStatus.QUEUED,
            "progress": 0,
            "stage": "queued",
            "message": "Task queued for processing",
            "file_path": file_path,
            "options": options or {},
            "created_at": now,
            "updated_at": now,
            "result": None,
            "error": None,
        }
        self._persist_task(task_id)
        asyncio.create_task(self._process_task(task_id))
        logger.info(f"Created task {task_id}")
        return task_id

    async def _process_task(self, task_id: str):
        task = self.tasks.get(task_id)
        if not task:
            return

        opts = task["options"]
        output_dir = Path(settings.OUTPUT_DIR) / task_id
        output_dir.mkdir(parents=True, exist_ok=True)
        audio_dir = output_dir / "audio"
        audio_dir.mkdir(parents=True, exist_ok=True)

        try:
            # 1. Extract text ---------------------------------------------------
            is_epub = task["file_path"].lower().endswith(".epub")
            file_label = "EPUB" if is_epub else "PDF"
            proc = epub_processor if is_epub else pdf_processor

            await self._update_status(
                task_id, status=TaskStatus.EXTRACTING, progress=5,
                stage="extracting",
                message=f"Reading {file_label}" + ("" if is_epub else " (OCR will run if scanned)") + "...",
            )
            main_loop = asyncio.get_running_loop()

            def _extract_progress(stage: str, done: int, total: int, message: str):
                pct = 5 + int((done / max(total, 1)) * 15)
                asyncio.run_coroutine_threadsafe(
                    self._update_status(task_id, progress=pct, message=message),
                    main_loop,
                )

            text = await asyncio.to_thread(
                proc.extract_text,
                task["file_path"],
                ocr_lang=opts.get("language", "auto"),
                on_progress=_extract_progress,
            )
            metadata = await asyncio.to_thread(proc.extract_metadata, task["file_path"])

            # Free disk space — we no longer need the uploaded file.
            try:
                if not is_epub:
                    Path(task["file_path"]).unlink(missing_ok=True)
            except Exception:
                pass

            # Fall back to the uploaded filename (without the .pdf extension)
            # when the PDF has no embedded title — otherwise every book
            # ends up displayed as "Untitled book" in the library.
            if not metadata.get("title"):
                original = opts.get("original_filename") or ""
                if original:
                    stem = Path(original).stem.strip()
                    # Replace underscores/hyphens with spaces for readability
                    stem = stem.replace("_", " ").replace("-", " ").strip()
                    if stem:
                        metadata["title"] = stem[:200]
            metadata["original_filename"] = opts.get("original_filename")

            (output_dir / "extracted_text.txt").write_text(text, encoding="utf-8")

            language = opts.get("language", "auto")
            if language == "auto":
                language = _detect_language(text)

            await self._update_status(
                task_id, progress=20,
                message=f"Extracted {len(text):,} chars from {metadata.get('page_count', '?')} pages ({language})",
            )

            # 2. Detect chapters ------------------------------------------------
            if is_epub:
                chapters = await asyncio.to_thread(
                    epub_processor.split_into_chapters, task["file_path"], text,
                )
            else:
                chapters = await asyncio.to_thread(pdf_processor.split_into_chapters, text)
            logger.info(f"Task {task_id}: {len(chapters)} chapters detected")

            (output_dir / "chapter_texts.json").write_text(
                json.dumps(_chapter_text_manifest(chapters), ensure_ascii=False),
                encoding="utf-8",
            )

            if is_epub:
                try:
                    Path(task["file_path"]).unlink(missing_ok=True)
                except Exception:
                    pass

            # 3. Summarization --------------------------------------------------
            summary_data: Dict[str, Any] = {"metadata": metadata, "language": language}
            if opts.get("summarize", True):
                await self._update_status(
                    task_id, status=TaskStatus.SUMMARIZING, progress=25,
                    stage="summarizing", message="Summarizing book...",
                )
                overall = await summarize(
                    text[:200_000],
                    length=opts.get("summary_length", "medium"),
                    language=language,
                )
                summary_data["summary"] = overall["summary"]
                summary_data["key_points"] = overall.get("key_points", [])

                await self._update_status(
                    task_id, progress=35, message="Summarizing chapters...",
                )
                chapter_summaries = await generate_chapter_summaries(
                    chapters,
                    length=opts.get("summary_length", "medium"),
                    language=language,
                )
                summary_data["chapters"] = _strip_chapter_text(chapter_summaries)
            else:
                summary_data["summary"] = ""
                summary_data["key_points"] = []
                summary_data["chapters"] = [
                    {
                        "chapter_number": i + 1,
                        "title": ch.get("title", f"Chapter {i + 1}"),
                        "summary": "",
                        "key_points": [],
                    }
                    for i, ch in enumerate(chapters)
                ]

            # 4. Audio ─ on-demand ------------------------------------------------
            # We NO LONGER pre-generate all chapter audio during processing.
            # Instead, each chapter's MP3 is synthesized the first time the
            # user requests it (see audiobooks route GET .../audio/chapter/N).
            # This avoids filling the Railway volume with hundreds of MB of
            # MP3 files for a single book.
            #
            # Store voice preference so on-demand generation uses the same voice.
            summary_data["voice"] = opts.get("voice") or detect_voice_for_language(language)
            summary_data["audio"] = []  # populated lazily per chapter

            # 5. Persist + complete --------------------------------------------
            (output_dir / "summary.json").write_text(
                json.dumps(summary_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            task["result"] = summary_data

            await self._update_status(
                task_id, status=TaskStatus.COMPLETED, progress=100,
                stage="completed", message="Processing complete!",
            )
            logger.info(f"Task {task_id} completed")

        except AppException as e:
            await self._update_status(
                task_id, status=TaskStatus.FAILED, progress=0, message=e.message,
            )
            task["error"] = {"code": e.code, "message": e.message}
            logger.error(f"Task {task_id} failed: {e.message}")
        except Exception as e:
            await self._update_status(
                task_id, status=TaskStatus.FAILED, progress=0,
                message=f"Unexpected error: {e}",
            )
            task["error"] = {"code": "UNKNOWN_ERROR", "message": str(e)}
            logger.error(f"Task {task_id} failed: {e}", exc_info=True)

    async def _update_status(self, task_id: str, status=None, progress=None,
                             stage=None, message=None):
        task = self.tasks.get(task_id)
        if not task:
            return
        if status:
            task["status"] = status
        if progress is not None:
            task["progress"] = progress
        if stage:
            task["stage"] = stage
        if message:
            task["message"] = message
        task["updated_at"] = datetime.utcnow().isoformat()
        self._persist_task(task_id)
        await self._send_websocket_update(task_id)

    async def _send_websocket_update(self, task_id: str):
        ws = self.websocket_connections.get(task_id)
        if not ws:
            return
        try:
            task = self.tasks[task_id]
            await ws.send_json({
                "type": "progress",
                "data": {
                    "task_id": task_id,
                    "status": task["status"],
                    "progress": task["progress"],
                    "stage": task.get("stage"),
                    "message": task.get("message"),
                },
            })
        except Exception as e:
            logger.warning(f"ws send failed {task_id}: {e}")
            self.websocket_connections.pop(task_id, None)

    def get_task_status(self, task_id: str) -> Optional[Dict[str, Any]]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        return {
            "task_id": task["task_id"],
            "status": task["status"],
            "progress": task["progress"],
            "stage": task.get("stage"),
            "message": task.get("message"),
            "created_at": task["created_at"],
            "updated_at": task["updated_at"],
            "result": task.get("result"),
            "error": task.get("error"),
        }

    def cancel_task(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        if not task:
            return False
        if task["status"] in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
            return False
        task["status"] = TaskStatus.CANCELLED
        task["message"] = "Task cancelled by user"
        task["updated_at"] = datetime.utcnow().isoformat()
        self._persist_task(task_id)
        self._cleanup_task_files(task_id)
        return True

    def delete_task(self, task_id: str) -> bool:
        if task_id not in self.tasks:
            return False
        del self.tasks[task_id]
        self._cleanup_task_files(task_id)
        return True

    def _cleanup_task_files(self, task_id: str):
        task_dir = Path(settings.OUTPUT_DIR) / task_id
        if task_dir.exists():
            try:
                shutil.rmtree(task_dir)
            except Exception as e:
                logger.warning(f"cleanup failed {task_id}: {e}")

    def register_websocket(self, task_id: str, websocket):
        self.websocket_connections[task_id] = websocket

    def unregister_websocket(self, task_id: str):
        self.websocket_connections.pop(task_id, None)

    def cleanup_old_tasks(self, older_than_hours: Optional[int] = None):
        hours = older_than_hours or settings.TASK_RETENTION_HOURS
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        to_rm = []
        for tid, t in self.tasks.items():
            created = datetime.fromisoformat(t["created_at"])
            if created < cutoff and t["status"] in [
                TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED,
            ]:
                to_rm.append(tid)
        for tid in to_rm:
            self.delete_task(tid)
        if to_rm:
            logger.info(f"Time-based cleanup: removed {len(to_rm)} old task(s)")

    # ---- Disk space management ----

    def _dir_size_mb(self, path: Path) -> float:
        """Return total size of a directory tree in MB."""
        total = 0
        try:
            for f in path.rglob("*"):
                if f.is_file():
                    total += f.stat().st_size
        except Exception:
            pass
        return total / (1024 * 1024)

    def ensure_disk_space(self, needed_mb: float = 50) -> None:
        """Free disk space by purging oldest completed tasks until we have
        at least `needed_mb` MB free (relative to MAX_DISK_USAGE_MB).

        Called automatically before starting a new task.
        """
        output_dir = Path(settings.OUTPUT_DIR)
        max_mb = settings.MAX_DISK_USAGE_MB

        current_mb = self._dir_size_mb(output_dir)
        if current_mb + needed_mb <= max_mb:
            return  # plenty of room

        # Build list of purgeable tasks (completed/failed), oldest first.
        purgeable = []
        for tid, t in self.tasks.items():
            if t["status"] in [TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED]:
                task_dir = output_dir / tid
                size = self._dir_size_mb(task_dir) if task_dir.exists() else 0
                purgeable.append((tid, t["created_at"], size))

        purgeable.sort(key=lambda x: x[1])  # oldest first

        freed = 0
        removed = []
        for tid, _, size in purgeable:
            if current_mb - freed + needed_mb <= max_mb:
                break
            self.delete_task(tid)
            freed += size
            removed.append(tid)

        if removed:
            logger.info(
                f"Disk cleanup: purged {len(removed)} task(s), "
                f"freed ~{freed:.1f} MB (was {current_mb:.1f} MB, cap {max_mb} MB)"
            )


task_manager = TaskManager()
