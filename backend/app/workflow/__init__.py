"""
Workflow Module
Provides A2A protocol standardization and workflow execution engine
"""

from .a2a_schema import A2AMessage, WorkflowDefinition, WorkflowNode

__all__ = [
    "A2AMessage",
    "WorkflowDefinition",
    "WorkflowEngine",
    "WorkflowNode",
]


def __getattr__(name: str):
    if name == "WorkflowEngine":
        from .engine import WorkflowEngine

        return WorkflowEngine
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
