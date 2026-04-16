"""Task management API endpoints."""
from fastapi import APIRouter, HTTPException
from typing import List
import logging

from app.models import TaskStatusResponse
from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("/{task_id}", response_model=TaskStatusResponse)
async def get_task_status(task_id: str):
    """Get the current status of a processing task.

    Args:
        task_id: Task identifier

    Returns:
        Task status information
    """
    status = task_manager.get_task_status(task_id)

    if not status:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Task {task_id} not found", "code": "TASK_NOT_FOUND"}
        )

    return TaskStatusResponse(**status)


@router.delete("/{task_id}")
async def cancel_task(task_id: str):
    """Cancel a running task.

    Args:
        task_id: Task identifier

    Returns:
        Cancellation result
    """
    success = task_manager.cancel_task(task_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail={"error": f"Task {task_id} not found or already completed", "code": "TASK_NOT_FOUND"}
        )

    return {"success": True, "message": "Task cancelled successfully"}


@router.get("")
async def list_tasks():
    """List all tasks (simplified version).

    Returns:
        List of task summaries
    """
    # Get all tasks
    all_tasks = []
    for task_id in task_manager.tasks.keys():
        status = task_manager.get_task_status(task_id)
        if status:
            all_tasks.append(status)

    # Sort by created_at (newest first)
    all_tasks.sort(key=lambda x: x["created_at"], reverse=True)

    return {
        "tasks": all_tasks,
        "total": len(all_tasks)
    }
