"""
Workflow Management API
Provides endpoints for submitting and managing A2A workflows
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.permissions import admin_required
from app.database import db

# Initialize APIRouter
router = APIRouter(tags=["workflows"])

class WorkflowSubmissionRequest(BaseModel):
    """Request model for workflow submission"""
    name: str
    definition_json: str

class WorkflowSubmissionResponse(BaseModel):
    """Response model for workflow submission"""
    success: bool
    workflow_id: int | None = None
    message: str

@router.post("/workflows")
async def submit_workflow(
    request: WorkflowSubmissionRequest,
    current_user = Depends(admin_required)
):
    """Submit a new workflow definition"""
    try:
        # Get company_id from current user
        company_id = current_user.company_id

        # Submit workflow
        workflow_id = db.create_workflow(company_id, request.name, request.definition_json)

        return WorkflowSubmissionResponse(
            success=True,
            workflow_id=workflow_id,
            message=f"Workflow '{request.name}' submitted successfully"
        )

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error submitting workflow: {str(e)}")

@router.get("/workflows/{workflow_id}")
async def get_workflow_status(
    workflow_id: int,
    current_user = Depends(admin_required)
):
    """Get workflow execution status and results"""
    try:
        # Get workflow status
        workflow_status = db.get_workflow_status(workflow_id)

        if not workflow_status:
            raise HTTPException(status_code=404, detail="Workflow not found")

        return workflow_status

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error getting workflow status: {str(e)}")

@router.get("/workflows")
async def list_workflows(
    current_user = Depends(admin_required)
):
    """List all workflows for the current company"""
    try:
        # Get company_id from current user
        company_id = current_user.company_id

        # Get all workflows for this company
        workflows = db.get_pending_workflows()

        return {
            "workflows": workflows,
            "total": len(workflows)
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error listing workflows: {str(e)}")
