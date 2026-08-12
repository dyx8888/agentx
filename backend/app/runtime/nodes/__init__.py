"""
LangGraph runtime nodes.

Node exports are lazy to avoid importing every node and its dependencies when a
caller only needs one helper or node module.
"""

__all__ = ["planner_node", "executor_node", "reflector_node"]


def __getattr__(name):
    if name == "planner_node":
        from .planner_node import planner_node

        return planner_node
    if name == "executor_node":
        from .executor_node import executor_node

        return executor_node
    if name == "reflector_node":
        from .reflector_node import reflector_node

        return reflector_node
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
