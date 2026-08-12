"""
Workflow Management API
Provides endpoints for submitting and managing A2A workflows
"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.core.logging import get_logger
from app.core.permissions import company_access_required
from app.database import db
from app.database.models import Workflow as ORMWorkflow

# Initialize APIRouter
router = APIRouter(tags=["workflows"])
logger = get_logger(__name__)


class WorkflowSubmissionRequest(BaseModel):
    """Request model for workflow submission"""

    name: str
    definition_json: str


class WorkflowSubmissionResponse(BaseModel):
    """Response model for workflow submission"""

    success: bool
    workflow_id: int | None = None
    message: str


def _serialize_datetime(value):
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _workflow_value(workflow, field: str, default=None):
    if isinstance(workflow, dict):
        return workflow.get(field, default)
    return getattr(workflow, field, default)


def _workflow_to_dict(workflow) -> dict:
    return {
        "id": _workflow_value(workflow, "id"),
        "company_id": _workflow_value(workflow, "company_id"),
        "name": _workflow_value(workflow, "name"),
        "status": _workflow_value(workflow, "status"),
        "definition_json": _workflow_value(workflow, "definition_json"),
        "result_json": _workflow_value(workflow, "result_json"),
        "created_at": _serialize_datetime(_workflow_value(workflow, "created_at")),
        "completed_at": _serialize_datetime(_workflow_value(workflow, "completed_at")),
    }


def _get_workflow(workflow_id: int):
    try:
        return db.get_workflow(workflow_id)
    except AttributeError:
        pass
    except Exception as exc:
        logger.warning("workflow_get_via_adapter_failed", workflow_id=workflow_id, error=str(exc))

    try:
        with db.get_session() as session:
            return session.query(ORMWorkflow).filter(ORMWorkflow.id == workflow_id).first()
    except Exception as exc:
        logger.warning("workflow_get_via_session_failed", workflow_id=workflow_id, error=str(exc))
        return None


def _list_company_workflows(company_id: int) -> list[dict]:
    try:
        with db.get_session() as session:
            workflows = (
                session.query(ORMWorkflow)
                .filter(ORMWorkflow.company_id == company_id)
                .order_by(ORMWorkflow.created_at.desc())
                .all()
            )
            return [_workflow_to_dict(workflow) for workflow in workflows]
    except Exception as exc:
        logger.warning("workflow_list_unavailable", company_id=company_id, error=str(exc))
        return []


@router.post("")
async def submit_workflow(
    request: WorkflowSubmissionRequest, current_user=Depends(company_access_required)
):
    """Submit a new workflow definition"""
    try:
        company_id = current_user.company_id
        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company access required",
            )

        workflow_id = db.create_workflow(company_id, request.name, request.definition_json)

        return WorkflowSubmissionResponse(
            success=True,
            workflow_id=workflow_id,
            message=f"Workflow '{request.name}' submitted successfully",
        )

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting workflow: {str(e)}")


@router.get("/{workflow_id:int}")
async def get_workflow_status(
    workflow_id: int, current_user=Depends(company_access_required)
):
    """Get workflow execution status and results"""
    try:
        workflow = _get_workflow(workflow_id)

        if not workflow:
            raise HTTPException(status_code=404, detail="Workflow not found")
        if _workflow_value(workflow, "company_id") != current_user.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: Cannot access workflow from another company",
            )

        return _workflow_to_dict(workflow)

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting workflow status: {str(e)}")


@router.get("")
async def list_workflows(current_user=Depends(company_access_required)):
    """List all workflows for the current company"""
    try:
        company_id = current_user.company_id
        if company_id is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Company access required",
            )

        workflows = _list_company_workflows(company_id)
        return {"workflows": workflows, "total": len(workflows)}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing workflows: {str(e)}")
