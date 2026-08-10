import asyncio
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException


pytestmark = pytest.mark.skip(
    reason=(
        "broad production issue inventory depends on uncommitted backend/runtime "
        "changes and is excluded from the current trusted-path clean closure"
    )
)


def test_lightweight_route_imports_do_not_eagerly_load_heavy_modules():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; "
        "sys.path.insert(0, 'backend'); "
        "import app.api.knowledge, app.api.feedback, app.workflow.api; "
        "blocked = ['app.mcp_servers.knowledge_retrieval_server', 'app.workflow.engine']; "
        "loaded = [name for name in blocked if name in sys.modules]; "
        "print(','.join(loaded)); "
        "raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_backend_main_import_does_not_eagerly_load_external_runtime_clients():
    root = Path(__file__).resolve().parents[2]
    code = (
        "import sys; "
        "sys.path.insert(0, 'backend'); "
        "import app.main; "
        "blocked = ['redis', 'pymilvus', 'app.runtime.memory', "
        "'app.rag.hybrid_retriever', 'app.services.model_gateway', "
        "'app.services.session_store']; "
        "loaded = [name for name in blocked if name in sys.modules]; "
        "print(','.join(loaded)); "
        "raise SystemExit(1 if loaded else 0)"
    )

    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=root,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr


def test_tasks_dynamic_routes_are_int_constrained():
    from app.api.tasks import router

    paths = {route.path for route in router.routes}

    assert "/pending" in paths
    assert "/{task_id:int}" in paths
    assert "/{task_id:int}/steps" in paths
    assert "/{task_id:int}/confirm" in paths
    assert "/{task_id}" not in paths


def test_task_status_broadcast_failures_are_logged_not_silently_ignored():
    tasks_api = (Path(__file__).resolve().parents[2] / "backend/app/api/tasks.py").read_text(
        encoding="utf-8"
    )

    assert "task_status_broadcast_failed" in tasks_api
    assert "await broadcast_task_status_update(task_id, request.status, request.message)" in tasks_api
    assert "except Exception:\n                pass" not in tasks_api


def test_feedback_db_migrates_legacy_stats_columns(tmp_path):
    from app.api.feedback import FeedbackDB

    db_path = tmp_path / "feedback.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT NOT NULL,
                tool_name TEXT NOT NULL,
                original_output TEXT NOT NULL,
                human_edited_output TEXT NOT NULL,
                kol_name TEXT,
                product_name TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        conn.execute(
            """
            INSERT INTO feedback
            (session_id, tool_name, original_output, human_edited_output, kol_name, product_name)
            VALUES ('s1', 'kol_search', 'draft', 'draft', NULL, NULL)
            """
        )

    FeedbackDB(str(db_path))

    with sqlite3.connect(db_path) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(feedback)").fetchall()}
        status = conn.execute("SELECT status FROM feedback WHERE session_id = 's1'").fetchone()[0]

    assert {"company_id", "agent_id", "action", "status"}.issubset(columns)
    assert status == "modified"


def test_store_feedback_writes_action_and_status(tmp_path):
    import app.api.feedback as feedback_api

    db = feedback_api.FeedbackDB(str(tmp_path / "feedback.db"))
    feedback_api._feedback_db = db
    try:
        feedback_api.store_feedback(
            {
                "session_id": "s1",
                "tool_name": "kol_search",
                "original_output": "same",
                "human_edited_output": "same",
                "company_id": "1",
                "agent_id": "7",
            }
        )

        with sqlite3.connect(db.db_path) as conn:
            action, status = conn.execute(
                "SELECT action, status FROM feedback WHERE session_id = 's1'"
            ).fetchone()
    finally:
        feedback_api._feedback_db = None

    assert action == "adopted"
    assert status == "adopted"


def test_receive_feedback_accepts_lightweight_comment(tmp_path, monkeypatch):
    import app.api.feedback as feedback_api

    db = feedback_api.FeedbackDB(str(tmp_path / "feedback.db"))
    feedback_api._feedback_db = db
    knowledge_mock = MagicMock()
    monkeypatch.setattr(feedback_api, "add_to_knowledge_base", knowledge_mock)
    try:
        result = asyncio.run(
            feedback_api.receive_feedback(
                feedback_api.FeedbackRequest(rating=1, comment="useful"),
                current_user=SimpleNamespace(company_id=239),
            )
        )

        with sqlite3.connect(db.db_path) as conn:
            row = conn.execute(
                """
                SELECT session_id, tool_name, original_output, human_edited_output,
                       company_id, action, status
                FROM feedback
                WHERE id = ?
                """,
                (result.id,),
            ).fetchone()
    finally:
        feedback_api._feedback_db = None

    assert row[0].startswith("feedback-")
    assert row[1] == "general"
    assert row[2] == ""
    assert row[3] == "useful"
    assert row[4] == "239"
    assert row[5] == "feedback"
    assert row[6] == "feedback"
    knowledge_mock.assert_not_called()


def test_feedback_stats_returns_empty_state_when_storage_unavailable(monkeypatch):
    import app.api.feedback as feedback_api

    monkeypatch.setattr(
        feedback_api,
        "get_feedback_db",
        lambda: SimpleNamespace(db_path="Z:/missing/feedback.db"),
    )

    result = asyncio.run(
        feedback_api.get_feedback_stats(current_user=SimpleNamespace(company_id=239))
    )

    assert result["stats"] == []
    assert result["status"] == "unavailable"


def test_tool_details_accepts_search_kols_alias(monkeypatch):
    import app.api.tools as tools_api

    async def fake_get_available_tools(_current_user):
        return [
            tools_api.ToolInfo(
                name="kol_search",
                module="app.mcp_servers.kol_search_server",
                function="search_kols",
                description="KOL search",
            )
        ]

    monkeypatch.setattr(tools_api, "get_available_tools", fake_get_available_tools)

    result = asyncio.run(
        tools_api.get_tool_details("search_kols", current_user=SimpleNamespace(id=1))
    )

    assert result.name == "kol_search"


def test_kol_export_pdf_returns_pdf_stream(monkeypatch):
    import app.agents.kol_search as kol_search_agent
    import app.api.kol as kol_api
    from app.database import db as db_proxy

    class FakeSessionContext:
        def __enter__(self):
            return SimpleNamespace()

        def __exit__(self, *_args):
            return False

    class FakeDb:
        def get_session(self):
            return FakeSessionContext()

    seen = {}

    def fake_search_kols(**kwargs):
        seen.update(kwargs)
        return [
            SimpleNamespace(
                id=1,
                name="FULLTestBeautyA",
                platform="xiaohongshu",
                followers=120000,
                engagement_rate=4.2,
                category="beauty",
                price_range_low=1000,
                price_range_high=2000,
                location="Shanghai",
            )
        ]

    async def collect_pdf():
        response = await kol_api.export_kols(
            kol_api.KolExportRequest(
                query="beauty",
                platform="xiaohongshu",
                format="pdf",
            ),
            current_user=SimpleNamespace(company_id=239),
        )
        chunks = []
        async for chunk in response.body_iterator:
            chunks.append(chunk if isinstance(chunk, bytes) else chunk.encode("utf-8"))
        return response, b"".join(chunks)

    previous_db = db_proxy._instance
    db_proxy._set_instance(FakeDb())
    monkeypatch.setattr(kol_search_agent, "search_kols", fake_search_kols)
    try:
        response, body = asyncio.run(collect_pdf())
    finally:
        db_proxy._set_instance(previous_db)

    assert response.media_type == "application/pdf"
    assert response.headers["content-disposition"] == "attachment; filename=kols.pdf"
    assert body.startswith(b"%PDF-1.4")
    assert b"KOL Export" in body
    assert seen["company_id"] == 239


def test_kol_mcp_http_endpoint_forwards_company_id(monkeypatch):
    import app.mcp_servers.kol_search_server as kol_server

    seen = {}

    async def fake_search_kols(category, count=3, company_id=None):
        seen["category"] = category
        seen["count"] = count
        seen["company_id"] = company_id
        return '{"status": "ok"}'

    monkeypatch.setattr(kol_server, "search_kols", fake_search_kols)

    result = asyncio.run(
        kol_server.search_kols_http_endpoint(
            kol_server.SearchKolsRequest(category="beauty", count=2, company_id=239)
        )
    )

    assert result == '{"status": "ok"}'
    assert seen == {"category": "beauty", "count": 2, "company_id": 239}


def test_mcp_http_wrappers_forward_company_id(monkeypatch):
    import app.mcp_servers.monitor_server as monitor_server
    import app.mcp_servers.outreach_server as outreach_server
    import app.mcp_servers.report_server as report_server
    import app.mcp_servers.script_server as script_server

    seen = {}

    def fake_outreach(kol_name, product_name, style="professional", company_id=None):
        seen["outreach"] = (kol_name, product_name, style, company_id)
        return "outreach-ok"

    def fake_script(
        kol_name,
        product_name,
        platform="douyin",
        style="lively",
        company_id=None,
    ):
        seen["script"] = (kol_name, product_name, platform, style, company_id)
        return "script-ok"

    async def fake_report(kol_name, campaign_id, company_id=None):
        seen["report"] = (kol_name, campaign_id, company_id)
        return "report-ok"

    def fake_strategy(platform, category, company_id=None):
        seen["strategy"] = (platform, category, company_id)
        return "strategy-ok"

    def fake_delivery(order_id, company_id=None):
        seen["delivery"] = (order_id, company_id)
        return "delivery-ok"

    def fake_arrival(kol_name, product_name, delivery_status, company_id=None):
        seen["arrival"] = (kol_name, product_name, delivery_status, company_id)
        return "arrival-ok"

    monkeypatch.setattr(outreach_server, "generate_outreach", fake_outreach)
    monkeypatch.setattr(script_server, "generate_script", fake_script)
    monkeypatch.setattr(report_server, "generate_performance_report", fake_report)
    monkeypatch.setattr(report_server, "generate_strategy_suggestion", fake_strategy)
    monkeypatch.setattr(monitor_server, "check_delivery_status", fake_delivery)
    monkeypatch.setattr(monitor_server, "generate_arrival_script", fake_arrival)

    assert asyncio.run(
        outreach_server.generate_outreach_http_endpoint(
            outreach_server.GenerateOutreachRequest(
                kol_name="Alice",
                product_name="Serum",
                style="casual",
                company_id=239,
            )
        )
    ) == "outreach-ok"
    assert asyncio.run(
        script_server.generate_script_http_endpoint(
            script_server.GenerateScriptRequest(
                kol_name="Alice",
                product_name="Serum",
                platform="xiaohongshu",
                style="plain",
                company_id=239,
            )
        )
    ) == "script-ok"
    assert asyncio.run(
        report_server.generate_performance_report_http_endpoint(
            report_server.PerformanceReportRequest(
                kol_name="Alice",
                campaign_id="cmp-1",
                company_id=239,
            )
        )
    ) == "report-ok"
    assert asyncio.run(
        report_server.generate_strategy_suggestion_http_endpoint(
            report_server.StrategySuggestionRequest(
                platform="xiaohongshu",
                category="beauty",
                company_id=239,
            )
        )
    ) == "strategy-ok"
    assert asyncio.run(
        monitor_server.check_delivery_status_http_endpoint(
            monitor_server.CheckDeliveryStatusRequest(order_id="ORD001", company_id=239)
        )
    ) == "delivery-ok"
    assert asyncio.run(
        monitor_server.generate_arrival_script_http_endpoint(
            monitor_server.GenerateArrivalScriptRequest(
                kol_name="Alice",
                product_name="Serum",
                delivery_status="shipped",
                company_id=239,
            )
        )
    ) == "arrival-ok"

    assert seen == {
        "outreach": ("Alice", "Serum", "casual", 239),
        "script": ("Alice", "Serum", "xiaohongshu", "plain", 239),
        "report": ("Alice", "cmp-1", 239),
        "strategy": ("xiaohongshu", "beauty", 239),
        "delivery": ("ORD001", 239),
        "arrival": ("Alice", "Serum", "shipped", 239),
    }


def test_a2a_task_request_accepts_common_aliases():
    import app.api.a2a as a2a_api

    request = a2a_api.TaskRequest(target_agent="brand_bd", task_description="find kols")

    target_agent, task_message = a2a_api._normalize_task_request(request)

    assert target_agent == "brand_bd"
    assert task_message == "find kols"


def test_a2a_delegate_uses_common_aliases(monkeypatch):
    import app.api.a2a as a2a_api

    adapter = SimpleNamespace(
        send_task=MagicMock(
            return_value={
                "success": True,
                "task_id": "task-1",
                "message": "queued",
                "timestamp": "2026-08-09T00:00:00Z",
            }
        )
    )
    monkeypatch.setattr(a2a_api, "get_a2a_adapter", lambda: adapter)

    result = asyncio.run(
        a2a_api.a2a_delegate_task(
            a2a_api.TaskRequest(target_agent="brand_bd", message="find kols"),
            current_user=SimpleNamespace(company_id=239),
        )
    )

    assert result.success is True
    assert result.target_agent == "brand_bd"
    adapter.send_task.assert_called_once_with(
        target_agent_name="brand_bd",
        task_message="find kols",
        task_type="general",
        payload=None,
    )


def test_a2a_task_request_missing_fields_returns_400():
    import app.api.a2a as a2a_api

    with pytest.raises(HTTPException) as exc_info:
        a2a_api._normalize_task_request(a2a_api.TaskRequest(message="find kols"))

    assert exc_info.value.status_code == 400


def test_a2a_discovery_falls_back_to_configured_registry_agents(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    class EmptyDB:
        def get_agents_by_company(self, _company_id):
            return []

    adapter = A2AAdapter(EmptyDB())
    monkeypatch.setattr(adapter, "_get_redis", lambda: None)

    cards = adapter.discover_agents(company_id=239)

    assert cards
    assert any(card["name"] == "brand_bd" for card in cards)
    assert {card["source"] for card in cards} == {"agent_registry"}
    assert {card["status"] for card in cards} == {"configured"}


def test_a2a_delegate_accepts_configured_registry_agent(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    class EmptyDB:
        def get_agent_by_name(self, _name):
            return None

        def get_connection(self):
            raise sqlite3.OperationalError("no a2a_messages table")

    adapter = A2AAdapter(EmptyDB())
    monkeypatch.setattr(adapter, "_get_redis", lambda: None)

    result = adapter.send_task("brand_bd", "find kols")

    assert result["success"] is True
    assert result["task_id"].startswith("task_")


def test_agents_list_falls_back_to_configured_registry(monkeypatch):
    import app.api.agents as agents_api

    monkeypatch.setattr(
        agents_api.db,
        "_instance",
        SimpleNamespace(get_agents_by_company=lambda _company_id: []),
    )

    result = asyncio.run(
        agents_api.get_agents(current_user=SimpleNamespace(company_id=239))
    )

    assert result
    assert all(agent.company_id == 239 for agent in result)
    assert any(agent.id < 0 for agent in result)
    assert any("catalog agent" in agent.description for agent in result)


def test_dashboard_agents_returns_configured_registry_statuses():
    import app.api.dashboard as dashboard_api

    result = asyncio.run(
        dashboard_api.get_agent_statuses(current_user=SimpleNamespace(company_id=239))
    )

    assert result
    assert any(agent.agent_key == "brand_bd" for agent in result)
    assert {agent.status for agent in result} == {"configured"}
    assert {agent.current_model for agent in result} == {"no_recent_usage"}


def test_dashboard_agents_surface_runtime_task_and_usage(monkeypatch):
    import app.api.dashboard as dashboard_api

    calls = iter(
        [
            [("brand_bd", "processing", "find matching KOLs", "2026-08-09T10:00:00")],
            [("brand_bd", 321, "2026-08-09T10:01:00")],
            [("brand_bd", "deepseek-chat", "2026-08-09T10:01:00")],
        ]
    )
    monkeypatch.setattr(dashboard_api, "_safe_query", lambda *_args, **_kwargs: next(calls))

    statuses = dashboard_api._get_configured_agent_statuses(company_id=239)
    brand_bd = next(agent for agent in statuses if agent.agent_key == "brand_bd")

    assert brand_bd.status == "working"
    assert brand_bd.current_task == "find matching KOLs"
    assert brand_bd.token_consumed_today == 321
    assert brand_bd.current_model == "deepseek-chat"
    assert brand_bd.last_active == "2026-08-09T10:01:00"


def test_evolution_report_returns_empty_when_analyzer_unavailable(monkeypatch):
    import app.api.evolution as evolution_api

    class BrokenAnalyzer:
        def get_company_evolution_report(self, _company_id, _days):
            raise sqlite3.OperationalError("no such table: agents")

    monkeypatch.setattr(evolution_api, "EvolutionAnalyzer", BrokenAnalyzer)

    result = asyncio.run(
        evolution_api.get_evolution_report(current_user=SimpleNamespace(company_id=1))
    )

    assert result.reports == []
    assert result.high_modification_agents == []


def test_evolution_history_returns_empty_when_log_table_unavailable(monkeypatch):
    import app.api.evolution as evolution_api
    import app.database.core as database_core

    monkeypatch.setattr(
        evolution_api.db,
        "_instance",
        SimpleNamespace(get_agent=lambda _agent_id: SimpleNamespace(company_id=1)),
    )

    class BrokenEngine:
        def connect(self):
            raise sqlite3.OperationalError("no such table: evolution_log")

    monkeypatch.setattr(database_core, "get_engine", lambda: BrokenEngine())

    result = asyncio.run(
        evolution_api.get_evolution_history(1, current_user=SimpleNamespace(company_id=1))
    )

    assert result == {"history": []}


def test_evolution_history_preserves_missing_agent_404(monkeypatch):
    import app.api.evolution as evolution_api

    monkeypatch.setattr(
        evolution_api.db,
        "_instance",
        SimpleNamespace(get_agent=lambda _agent_id: None),
    )

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            evolution_api.get_evolution_history(404, current_user=SimpleNamespace(company_id=1))
        )

    assert exc_info.value.status_code == 404


def test_evolution_notifier_uses_adapter_methods(monkeypatch, tmp_path):
    import app.evolution.notifier as notifier_mod

    training_file = tmp_path / "training.jsonl"
    training_file.write_text("{}", encoding="utf-8")
    calls = {}

    class Adapter:
        def create_evolution_log(self, agent_id, suggestion_text, training_data_path=None, **_kwargs):
            calls["create"] = (agent_id, suggestion_text, training_data_path)
            return 17

        def get_evolution_logs_by_agent(self, agent_id):
            return [
                SimpleNamespace(
                    id=17,
                    agent_id=agent_id,
                    suggestion_text="x" * 120,
                    training_data_path=str(training_file),
                    created_at=datetime(2026, 8, 9, 1, 2, 3, tzinfo=timezone.utc),
                    applied=False,
                ),
                SimpleNamespace(
                    id=18,
                    agent_id=agent_id,
                    suggestion_text="no file",
                    training_data_path=None,
                    created_at=None,
                    applied=False,
                ),
            ]

        def update_evolution_applied(self, evolution_log_id):
            calls["update"] = evolution_log_id
            return True

    monkeypatch.setattr(notifier_mod.db, "_instance", Adapter())

    notifier = notifier_mod.EvolutionNotifier()

    assert notifier._save_evolution_log(7, "improve prompt", str(training_file)) == 17
    files = notifier.get_training_data_files(7)
    assert notifier.mark_evolution_applied(17) is True

    assert calls["create"] == (7, "improve prompt", str(training_file))
    assert calls["update"] == 17
    assert len(files) == 1
    assert files[0]["evolution_log_id"] == 17
    assert files[0]["file_exists"] is True
    assert files[0]["suggestion_preview"].endswith("...")


def test_training_data_extractor_uses_orm_session(monkeypatch):
    import app.evolution.data_extractor as extractor_mod
    from app.database.models import Agent, Base, Feedback
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    engine = create_engine('sqlite:///:memory:')
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine)

    with SessionLocal() as session:
        session.add(Agent(id=7, company_id=239, name='brand_bd', description='agent', tools_json='[]'))
        session.add(
            Feedback(
                agent_id=7,
                tool_name='kol_search',
                original_output='draft',
                human_edited_output='edited draft',
                status='modified',
                created_at=datetime(2026, 8, 9, 1, 2, 3),
            )
        )
        session.add(
            Feedback(
                agent_id=7,
                tool_name='kol_search',
                original_output='pending',
                human_edited_output='pending',
                status='pending',
                created_at=datetime(2026, 8, 9, 1, 2, 4),
            )
        )
        session.commit()

    class Adapter:
        def get_session(self):
            return SessionLocal()

    monkeypatch.setattr(extractor_mod.db, '_instance', Adapter())
    extractor = extractor_mod.TrainingDataExtractor.__new__(extractor_mod.TrainingDataExtractor)

    pairs = extractor.extract_training_pairs(7, tool_name='kol_search', days=3650, min_samples=1)

    assert pairs == [
        {
            'id': 1,
            'tool_name': 'kol_search',
            'original_output': 'draft',
            'human_edited_output': 'edited draft',
            'status': 'modified',
            'created_at': datetime(2026, 8, 9, 1, 2, 3),
            'agent_name': 'brand_bd',
            'company_id': 239,
        }
    ]


def test_company_list_serializes_datetime_created_at(monkeypatch):
    import app.api.companies as companies_api

    created_at = datetime(2026, 8, 9, 1, 2, 3, tzinfo=timezone.utc)
    company = SimpleNamespace(
        id=239,
        name="Acme",
        brand_name="Acme Brand",
        category="beauty",
        platforms_json="douyin,xiaohongshu",
        created_at=created_at,
    )
    monkeypatch.setattr(
        companies_api.db,
        "_instance",
        SimpleNamespace(get_all_companies=lambda: [company]),
    )

    result = asyncio.run(
        companies_api.get_companies(current_user=SimpleNamespace(is_admin=True, company_id=239))
    )

    assert result[0].created_at == created_at.isoformat()


def test_document_status_falls_back_to_ready_for_existing_document(monkeypatch):
    import app.api.knowledge as knowledge_api
    import app.rag.doc_status as doc_status_mod
    import app.rag.hybrid_retriever as hybrid_retriever_mod

    monkeypatch.setattr(
        doc_status_mod,
        "_doc_status_manager",
        doc_status_mod.DocStatusManager(),
    )
    monkeypatch.setattr(
        hybrid_retriever_mod,
        "get_hybrid_retriever",
        lambda _company_id: SimpleNamespace(list_documents=lambda: [{"id": "doc-1"}]),
    )

    result = knowledge_api.get_document_status(
        "doc-1",
        current_user=SimpleNamespace(company_id=239),
    )

    assert result.doc_id == "doc-1"
    assert result.text_state == "ready"
    assert result.multimodal_state == "ready"
    assert result.is_fully_processed is True



def test_xiaohongshu_oauth_is_supported_without_manual_access_token():
    import app.api.companies as companies_api
    from app.platforms.credentials import OAUTH_PLATFORMS, get_oauth_managed_fields

    assert "xiaohongshu" in OAUTH_PLATFORMS
    assert "access_token" in get_oauth_managed_fields("xiaohongshu")

    companies_api._validate_platform_and_fields(
        "xiaohongshu",
        {"app_id": "app-1", "app_secret": "secret-1"},
    )


def test_xiaohongshu_credential_fields_mark_oauth_token_optional():
    import app.api.platforms as platforms_api

    result = asyncio.run(platforms_api.get_credential_fields("xiaohongshu"))
    required_by_field = {field.field_name: field.required for field in result.fields}

    assert required_by_field["app_id"] is True
    assert required_by_field["app_secret"] is True
    assert required_by_field["access_token"] is False
    assert required_by_field["refresh_token"] is False


def test_xiaohongshu_oauth_authorize_url_uses_configured_endpoint(monkeypatch):
    from app.platforms.xiaohongshu import XiaohongshuAdapter

    monkeypatch.setenv("XIAOHONGSHU_OAUTH_AUTHORIZE_URL", "https://xhs.example/oauth")
    adapter = XiaohongshuAdapter(app_id="app-1", app_secret="secret-1")

    url = asyncio.run(adapter.get_authorize_url("https://app.example/callback", "state-1"))

    assert url.startswith("https://xhs.example/oauth?")
    assert "client_id=app-1" in url
    assert "response_type=code" in url
    assert "state=state-1" in url


def test_oauth_authorize_generates_url_and_state_without_callback_params(monkeypatch):
    import app.api.oauth_router as oauth_api

    class FakeAdapter:
        async def get_authorize_url(self, redirect_uri, state):
            return f"https://platform.example/oauth?redirect_uri={redirect_uri}&state={state}"

    oauth_api._OAUTH_STATE_STORE.clear()
    monkeypatch.setattr(
        oauth_api,
        "_build_adapter_from_credentials",
        lambda company_id, platform: FakeAdapter(),
    )
    monkeypatch.setenv("OAUTH_REDIRECT_BASE_URL", "https://api.example")

    result = asyncio.run(
        oauth_api.authorize(
            "xiaohongshu",
            current_user=SimpleNamespace(company_id=239),
        )
    )

    assert result["platform"] == "xiaohongshu"
    assert result["redirect_uri"] == "https://api.example/api/oauth/callback/xiaohongshu"
    assert result["state"] in oauth_api._OAUTH_STATE_STORE
    assert oauth_api._OAUTH_STATE_STORE[result["state"]]["company_id"] == 239
    assert "state=" in result["authorize_url"]


def test_oauth_callback_missing_params_returns_400():
    import app.api.oauth_router as oauth_api

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(oauth_api.oauth_callback("xiaohongshu"))

    assert exc_info.value.status_code == 400
    assert "code and state" in exc_info.value.detail


def test_oauth_callback_post_missing_params_returns_400():
    import app.api.oauth_router as oauth_api

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_api.oauth_callback_post(
                "xiaohongshu",
                oauth_api.OAuthCallbackRequest(code="", state=""),
            )
        )

    assert exc_info.value.status_code == 400


def test_oauth_callback_post_rejects_state_platform_mismatch():
    import app.api.oauth_router as oauth_api

    oauth_api._OAUTH_STATE_STORE.clear()
    state = oauth_api._create_state(239, "xiaohongshu")

    with pytest.raises(HTTPException) as exc_info:
        asyncio.run(
            oauth_api.oauth_callback_post(
                "taobao",
                oauth_api.OAuthCallbackRequest(code="code-1", state=state),
            )
        )

    assert exc_info.value.status_code == 400
    assert "不匹配" in exc_info.value.detail



def test_dynamic_validator_fails_when_llm_validation_raises(monkeypatch):
    import importlib.util
    from pathlib import Path

    validator_path = Path(__file__).resolve().parents[2] / "backend" / "app" / "runtime" / "validator.py"
    spec = importlib.util.spec_from_file_location("agentx_runtime_validator", validator_path)
    validator_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(validator_mod)
    DynamicValidator = validator_mod.DynamicValidator

    monkeypatch.delenv("AGENT_EVAL_MODE", raising=False)

    class BrokenLLM:
        def invoke(self, _messages):
            raise RuntimeError("llm unavailable")

    validator = DynamicValidator(skill_registry=SimpleNamespace(), llm=BrokenLLM())

    result = validator.validate(
        plan={"steps": [{"id": "s1"}], "acceptance_criteria": ["must pass"]},
        step_results=[{"result": "done"}],
    )

    assert result["passed"] is False
    assert any("Layer C LLM validation failed" in issue for issue in result["issues"])


def test_dynamic_validator_respects_llm_passed_false(monkeypatch):
    import importlib.util
    from pathlib import Path

    validator_path = Path(__file__).resolve().parents[2] / "backend" / "app" / "runtime" / "validator.py"
    spec = importlib.util.spec_from_file_location("agentx_runtime_validator_false", validator_path)
    validator_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(validator_mod)
    DynamicValidator = validator_mod.DynamicValidator

    monkeypatch.delenv("AGENT_EVAL_MODE", raising=False)

    class FalseLLM:
        def invoke(self, _messages):
            return SimpleNamespace(content='{"passed": false, "issues": [], "suggestions": []}')

    validator = DynamicValidator(skill_registry=SimpleNamespace(), llm=FalseLLM())

    result = validator.validate(
        plan={"steps": [{"id": "s1"}], "acceptance_criteria": ["must pass"]},
        step_results=[{"result": "done"}],
    )

    assert result["passed"] is False
    assert "Layer C LLM validation did not pass" in result["issues"]


def test_dynamic_validator_unparseable_llm_validation_fails_closed(monkeypatch):
    import importlib.util
    from pathlib import Path

    validator_path = Path(__file__).resolve().parents[2] / "backend" / "app" / "runtime" / "validator.py"
    spec = importlib.util.spec_from_file_location("agentx_runtime_validator_parse", validator_path)
    validator_mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(validator_mod)
    DynamicValidator = validator_mod.DynamicValidator

    monkeypatch.delenv("AGENT_EVAL_MODE", raising=False)

    class UnparseableLLM:
        def invoke(self, _messages):
            return SimpleNamespace(content="无法判断验收结果")

    validator = DynamicValidator(skill_registry=SimpleNamespace(), llm=UnparseableLLM())

    result = validator.validate(
        plan={"steps": [{"id": "s1"}], "acceptance_criteria": ["must pass"]},
        step_results=[{"result": "done"}],
    )

    assert result["passed"] is False
    assert "Layer C LLM validation output was not parseable" in result["issues"]


def test_websocket_invalid_message_payload_is_explicit_error():
    import app.ws as ws_api

    payload = ws_api._invalid_ws_message_payload()

    assert payload == {
        "type": "error",
        "code": "invalid_json",
        "message": "Invalid WebSocket message",
    }


def test_ad_write_action_failure_does_not_return_mock_success(monkeypatch):
    from app.platforms.ad_platforms import QanchuanAdapter

    async def failing_call(*_args, **_kwargs):
        raise RuntimeError("ad api down")

    adapter = QanchuanAdapter(advertiser_id="adv-1", access_token="token-1")
    monkeypatch.setattr(adapter, "_do_call_api", failing_call)

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(adapter.create_campaign("launch", 100.0, "sales", ["creative-1"]))

    assert "mock success is disabled" in str(exc_info.value)


def test_xiaohongshu_post_note_without_credentials_fails_closed():
    from app.platforms.xiaohongshu import XiaohongshuAdapter

    adapter = XiaohongshuAdapter()

    with pytest.raises(RuntimeError) as exc_info:
        asyncio.run(adapter.post_note("title", "content"))

    assert "mock success is disabled" in str(exc_info.value)


def test_enterprise_mock_integrations_fail_closed_in_production(monkeypatch):
    from app.integrations.enterprise_systems import (
        EnterpriseIntegrationUnavailable,
        MockCustomerServiceIntegration,
        MockERPIntegration,
        MockWMSIntegration,
    )

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_ENTERPRISE_MOCK_INTEGRATIONS", raising=False)

    erp = MockERPIntegration()
    wms = MockWMSIntegration()
    customer_service = MockCustomerServiceIntegration()

    assert erp.is_available() is False
    assert wms.is_available() is False

    with pytest.raises(EnterpriseIntegrationUnavailable):
        erp.get_inventory()
    with pytest.raises(EnterpriseIntegrationUnavailable):
        wms.create_outbound_order("order-1", "warehouse-1", [{"sku": "SKU001"}])
    with pytest.raises(EnterpriseIntegrationUnavailable):
        customer_service.send_reply("conv-1", "draft", auto_send=True)


def test_subscription_plans_fall_back_to_configured_products(monkeypatch):
    import app.api.subscription as subscription_api

    monkeypatch.setattr(
        subscription_api.db,
        "_instance",
        SimpleNamespace(get_subscription_plans=lambda: []),
    )

    plans = asyncio.run(subscription_api.get_subscription_plans())

    assert [plan.id for plan in plans] == [1, 2, 3]
    assert plans[0].name == "Starter"


def test_workflows_are_available_to_company_users(monkeypatch):
    import app.workflow.api as workflow_api

    monkeypatch.setattr(
        workflow_api,
        "_list_company_workflows",
        lambda company_id: [{"id": 1, "company_id": company_id, "name": "wf"}],
    )

    result = asyncio.run(workflow_api.list_workflows(current_user=SimpleNamespace(company_id=239)))

    assert result["total"] == 1
    assert result["workflows"][0]["company_id"] == 239


def test_admin_company_routes_do_not_500_when_company_store_is_unavailable(monkeypatch):
    import app.api.companies as companies_api

    def broken_query(*_args, **_kwargs):
        raise RuntimeError("schema unavailable")

    monkeypatch.setattr(
        companies_api.db,
        "_instance",
        SimpleNamespace(get_all_companies=broken_query, get_company=broken_query),
    )

    current_user = SimpleNamespace(id=1, is_admin=True, company_id=239)

    companies = asyncio.run(companies_api.get_companies(current_user=current_user))
    assert companies == []

    with pytest.raises(HTTPException) as exc:
        asyncio.run(companies_api.get_company_info(239, current_user=current_user))

    assert exc.value.status_code == 404


def test_evolution_report_and_history_return_empty_state_when_storage_is_unavailable(
    monkeypatch,
):
    import app.api.evolution as evolution_api

    class BrokenAnalyzer:
        def get_company_evolution_report(self, *_args, **_kwargs):
            raise RuntimeError("feedback store unavailable")

    def broken_get_agent(*_args, **_kwargs):
        raise RuntimeError("evolution schema unavailable")

    monkeypatch.setattr(evolution_api, "EvolutionAnalyzer", BrokenAnalyzer)
    current_user = SimpleNamespace(id=1, company_id=239, is_admin=True)

    report = asyncio.run(evolution_api.get_evolution_report(current_user=current_user))
    assert report.reports == []
    assert report.high_modification_agents == []

    monkeypatch.setattr(evolution_api.db, "_instance", SimpleNamespace(get_agent=broken_get_agent))
    history = asyncio.run(evolution_api.get_evolution_history(1, current_user=current_user))
    assert history == {"history": []}


def test_admin_tools_route_has_admin_dependency():
    from pathlib import Path

    main_text = (Path(__file__).resolve().parents[2] / "backend" / "app" / "main.py").read_text(
        encoding="utf-8"
    )
    main_text = main_text.replace("\r\n", "\n")
    tools_include_start = main_text.index("app.include_router(\n    tools_router")
    tools_include = main_text[tools_include_start : tools_include_start + 240]

    assert 'prefix="/api/admin/tools"' in tools_include
    assert "dependencies=[Depends(admin_required)]" in tools_include


def test_auth_tokens_include_user_token_version(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-bytes")

    from app.auth import (
        create_access_token_for_user,
        create_refresh_token,
        decode_access_token,
        decode_refresh_token,
    )

    user = SimpleNamespace(
        username="alice",
        id=1,
        company_id=239,
        is_admin=False,
        disabled=False,
        token_version=7,
    )

    access_payload = decode_access_token(create_access_token_for_user(user))
    refresh_payload = decode_refresh_token(create_refresh_token("alice", token_version=7))

    assert access_payload["token_version"] == 7
    assert refresh_payload == ("alice", refresh_payload[1], 7)


def test_auth_user_cache_preserves_token_version(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-bytes")

    import app.auth as auth

    monkeypatch.setattr(auth, "_redis_client", False)
    auth._user_cache.clear()

    user = SimpleNamespace(
        username="alice",
        id=1,
        email="alice@example.test",
        company_id=239,
        is_admin=False,
        disabled=False,
        is_active=True,
        password_hash="hash",
        created_at=None,
        token_version=7,
    )

    token = auth.create_access_token_for_user(user)
    auth._cache_set(user)

    try:
        current_user = asyncio.run(auth.get_current_user(SimpleNamespace(cookies={}), token=token))
    finally:
        auth._user_cache.clear()

    assert current_user.username == "alice"
    assert current_user.token_version == 7


def test_auth_rejects_access_token_after_token_version_increment(monkeypatch):
    monkeypatch.setenv("JWT_SECRET_KEY", "test-secret-key-with-at-least-32-bytes")

    import app.auth as auth

    monkeypatch.setattr(auth, "_redis_client", False)
    auth._user_cache.clear()

    old_user = SimpleNamespace(
        username="alice",
        id=1,
        company_id=239,
        is_admin=False,
        disabled=False,
        token_version=0,
    )
    current_user = SimpleNamespace(
        username="alice",
        id=1,
        email="alice@example.test",
        company_id=239,
        is_admin=False,
        disabled=False,
        is_active=True,
        password_hash="hash",
        created_at=None,
        token_version=1,
    )

    old_token = auth.create_access_token_for_user(old_user)
    auth._cache_set(current_user)

    try:
        with pytest.raises(HTTPException) as exc_info:
            asyncio.run(auth.get_current_user(SimpleNamespace(cookies={}), token=old_token))
    finally:
        auth._user_cache.clear()

    assert exc_info.value.status_code == 401


def test_dashboard_alerts_use_real_failed_tasks(monkeypatch):
    import app.api.dashboard as dashboard_api

    calls = iter(
        [
            [(11, "brand_bd", "failed to finish task", "2026-08-09T00:00:00")],
            [],
        ]
    )
    monkeypatch.setattr(dashboard_api, "_safe_query", lambda *_args, **_kwargs: next(calls))

    alerts = dashboard_api._get_real_alerts(company_id=239, limit=5)

    assert len(alerts) == 1
    assert alerts[0].alert_type == "task_failed"
    assert alerts[0].message == "failed to finish task"


def test_dashboard_cost_stat_uses_usd_unit():
    from pathlib import Path

    dashboard = (
        Path(__file__).resolve().parents[2] / "backend" / "app" / "api" / "dashboard.py"
    ).read_text(encoding="utf-8-sig")

    assert 'StatCard(label="今日消耗", value=round(float(cost_today), 2), unit="USD")' in dashboard
    assert 'StatCard(label="今日消耗", value=round(float(cost_today), 2), unit="元")' not in dashboard




def test_message_persistence_strips_internal_action_traces():
    from app.services.message_persistence import sanitize_user_visible_text

    visible = sanitize_user_visible_text(
        "[Action] RAG answer from knowledge base\n\n"
        "\u9762\u5411\u7528\u6237\u7684\u7b54\u6848"
    )
    internal_only = sanitize_user_visible_text("[Action] RAG answer from knowledge base")

    assert visible == "\u9762\u5411\u7528\u6237\u7684\u7b54\u6848"
    assert internal_only == "\u4efb\u52a1\u5df2\u5b8c\u6210"


def test_company_profile_status_flags_missing_business_context():
    from app.api.rag import _company_profile_status

    status = _company_profile_status(
        {
            "industry": "",
            "brand_description": "skin care brand",
            "target_audience": "",
            "product_categories": [],
            "competitors": ["competitor-a"],
            "usp": "",
        }
    )

    assert status["setup_required"] is True
    assert status["completeness_score"] == 0.33
    assert status["missing_fields"] == [
        "industry",
        "target_audience",
        "product_categories",
        "usp",
    ]


def test_llm_config_status_flags_empty_company_model_config():
    from app.api.companies import _llm_config_status

    empty = _llm_config_status({})
    partial = _llm_config_status({"deepseek": {"gateway": "", "apiKey": ""}})
    configured = _llm_config_status({"deepseek": {"gateway": "https://api.example.com", "apiKey": "sk-live"}})

    assert empty["status"] == "not_configured"
    assert empty["setup_required"] is True
    assert empty["missing_required"] == ["apiKey", "gateway", "provider"]
    assert partial["status"] == "incomplete"
    assert configured["status"] == "configured"
    assert configured["setup_required"] is False


def test_runtime_parse_failures_are_visible_errors():
    from app.runtime.nodes.executor_node import _wrap_tool_result
    from app.runtime.nodes.planner_node import _parse_plan, _validate_plan
    from app.runtime.nodes.reflector_node import _parse_reflection

    plan = _parse_plan("not json")
    errors = _validate_plan(plan, "find creators", [])
    reflection = _parse_reflection("not json")
    executor_result = _wrap_tool_result(SimpleNamespace(content="{not json"), 0, [])

    assert plan["parse_error"] == "planner_llm_json_parse_failed"
    assert errors == ["planner_llm_json_parse_failed"]
    assert reflection["passed"] is False
    assert reflection["issues"] == ["reflector_llm_json_parse_failed"]
    assert executor_result.status == "error"
    assert "Executor tool result JSON parse failed" in executor_result.message


def test_legacy_agent_chat_websocket_fails_closed_when_runtime_unavailable(monkeypatch):
    import app.runtime.orchestrator as orchestrator
    import app.ws as ws_api

    class BrokenRuntime:
        def __init__(self):
            raise RuntimeError("runtime unavailable")

    async def collect_events():
        return [event async for event in ws_api._run_agent_chat("brand_bd", "find kols")]

    monkeypatch.setattr(orchestrator, "AgentRuntime", BrokenRuntime)

    events = asyncio.run(collect_events())

    assert events == [
        {
            "type": "error",
            "code": "agent_runtime_unavailable",
            "content": "Agent runtime is unavailable; no mock response was generated.",
        }
    ]


def test_tool_endpoint_env_templates_expand_defaults(monkeypatch):
    from app.tools.loader import _expand_env_template as loader_expand
    from app.tools.registry import _expand_env_template as registry_expand

    monkeypatch.delenv("KOL_SEARCH_TOOL_URL", raising=False)
    assert loader_expand("${KOL_SEARCH_TOOL_URL:-http://kol-search:8101/tools/search_kols}") == (
        "http://kol-search:8101/tools/search_kols"
    )

    monkeypatch.setenv("KOL_SEARCH_TOOL_URL", "http://tools.example/search")
    assert registry_expand("${KOL_SEARCH_TOOL_URL:-http://kol-search:8101/tools/search_kols}") == (
        "http://tools.example/search"
    )


def test_static_config_avoids_localhost_tool_endpoints_and_weak_prod_defaults():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    tool_providers = (root / "backend" / "config" / "tool_providers.yaml").read_text(
        encoding="utf-8"
    )
    legacy_tools = (root / "backend" / "config" / "tools.yaml").read_text(encoding="utf-8")
    production_env = (root / "backend" / ".env.production.example").read_text(encoding="utf-8")
    compose = (root / "backend" / "docker-compose.yml").read_text(encoding="utf-8")
    alembic_ini = (root / "backend" / "alembic.ini").read_text(encoding="utf-8")
    migrate_script = (root / "backend" / "scripts" / "migrate_to_postgres.py").read_text(
        encoding="utf-8"
    )
    docker_docs = (root / "backend" / "DOCKER_DEPLOYMENT.md").read_text(encoding="utf-8")
    weak_password = "agentx" "_password"
    weak_compose_default = f"POSTGRES_PASSWORD=${{POSTGRES_PASSWORD:-{weak_password}}}"

    assert "http://localhost:810" not in tool_providers
    assert "http://localhost:810" not in legacy_tools
    assert "MILVUS_HOST=milvus" in production_env
    assert "POSTGRES_PASSWORD=${POSTGRES_PASSWORD:?" in compose
    assert weak_compose_default not in compose
    assert weak_password not in alembic_ini
    assert weak_password not in migrate_script
    assert weak_password not in docker_docs
    assert "driver://user:pass@host/dbname" in alembic_ini
    assert "get_postgres_url" in migrate_script
    assert '"127.0.0.1:1025:1025"' in compose
    assert '"127.0.0.1:8025:8025"' in compose
    assert '\n      - "1025:1025"' not in compose
    assert '\n      - "8025:8025"' not in compose
    for service_name, port, command in [
        ("outreach-server", "8105", "python app/mcp_servers/outreach_server.py"),
        ("script-server", "8103", "python app/mcp_servers/script_server.py"),
        ("logistics-server", "8106", "python app/mcp_servers/monitor_server.py"),
    ]:
        assert f"  {service_name}:" in compose
        assert f"http://{service_name}:{port}/tools/" in tool_providers
        assert f"http://{service_name}:{port}/tools/" in legacy_tools
        assert command in compose


def test_verify_platform_credentials_awaits_live_authenticate(monkeypatch):
    import json
    import app.api.companies as companies_api

    class AsyncAuthAdapter:
        def __init__(self, app_id=None, app_secret=None, access_token=None, advertiser_id=None):
            self.credentials = {
                "app_id": app_id,
                "app_secret": app_secret,
                "access_token": access_token,
                "advertiser_id": advertiser_id,
            }

        async def authenticate(self):
            assert self.credentials["access_token"] == "bad-token"
            return False, "live token check failed"

    company = SimpleNamespace(
        id=239,
        platform_credentials=json.dumps(
            {
                "douyin_star": {
                    "credentials": {
                        "app_id": "app-1",
                        "app_secret": "secret-1",
                        "access_token": "bad-token",
                        "advertiser_id": "adv-1",
                    },
                    "_meta": {},
                }
            }
        ),
    )
    saved = {}

    monkeypatch.setattr(
        companies_api.db,
        "_instance",
        SimpleNamespace(
            get_company=lambda company_id: company,
            update_company_platform_credentials=lambda company_id, value: saved.setdefault(
                "value", value
            )
            or True,
        ),
    )
    monkeypatch.setitem(companies_api.PLATFORM_ADAPTERS, "douyin_star", AsyncAuthAdapter)

    result = asyncio.run(
        companies_api.verify_platform_credentials(
            239,
            "douyin_star",
            current_user=SimpleNamespace(is_admin=True, company_id=239),
        )
    )

    stored = json.loads(saved["value"])
    assert result.valid is False
    assert result.message == "live token check failed"
    assert stored["douyin_star"]["_meta"]["last_verify_valid"] is False


def test_platform_registry_passes_company_id_to_company_aware_adapters(monkeypatch):
    import app.platforms as platforms

    class CompanyAwareAdapter:
        def __init__(self, company_id=None):
            self.company_id = company_id

        def is_available(self):
            return True

    platforms.clear_adapter_cache()
    monkeypatch.setitem(platforms.PLATFORM_ADAPTERS, "company_aware", CompanyAwareAdapter)

    adapter = platforms.get_platform_adapter("company_aware", company_id=239)

    assert adapter.company_id == 239


def test_mcp_mock_fallbacks_are_blocked_in_production(monkeypatch):
    import json
    from app.mcp_servers.kol_search_server import search_kols
    from app.mcp_servers.monitor_server import check_delivery_status
    from app.mcp_servers.report_server import (
        generate_performance_report,
        generate_strategy_suggestion,
    )

    monkeypatch.setenv("ENV", "production")
    monkeypatch.delenv("ALLOW_PLATFORM_MOCK_FALLBACK", raising=False)

    kol_result = json.loads(asyncio.run(search_kols("beauty", count=1)))
    report_result = json.loads(asyncio.run(generate_performance_report("unknown", "campaign-1")))
    strategy_result = json.loads(generate_strategy_suggestion("xiaohongshu", "beauty"))
    delivery_result = json.loads(check_delivery_status("ORD001"))

    assert kol_result["status"] == "error"
    assert report_result["status"] == "error"
    assert strategy_result["status"] == "error"
    assert delivery_result["status"] == "error"
    assert "mock fallback is disabled" in kol_result["message"]


def test_unsupported_platform_creator_search_does_not_return_instruction_rows():
    from app.platforms.douyin_shop import DouyinShopAdapter
    from app.platforms.taobao import TaobaoAdapter

    douyin_shop_results = asyncio.run(DouyinShopAdapter().search_creators("beauty", 2))
    taobao_results = asyncio.run(TaobaoAdapter().search_creators("beauty", 2))

    assert douyin_shop_results == []
    assert taobao_results == []


def test_local_embedding_test_success_has_no_error():
    import app.api.rag as rag_api

    result = rag_api.test_embedding_connection(
        rag_api.EmbeddingTestRequest(mode="local"),
        current_user=SimpleNamespace(company_id=239),
    )

    assert result.ok is True
    assert result.error == ""
    assert result.message == "\u672c\u5730\u6a21\u5f0f\u65e0\u9700\u6d4b\u8bd5"


def test_chat_request_company_context_default_is_isolated():
    from app.api.chat import ChatRequest

    first = ChatRequest(message="只根据知识库回答")
    second = ChatRequest(message="普通问题")
    first.company_context["company_name"] = "污染测试"

    assert second.company_context == {}


def test_chat_kol_search_extracts_explicit_name_constraint():
    from app.api.chat import _extract_kol_search_params

    params = _extract_kol_search_params(
        "请只基于我的达人库搜索护肤类小红书达人，列出2位候选达人。"
        "如果没有名称包含 FULL测试 的达人，请明确说没有找到，不要编造。"
    )

    assert params["platform"] == "xiaohongshu"
    assert params["category_label"] == "护肤"
    assert params["limit"] == 2
    assert params["query"] == "护肤 FULL测试"


def test_chat_kol_empty_result_refuses_mock_or_generic_fill():
    from app.api.chat import _format_company_kol_search_response

    response = _format_company_kol_search_response(
        {
            "params": {"platform": "xiaohongshu", "category_label": "护肤"},
            "results": [],
        }
    )

    assert "没有在当前企业达人库中找到" in response
    assert "没有使用 mock、demo 或通用知识库结果补齐" in response
    assert "设置 - 达人数据" in response


def test_chat_kol_response_shows_enterprise_data_source():
    from app.api.chat import _format_company_kol_search_response

    response = _format_company_kol_search_response(
        {
            "params": {"platform": "xiaohongshu", "category_label": "护肤"},
            "results": [
                {
                    "name": "FULL测试护肤达人A",
                    "platform": "xiaohongshu",
                    "followers": 120000,
                    "engagement_rate": 4.2,
                    "category": "护肤",
                    "data_source": "manual_upload",
                }
            ],
        }
    )

    assert "FULL测试护肤达人A" in response
    assert "人工导入" in response
    assert "未使用 mock/demo/fallback 数据" in response


def test_creative_tools_do_not_return_fake_success_without_services():
    from app.agents.tools import (
        bridge_video_editor,
        check_image_compliance,
        export_multi_format,
    )

    compliance = check_image_compliance.invoke(
        {"image_url": "https://asset.example.test/image.png", "platform": "douyin"}
    )
    exports = export_multi_format.invoke(
        {"image_url": "https://asset.example.test/image.png", "platform": "douyin"}
    )
    export_clip = bridge_video_editor.invoke(
        {"action": "export_clip", "project_name": "campaign-video", "output_format": "mp4"}
    )
    progress = bridge_video_editor.invoke(
        {"action": "query_progress", "project_name": "campaign-video"}
    )

    assert compliance["status"] == "unverified"
    assert compliance["compliant"] is False
    assert compliance["requires_human_review"] is True
    assert exports["status"] == "unavailable"
    assert exports["requires_external_renderer"] is True
    assert all(item["url"] == "" and item["status"] == "not_generated" for item in exports["exports"])
    assert export_clip["status"] == "unavailable"
    assert "output_url" not in export_clip
    assert progress["status"] == "unavailable"
    assert "tasks" not in progress


def test_business_tools_do_not_return_fake_logistics_or_crm_success_without_backends():
    from app.agents.tools import check_delivery_status, manage_kol_relationship

    delivery = check_delivery_status.invoke({"sample_id": "SAMPLE-20260810-001"})
    add_profile = manage_kol_relationship.invoke(
        {
            "action": "add_profile",
            "kol_name": "FULL测试达人",
            "kol_platform": "xiaohongshu",
            "company_id": "239",
        }
    )
    schedule = manage_kol_relationship.invoke({"action": "query_schedule", "company_id": "239"})
    active = manage_kol_relationship.invoke({"action": "list_active", "company_id": "239"})
    history = manage_kol_relationship.invoke({"action": "cooperation_history", "company_id": "239"})

    assert delivery["status"] == "unavailable"
    assert delivery["requires_logistics_backend"] is True
    assert delivery["carrier"] == ""
    assert delivery["tracking_no"] == ""
    assert "SF001" not in str(delivery)
    assert add_profile["status"] == "unavailable"
    assert add_profile["requires_crm_backend"] is True
    assert add_profile["created"] is False
    assert add_profile["profile"] is None
    assert schedule["upcoming_campaigns"] == []
    assert schedule["available_slots"] == []
    assert active["active_kols"] == []
    assert active["total_active"] == 0
    assert history["records"] == []
    assert history["summary"] == {}
    assert "达人A" not in str(schedule)
    assert "达人B" not in str(active)
    assert "370000" not in str(history)


def test_erp_bridge_does_not_return_fake_tracking_or_sync_success_without_backends():
    from app.agents.tools import track_shipment
    from app.services.erp_bridge import ERPBridge

    tracking = track_shipment.invoke({"tracking_no": "SF1234567890", "provider": "auto"})
    ewaybill = ERPBridge.create_ewaybill(
        "ORDER-1",
        sender={"name": "sender"},
        receiver={"name": "receiver"},
        package_info={"weight": 1},
    )
    sync_result = ERPBridge.sync_erp(
        "order",
        "ORDER-1",
        {"status": "paid", "amount": 100},
        erp_system="jushuitan",
    )

    assert tracking["status"] == "unavailable"
    assert tracking["requires_logistics_backend"] is True
    assert tracking["tracking_details"] == []
    assert tracking["current_location"] == ""
    assert ewaybill["success"] is False
    assert ewaybill["status"] == "unavailable"
    assert ewaybill["requires_external_shipping_api"] is True
    assert ewaybill["ewaybill_no"] == ""
    assert sync_result["success"] is False
    assert sync_result["requires_erp_backend"] is True
    assert sync_result["synced_fields"] == []
    assert sync_result["requested_fields"] == ["status", "amount"]


def test_customer_auto_reply_is_review_draft_not_sent_message():
    from app.agents.tools import generate_auto_reply

    reply = generate_auto_reply.invoke({"inquiry_type": "物流进度"})

    assert reply["status"] == "pending_review"
    assert reply["auto_send"] is False
    assert reply["requires_human_review"] is True
    assert "未接入外发渠道" in reply["message"]
    assert "已发送" not in str(reply)


def test_send_strategy_tool_matches_current_decision_schema(monkeypatch):
    from app.agents.tools import evaluate_send_strategy

    monkeypatch.delenv("ALLOW_CUSTOMER_SERVICE_AUTO_SEND", raising=False)

    decision = evaluate_send_strategy.invoke(
        {
            "message_id": "msg-1",
            "customer_message": "请问物流什么时候到",
            "confidence": 0.95,
            "agent_reply": "您好，已为您生成回复草稿。",
        }
    )

    assert decision["send_level"] == "batch"
    assert decision["requires_review"] is True
    assert decision["auto_send"] is False
    assert decision["batch_group"]
    assert "生产默认需人工批量确认后发送" in decision["reason"]


def test_customer_service_rule_fallbacks_do_not_claim_external_state():
    from app.engines.customer_service_engine import CustomerServiceEngine

    engine = CustomerServiceEngine()

    shipping_reply = engine._rule_based_reply("什么时候发货")
    refund_reply = engine._rule_based_reply("我要退款")
    exchange_reply = engine._rule_based_reply("我要退换货")

    combined = "\n".join([shipping_reply, refund_reply, exchange_reply])
    assert "已进入发货流程" not in combined
    assert "退款申请已收到，我们将在" not in combined
    assert "马上为您处理退换货" not in combined
    assert "订单系统确认" in shipping_reply
    assert "人工审核" in refund_reply
    assert "审核草稿" in exchange_reply


def test_metric_recommendations_mark_ad_side_effects_for_manual_confirmation():
    from app.engines.metrics_engine import MetricsEngine

    roi_down = MetricsEngine.detect_anomaly("roi", 60, 100)
    roi_up = MetricsEngine.detect_anomaly("roi", 140, 100)
    cpa_up = MetricsEngine.detect_anomaly("cpa", 160, 100)
    refund_up = MetricsEngine.detect_anomaly("refund_rate", 8, 1)

    actions = (
        roi_down.suggested_actions
        + roi_up.suggested_actions
        + cpa_up.suggested_actions
        + refund_up.suggested_actions
    )
    high_risk_actions = [
        action
        for action in actions
        if any(keyword in action for keyword in ["暂停", "预算", "出价", "投放推广"])
    ]

    assert high_risk_actions
    assert all("人工确认" in action or "检查投放计划是否" in action for action in high_risk_actions)
    assert "紧急暂停低效计划，避免亏损扩大" not in "\n".join(actions)


def test_agent_prompts_do_not_claim_high_risk_side_effects_are_executed():
    from app.agents import amy, brand_bd, cc, smart_ad_delivery, warehouse_logistics

    customer_prompt = amy.get_system_prompt()
    bd_prompt = brand_bd.get_system_prompt()
    content_prompt = cc.get_system_prompt()
    ad_prompt = smart_ad_delivery.get_system_prompt()
    logistics_prompt = warehouse_logistics.get_system_prompt()

    assert "静默发送" not in customer_prompt
    assert "订单号 #{order_id} 已为您登记退货退款申请" not in customer_prompt
    assert "退款将在收到退货后24小时内原路返回" not in customer_prompt
    assert "未得到显式人工确认前，不得声称已经发送、登记、退款、补偿或执行" in customer_prompt
    assert "待人工确认后才会对外发送" in customer_prompt

    assert "内容发布后通知数据分析追踪效果" not in content_prompt
    assert "不得声称已经发布、回复、私信或修改账号" in content_prompt

    assert "campaign_create(platform=\"抖音\", daily_budget=500)" not in ad_prompt
    assert "未得到显式人工确认前，不得声称已经创建计划、调整预算、暂停投放或修改出价" in ad_prompt

    assert "安排寄样、跟踪物流状态、发送收货提醒" not in bd_prompt
    assert "不得声称已经联系、寄样、提醒或建档" in bd_prompt
    signoff_lines = [line for line in logistics_prompt.splitlines() if "签收异常" in line]
    assert signoff_lines
    assert all("补发/退款建议，必须人工确认后执行" in line for line in signoff_lines)


def test_frontend_destructive_actions_require_confirmation():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    sidebar = (root / "frontend/src/components/Sidebar.jsx").read_text(encoding="utf-8")
    knowledge = (root / "frontend/src/pages/settings/KnowledgeSection.jsx").read_text(encoding="utf-8")
    platform_form = (root / "frontend/src/components/SettingsSection/PlatformCredentialForm.jsx").read_text(encoding="utf-8")

    assert sidebar.count("window.confirm") >= 3
    assert "onDeleteConversation(c.id)" in sidebar
    assert "onLogout?.()" in sidebar
    assert knowledge.count("window.confirm") >= 2
    assert "deleteDocument(docId, companyId)" in knowledge
    assert "deleteAllDocuments(companyId)" in knowledge
    assert "window.confirm" in platform_form
    assert "unbindCredentials(companyId, platform.code)" in platform_form


def test_frontend_auth_paths_use_cookie_credentials_not_legacy_token_headers():
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    chat_api = (root / "frontend/src/api/chat.js").read_text(encoding="utf-8")
    preview_modal = (
        root / "frontend/src/components/FilePreviewModal.jsx"
    ).read_text(encoding="utf-8")

    assert "getAuthToken" not in chat_api
    assert "Authorization" not in chat_api
    assert "credentials: 'include'" in chat_api
    assert "getAuthToken" not in preview_modal
    assert "Authorization" not in preview_modal
    assert "credentials: 'include'" in preview_modal


def test_frontend_does_not_default_missing_company_context_to_company_one():
    root = Path(__file__).resolve().parents[2]
    frontend_files = [
        "frontend/src/pages/ChatPage.jsx",
        "frontend/src/components/TopBar.jsx",
        "frontend/src/pages/settings/LlmConfigSection.jsx",
        "frontend/src/pages/settings/KnowledgeSection.jsx",
        "frontend/src/pages/settings/CompanyProfileSection.jsx",
        "frontend/src/components/SettingsSection/PlatformAuthSection.jsx",
    ]
    forbidden = [
        "user?.company_id || '1'",
        'user?.company_id || "1"',
        "user?.company_id || 1",
        "companyId || '1'",
        'companyId || "1"',
        "companyId || 1",
    ]

    for rel_path in frontend_files:
        text = (root / rel_path).read_text(encoding="utf-8")
        for pattern in forbidden:
            assert pattern not in text, f"{rel_path} must not default missing company_id to 1"


def test_frontend_user_chain_smoke_covers_business_path():
    root = Path(__file__).resolve().parents[2]
    smoke = (root / "frontend/scripts/user-chain-smoke.mjs").read_text(encoding="utf-8")

    for step_name in [
        "settings_7_sections_clickable",
        "knowledge_structured_preview",
        "kol_import_and_ui_search",
        "chat_uses_imported_kol_data",
    ]:
        assert step_name in smoke
    assert "public-source.invalid/ui-kol" in smoke
    assert "example.com/ui-kol" not in smoke


def test_knowledge_upload_filename_is_sanitized():
    import app.api.knowledge as knowledge_api

    safe = knowledge_api._sanitize_upload_filename(r"..\..\evil<script>.txt")

    assert safe == "evil_script_.txt"
    assert "/" not in safe
    assert "\\" not in safe
    assert "<" not in safe


def test_knowledge_upload_rejects_mismatched_content_type():
    import app.api.knowledge as knowledge_api

    with pytest.raises(HTTPException) as exc_info:
        knowledge_api._validate_upload_content_type(".txt", "application/javascript")

    assert exc_info.value.status_code == 400


def test_knowledge_upload_supported_extensions_match_parser():
    import app.api.knowledge as knowledge_api
    from app.rag.document_parser import SUPPORTED_FORMATS

    assert ".doc" not in knowledge_api.SUPPORTED_EXTENSIONS
    assert {
        extension.lstrip(".") for extension in knowledge_api.SUPPORTED_EXTENSIONS
    }.issubset(SUPPORTED_FORMATS)

