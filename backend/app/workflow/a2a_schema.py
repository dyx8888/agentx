"""
A2A Message Schema Definition
Defines the standard A2A message format for Agent-to-Agent communication
"""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class A2AMessage(BaseModel):
    """Standard A2A message format"""

    message_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    sender_agent_name: str
    recipient_agent_name: str | None = None  # Can be array for multiple recipients
    task_description: str
    task_type: str  # e.g., "analysis", "outreach", "script_generation"
    payload: dict[str, Any] | None = None  # Structured parameters
    company_id: int
    status: str = "pending"  # pending, processing, completed, failed
    result: dict[str, Any] | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


def create_a2a_message(
    sender: str,
    recipients: list[str],
    task: str,
    task_type: str,
    company_id: int,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """
    Create a standard A2A message

    Args:
        sender: Sender agent name
        recipients: List of recipient agent names
        task: Task description
        task_type: Type of task
        company_id: Company ID for multi-tenant isolation
        payload: Optional structured parameters

    Returns:
        Dictionary representing the A2A message
    """
    message_id = uuid.uuid4().hex

    return {
        "message_id": message_id,
        "sender_agent_name": sender,
        "recipient_agent_name": recipients[0] if len(recipients) == 1 else recipients,
        "task_description": task,
        "task_type": task_type,
        "payload": payload,
        "company_id": company_id,
        "status": "pending",
        "result": None,
        "created_at": datetime.utcnow().isoformat(),
        "completed_at": None,
    }


class WorkflowDefinition(BaseModel):
    """Workflow definition for A2A DAG execution"""

    id: int | None = None
    company_id: int
    name: str
    status: str = "pending"
    definition_json: str  # JSON representation of workflow DAG
    result_json: str | None = None  # Final aggregated results
    created_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None

    class Config:
        json_encoders = {datetime: lambda v: v.isoformat() if v else None}


class WorkflowNode(BaseModel):
    """Individual node in a workflow DAG"""

    id: str
    agent: str
    action: str  # e.g., "search_kols", "generate_outreach"
    params: dict[str, Any]
    depends_on: list[str] = []  # List of node IDs this node depends on
