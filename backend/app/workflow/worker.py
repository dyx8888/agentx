"""
Workflow Worker
Background processing for A2A workflows and messages
"""

import threading
import time
import uuid

import structlog

from app.core.logging import get_logger
from app.database import db
from app.workflow.engine import WorkflowEngine

logger = get_logger(__name__)

class WorkflowWorker:
    """Background worker for processing A2A workflows"""

    def __init__(self):
        self.engine = WorkflowEngine()
        self.running = False
        self.worker_thread = None

    def start(self):
        """Start the workflow worker"""
        if self.running:
            logger.warning("Workflow worker is already running")
            return

        self.running = True
        self.worker_thread = threading.Thread(target=self._process_workflows, daemon=True)
        self.worker_thread.start()
        logger.info("Workflow worker started")

    def stop(self):
        """Stop the workflow worker"""
        self.running = False
        if self.worker_thread:
            self.worker_thread.join(timeout=10)
            self.worker_thread = None
        logger.info("Workflow worker stopped")

    def _process_workflows(self):
        """Main processing loop"""
        while self.running:
            try:
                # Get all pending workflows
                pending_workflows = db.get_pending_workflows()

                for workflow in pending_workflows:
                    wf_request_id = f"wf-{uuid.uuid4().hex[:12]}"
                    structlog.contextvars.bind_contextvars(
                        request_id=wf_request_id,
                        company_id=workflow.company_id,
                    )
                    try:
                        logger.info(f"Processing workflow: {workflow.name}")

                        # Execute workflow
                        self.engine.submit_workflow(workflow.company_id, workflow.name, workflow.definition_json)

                        # Brief pause between workflows
                        time.sleep(1)
                    finally:
                        structlog.contextvars.clear_contextvars()

            except Exception as e:
                logger.error(f"Error in workflow processing: {e}")
                time.sleep(5)  # Wait longer on error

    def get_status(self) -> dict:
        """Get worker status"""
        return {
            "running": self.running,
            "active_workflows": len(self.engine.current_workflows) if self.running else 0,
            "worker_thread_alive": self.worker_thread.is_alive() if self.worker_thread else False
        }
