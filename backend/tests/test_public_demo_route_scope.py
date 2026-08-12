import ast
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
