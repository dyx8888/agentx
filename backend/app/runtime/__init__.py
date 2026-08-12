"""
Runtime Module - Agent core orchestration engine.

Keep exports lazy so importing runtime submodules for tests or static utilities does
not initialize the full AgentRuntime stack or external memory clients.
"""

__all__ = ["AgentRuntime"]


def __getattr__(name):
    if name == "AgentRuntime":
        from .orchestrator import AgentRuntime

        return AgentRuntime
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
