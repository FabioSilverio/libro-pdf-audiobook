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
                summary_data["chapters"] = chapter_summaries
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

            # 4. Audiobook ------------------------------------------------------
            audio_manifest: List[Dict[str, Any]] = []
            if opts.get("generate_audio", True) and settings.TTS_ENABLED:
                await self._update_status(
                    task_id, status=TaskStatus.GENERATING_AUDIO, progress=45,
                    stage="generating_audio",
                    message=f"Generating audiobook ({len(chapters)} chapters)...",
                )
                voice = opts.get("voice") or detect_voice_for_language(language)
                total = len(chapters)
                base_progress = 45
                span = 55  # 45 -> 100

                for i, ch in enumerate(chapters):
                    title = ch.get("title", f"Chapter {i + 1}")
                    body = ch.get("text", "")[: settings.TTS_MAX_CHARS_PER_CHAPTER]
                    if not body.strip():
                        continue

                    filename = f"{i + 1:03d}_{_safe_filename(title, f'chapter_{i+1}')}.mp3"
                    out_path = audio_dir / filename

                    ch_start = base_progress + int((i / total) * span)
                    ch_end = base_progress + int(((i + 1) / total) * span)

                    def _progress_cb(done, tot, _i=i, _title=title,
                                     _cs=ch_start, _ce=ch_end):
                        # Called from inside synthesize_to_file (same loop).
                        p = _cs + int((done / max(tot, 1)) * (_ce - _cs))
                        asyncio.create_task(self._update_status(
                            task_id,
                            progress=min(p, 99),
                            message=f"Audio {_i + 1}/{total}: {_title[:40]} "
                                    f"({done}/{tot} segments)",
                        ))

                    try:
                        await synthesize_to_file(
                            body, out_path, voice=voice, on_chunk=_progress_cb,
                        )
                        audio_manifest.append({
                            "index": i + 1,
                            "title": title,
                            "file": filename,
                            "url": f"/api/v1/audiobooks/{task_id}/audio/{filename}",
                            "size": out_path.stat().st_size,
                        })
                    except Exception as e:
                        logger.error(f"TTS failed for chapter {i + 1}: {e}", exc_info=True)

                    await self._update_status(
                        task_id, progress=min(ch_end, 99),
                        message=f"Audio {i + 1}/{total}: {title[:40]} done",
                    )

            summary_data["audio"] = audio_manifest

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


task_manager = TaskManager()
