from types import SimpleNamespace


def test_public_tool_capabilities_only_returns_shortcut_labels():
    from app.api.tools import get_public_tool_capabilities

    result = __import__("asyncio").run(
        get_public_tool_capabilities(SimpleNamespace(id=7, company_id=42))
    )

    assert result
    assert all(set(item) == {"key", "label"} for item in result)
    assert all("module" not in item and "function" not in item for item in result)
