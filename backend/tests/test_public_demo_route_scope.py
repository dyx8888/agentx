import ast
import importlib
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MAIN = ROOT / "backend" / "app" / "main.py"
PRODUCTION_ENV = ROOT / "backend" / ".env.production.example"


def _is_evolution_include_router_call(node: ast.Call) -> bool:
    if not isinstance(node.func, ast.Attribute):
        return False
    if node.func.attr != "include_router":
        return False
    if not node.args:
        return False
    first_arg = node.args[0]
    return isinstance(first_arg, ast.Name) and first_arg.id == "evolution_router"


class EvolutionRouterGuardVisitor(ast.NodeVisitor):
    def __init__(self) -> None:
        self._guard_depth = 0
        self.guarded_lines: list[int] = []
        self.unguarded_lines: list[int] = []

    def visit_If(self, node: ast.If) -> None:
        is_evolution_guard = isinstance(node.test, ast.Name) and node.test.id == "EVOLUTION_API_ENABLED"
        if is_evolution_guard:
            self._guard_depth += 1
        for child in node.body:
            self.visit(child)
        if is_evolution_guard:
            self._guard_depth -= 1
        for child in node.orelse:
            self.visit(child)

    def visit_Call(self, node: ast.Call) -> None:
        if _is_evolution_include_router_call(node):
            target = self.guarded_lines if self._guard_depth else self.unguarded_lines
            target.append(node.lineno)
        self.generic_visit(node)


def test_public_demo_production_disables_evolution_routes_by_default():
    source = MAIN.read_text(encoding="utf-8-sig")

    assert 'return _env_flag("ENABLE_EVOLUTION_API", default=not _is_production())' in source

    visitor = EvolutionRouterGuardVisitor()
    visitor.visit(ast.parse(source))

    assert visitor.guarded_lines, "evolution router must remain behind EVOLUTION_API_ENABLED"
    assert not visitor.unguarded_lines, (
        "evolution router is registered outside EVOLUTION_API_ENABLED guard: "
        f"{visitor.unguarded_lines}"
    )
    assert "ENABLE_EVOLUTION_API=false" in PRODUCTION_ENV.read_text(encoding="utf-8-sig")


def test_public_demo_chat_master_router_dependency_is_present():
    from app.api import chat
    from app.agents.master_router import MasterAgentRouter

    chat._master_router = None

    assert isinstance(chat._get_master_router(), MasterAgentRouter)


def test_public_demo_settings_backend_routes_are_registered():
    from app.main import app

    route_paths = {getattr(route, "path", "") for route in app.routes}

    assert "/api/platforms" in route_paths
    assert "/api/rag/embedding/config" in route_paths
    assert "/api/rag/company/profile" in route_paths


def test_public_demo_backend_runtime_dependencies_are_present():
    required_modules = [
        "app.communication.master_dispatcher",
        "app.core.circuit_breaker",
        "app.core.config",
        "app.mcp_servers.runtime",
        "app.rag.doc_status",
    ]

    for module_name in required_modules:
        assert importlib.import_module(module_name)


def test_public_demo_message_persistence_strips_internal_traces():
    from app.services.message_persistence import sanitize_user_visible_text

    visible = sanitize_user_visible_text(
        "[Action] RAG answer from knowledge base\n\n"
        "\u9762\u5411\u7528\u6237\u7684\u7b54\u6848"
    )
    internal_only = sanitize_user_visible_text("[Action] RAG answer from knowledge base")

    assert visible == "\u9762\u5411\u7528\u6237\u7684\u7b54\u6848"
    assert internal_only == "\u4efb\u52a1\u5df2\u5b8c\u6210"


def test_public_demo_websocket_invalid_json_is_explicit_error():
    import app.ws as ws_api

    assert ws_api._invalid_ws_message_payload() == {
        "type": "error",
        "code": "invalid_json",
        "message": "Invalid WebSocket message",
    }


def test_public_demo_websocket_auth_uses_token_identity(monkeypatch):
    from types import SimpleNamespace

    import app.ws as ws_api

    monkeypatch.setattr(ws_api, "decode_access_token", lambda token: {"sub": f"user-{token}"})
    monkeypatch.setattr(
        ws_api.db,
        "_instance",
        SimpleNamespace(
            get_user_by_username=lambda username: SimpleNamespace(
                id=42, username=username, disabled=False
            )
        ),
        raising=False,
    )

    websocket = SimpleNamespace(query_params={"token": "query-token", "user_id": "spoofed"}, cookies={})
    cookie_websocket = SimpleNamespace(query_params={}, cookies={"access_token": "cookie-token"})

    assert ws_api._authenticate_ws(websocket).username == "user-query-token"
    assert ws_api._authenticate_ws(cookie_websocket).username == "user-cookie-token"


def test_public_demo_logging_middleware_redacts_sensitive_urls():
    from app.middleware.logging import _redact_url

    redacted = _redact_url(
        "https://example.test/callback?token=abc123&api_key=secret-value&next=/chat"
    )

    assert "abc123" not in redacted
    assert "secret-value" not in redacted
    assert "token=***" in redacted
    assert "api_key=***" in redacted
    assert "next=/chat" in redacted


def test_public_demo_logging_middleware_hides_exception_detail():
    source = (ROOT / "backend" / "app" / "middleware" / "logging.py").read_text(
        encoding="utf-8-sig"
    )

    assert '{"error": "Internal server error"}' in source
    assert '"detail": str(e)' not in source


def test_public_demo_core_logging_redacts_user_payload_fields():
    from app.core.logging import _redact_sensitive

    event_dict = {
        "event": "model_response",
        "prompt": "customer secret request",
        "raw_content": "internal chain trace",
        "assistant_message": "visible answer",
        "api_key": "provider-key",
        "safe_count": 3,
    }

    redacted = _redact_sensitive(None, None, event_dict)

    assert redacted["event"] == "model_response"
    assert redacted["prompt"] == "[REDACTED]"
    assert redacted["raw_content"] == "[REDACTED]"
    assert redacted["assistant_message"] == "[REDACTED]"
    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["safe_count"] == 3
