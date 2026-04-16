"""Pydantic models for request/response validation."""
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from enum import Enum


class TaskStatus(str, Enum):
    """Possible states for a processing task."""
    QUEUED = "queued"
    EXTRACTING = "extracting"
    SUMMARIZING = "summarizing"
    GENERATING_AUDIO = "generating_audio"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class UploadResponse(BaseModel):
    """Response after uploading a PDF file."""
    task_id: str
    status: str
    message: str
    estimated_time: Optional[str] = "2-5 minutes"


class TaskStatusResponse(BaseModel):
    """Response for task status queries."""
    task_id: str
    status: str
    progress: int = Field(ge=0, le=100)
    stage: Optional[str] = None
    message: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class SummaryData(BaseModel):
    """Book summary data structure."""
    summary: str
    key_points: list[str]
    chapters: Optional[list[Dict[str, Any]]] = None


class AudiobookMetadata(BaseModel):
    """Metadata for a generated audiobook."""
    task_id: str
    title: Optional[str] = None
    author: Optional[str] = None
    duration: Optional[float] = None  # in seconds
    file_size: Optional[int] = None  # in bytes
    format: str = "mp3"
    summary: Optional[str] = None
    chapters: Optional[list[Dict[str, Any]]] = None
    created_at: Optional[str] = None


class ErrorResponse(BaseModel):
    """Standard error response format."""
    error: str
    code: str
    detail: Optional[str] = None
