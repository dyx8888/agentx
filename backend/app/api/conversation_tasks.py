"""Owner-only task readback and explicit recovery of pending chat work."""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException

from app.auth import get_current_active_user
from app.services.conversation_tasks import list_tasks, prepare_task_resume, run_task

router = APIRouter()


@router.get("/conversations/{conversation_id}/tasks")
def get_tasks(conversation_id: int, current_user=Depends(get_current_active_user)):
    try:
        return {"items": list_tasks(current_user.company_id, current_user.id, conversation_id)}
    except PermissionError as exc:
        raise HTTPException(404, "Conversation not found") from exc


@router.post("/conversations/{conversation_id}/tasks/{task_id}/resume", status_code=202)
def resume_task(conversation_id: int, task_id: str, background: BackgroundTasks,
                current_user=Depends(get_current_active_user)):
    try:
        resumable_id = prepare_task_resume(
            task_id, current_user.company_id, current_user.id, conversation_id
        )
    except PermissionError as exc:
        raise HTTPException(404, "Conversation not found") from exc
    if resumable_id is None:
        raise HTTPException(409, "Task is not pending, is still running, or has expired")
    background.add_task(
        run_task, resumable_id, current_user.company_id, current_user.id, conversation_id
    )
    return {"id": resumable_id, "status": "pending"}
