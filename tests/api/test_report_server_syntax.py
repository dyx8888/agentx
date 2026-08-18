import ast
import json
from pathlib import Path
from types import SimpleNamespace


def test_report_server_module_ast_parses():
    root = Path(__file__).resolve().parents[2]
    source = root / "backend" / "app" / "mcp_servers" / "report_server.py"

    ast.parse(source.read_text(encoding="utf-8"))


def test_generate_strategy_suggestion_runs_without_f_string_syntax_error(monkeypatch):
    import app.mcp_servers.report_server as report_server

    class FakeModelGateway:
        def get_llm(self, _model_name):
            return SimpleNamespace(
                invoke=lambda _prompt: SimpleNamespace(content="local strategy summary")
            )

    monkeypatch.setattr(report_server, "get_model_gateway", lambda: FakeModelGateway())

    result = json.loads(report_server.generate_strategy_suggestion("xiaohongshu", "beauty"))

    assert result["status"] == "ok"
    assert "local strategy summary" in result["data"]
