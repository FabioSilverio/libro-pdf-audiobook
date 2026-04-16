"""WebSocket endpoint for real-time progress updates."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
import logging

from app.services.task_manager import task_manager

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


@router.websocket("/ws/{task_id}")
async def websocket_endpoint(websocket: WebSocket, task_id: str):
    """WebSocket endpoint for real-time task progress updates.

    Args:
        websocket: WebSocket connection
        task_id: Task identifier to monitor
    """
    await websocket.accept()

    # Register this WebSocket connection
    task_manager.register_websocket(task_id, websocket)

    # Send current status immediately
    current_status = task_manager.get_task_status(task_id)
    if current_status:
        await websocket.send_json({
            "type": "status",
            "data": current_status
        })

    try:
        while True:
            # Keep connection alive and listen for client messages
            data = await websocket.receive_text()

            # Handle client messages (e.g., ping/pong)
            if data == "ping":
                await websocket.send_text("pong")

    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected for task {task_id}")
    except Exception as e:
        logger.error(f"WebSocket error for task {task_id}: {e}")
    finally:
        # Clean up
        task_manager.unregister_websocket(task_id)
