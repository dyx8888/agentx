import ast
import re
from pathlib import Path


HTTP_METHODS = {"get", "post", "put", "patch", "delete"}
PATH_PARAM_RE = re.compile(r"{([^}:]+)(?::[^}]+)?}")

KNOWN_UNCONSTRAINED_STATIC_SIBLINGS = {
    ("conversations.py", "GET", "/{conversation_id}"),
}


def _api_files() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    api_root = root / "backend" / "app" / "api"
    files = sorted(path for path in api_root.rglob("*.py") if path.name != "__init__.py")
    files.append(root / "backend" / "app" / "workflow" / "api.py")
    return files


def _literal_string(node):
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _route_decorators():
    for path in _api_files():
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            function_args = {
                arg.arg
                for arg in [
                    *node.args.posonlyargs,
                    *node.args.args,
                    *node.args.kwonlyargs,
                ]
            }
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in HTTP_METHODS:
                    continue
                if not isinstance(func.value, ast.Name) or func.value.id != "router":
                    continue
                route_path = _literal_string(decorator.args[0]) if decorator.args else None
                if route_path is None:
                    for keyword in decorator.keywords:
                        if keyword.arg == "path":
                            route_path = _literal_string(keyword.value)
                            break
                if route_path is None:
                    continue
                yield {
                    "file": path,
                    "function": node.name,
                    "method": func.attr.upper(),
                    "path": route_path,
                    "function_args": function_args,
                }


def test_openapi_static_contract_has_no_duplicate_method_paths():
    routes = list(_route_decorators())
    seen = {}
    duplicates = []

    for route in routes:
        key = (route["file"], route["method"], route["path"])
        if key in seen:
            duplicates.append((route, seen[key]))
        seen[key] = route

    assert not duplicates, [
        (
            str(route["file"]),
            route["method"],
            route["path"],
            route["function"],
            previous["function"],
        )
        for route, previous in duplicates
    ]


def test_openapi_path_parameters_are_declared_in_endpoint_signatures():
    missing = []
    for route in _route_decorators():
        for param in PATH_PARAM_RE.findall(route["path"]):
            if param not in route["function_args"]:
                missing.append((str(route["file"]), route["method"], route["path"], param))

    assert not missing


def test_openapi_static_contract_rejects_unconstrained_id_routes_with_static_siblings():
    offenders = []
    routes = list(_route_decorators())
    by_file_method = {}
    for route in routes:
        by_file_method.setdefault((route["file"], route["method"]), []).append(route)

    for grouped_routes in by_file_method.values():
        static_prefixes = {
            route["path"].rsplit("/", 1)[0]
            for route in grouped_routes
            if "{" not in route["path"]
        }
        for route in grouped_routes:
            segments = route["path"].strip("/").split("/")
            if not segments or not segments[-1].startswith("{") or ":" in segments[-1]:
                continue
            param_name = PATH_PARAM_RE.findall(route["path"])[-1]
            if not param_name.endswith("_id") and param_name != "id":
                continue
            prefix = route["path"].rsplit("/", 1)[0]
            known_key = (route["file"].name, route["method"], route["path"])
            if prefix in static_prefixes and known_key not in KNOWN_UNCONSTRAINED_STATIC_SIBLINGS:
                offenders.append((str(route["file"]), route["method"], route["path"]))

    assert not offenders


def test_openapi_schema_includes_a2a_agents_route():
    from app.main import app

    paths = app.openapi()["paths"]

    assert "/api/a2a/agents" in paths
    assert "get" in paths["/api/a2a/agents"]


def test_openapi_schema_includes_feedback_stats_route():
    from app.main import app

    paths = app.openapi()["paths"]

    assert "/api/feedback/stats" in paths
    assert "get" in paths["/api/feedback/stats"]


def test_openapi_schema_includes_admin_companies_routes():
    from app.main import app

    paths = app.openapi()["paths"]

    assert "/api/admin/companies/" in paths
    assert "get" in paths["/api/admin/companies/"]
    assert "/api/admin/companies/{company_id}" in paths
    assert "get" in paths["/api/admin/companies/{company_id}"]
    assert "/api/admin/companies/{company_id}/credentials" in paths
    assert "get" in paths["/api/admin/companies/{company_id}/credentials"]
    assert "post" in paths["/api/admin/companies/{company_id}/credentials"]
    assert "/api/admin/companies/{company_id}/credentials/{platform}/verify" in paths
    assert (
        "post"
        in paths["/api/admin/companies/{company_id}/credentials/{platform}/verify"]
    )


def test_openapi_schema_includes_admin_evolution_report_route():
    from app.main import app

    paths = app.openapi()["paths"]

    assert "/api/admin/evolution/report" in paths
    assert "get" in paths["/api/admin/evolution/report"]


def test_openapi_schema_includes_pending_tasks_route():
    from app.main import app

    paths = app.openapi()["paths"]

    assert "/api/tasks/pending" in paths
    assert "get" in paths["/api/tasks/pending"]
