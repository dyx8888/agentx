"""No worker is started; exercise synthetic tasks and models only."""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

from app.tasks import worker as worker_module


@pytest.fixture
def harness(monkeypatch):
    import app.agent as agent_module
    import app.agents as agents
    import app.communication.collaboration as collaboration
    import app.services.model_gateway as gateway_module
    import app.tools.registry as registry_module

    db = MagicMock()
    own_agent = SimpleNamespace(company_id=65, name='warehouse_logistics', tools_json='[]', id=None)
    db.get_agent_by_name.return_value = own_agent
    monkeypatch.setattr(worker_module, 'db', db)
    context_builder = MagicMock(return_value={})
    monkeypatch.setattr(agents, 'create_agent_execution_context', context_builder)
    llm = MagicMock()
    llm.bind_tools.return_value = llm
    llm.invoke.return_value = AIMessage(content='synthetic read result')
    llm.ainvoke = AsyncMock(return_value=AIMessage(content='synthetic read result'))
    gateway = SimpleNamespace(get_llm=MagicMock(return_value=llm))
    monkeypatch.setattr(gateway_module, 'get_global_model_gateway', lambda: gateway)
    original_tools, bound_tools = [object()], [object()]
    monkeypatch.setattr(registry_module.registry, 'get_tools_by_names', lambda _: original_tools)
    binder = MagicMock(return_value=bound_tools)
    monkeypatch.setattr(agent_module, 'bind_tenant_core_tools', binder)

    class Graph:
        def __init__(self, node):
            self.node = node
        def invoke(self, state):
            value = self.node(state)
            return asyncio.run(value) if hasattr(value, '__await__') else value
        async def ainvoke(self, state):
            value = self.node(state)
            return await value if hasattr(value, '__await__') else value

    monkeypatch.setattr(agent_module, 'build_reaction_graph', lambda node, tools, mg: (Graph(node), mg))
    monkeypatch.setattr(agent_module, 'build_system_message', lambda _: 'synthetic worker context')
    monkeypatch.setattr(worker_module, '_extract_steps', lambda _: [])
    # Skip constructor: it probes Redis. Never start background loops in tests.
    worker = worker_module.TaskWorker.__new__(worker_module.TaskWorker)
    for name in ('_notify_task_started', '_notify_task_completed', '_notify_task_failed', '_notify_review_required'):
        monkeypatch.setattr(worker, name, MagicMock())
    monkeypatch.setattr(worker, '_get_async_loop', lambda: None)
    monkeypatch.setattr(collaboration.collaboration_engine, 'on_agent_task_completed', MagicMock(return_value=None))
    monkeypatch.setattr(asyncio, 'run_coroutine_threadsafe', MagicMock())
    task = {'id': 17, 'company_id': 65, 'source_agent_id': None,
            'target_agent_name': 'warehouse_logistics', 'task_description': 'synthetic read-only test'}
    return SimpleNamespace(worker=worker, db=db, task=task, own=own_agent, llm=llm,
                           gateway=gateway, binder=binder, bound_tools=bound_tools,
                           original_tools=original_tools, context_builder=context_builder)


def test_worker_uses_company_model_and_bound_core_tools(harness):
    h = harness
    h.worker._process_single_task(h.task)
    h.gateway.get_llm.assert_called_once_with(company_id=65)
    h.binder.assert_called_once_with(h.original_tools, 65)
    h.llm.bind_tools.assert_called_once_with(h.bound_tools)
    h.llm.ainvoke.assert_awaited_once()
    assert h.llm.ainvoke.await_args.kwargs['company_id'] == 65
    h.llm.invoke.assert_not_called()
    assert any(c.args[:2] == (17, 'completed') for c in h.db.update_task_status.call_args_list)


def test_same_named_agent_is_selected_in_current_company(harness):
    h = harness
    h.db.get_agent_by_name.side_effect = lambda name, **kw: (
        h.own if kw.get('company_id') == 65 else SimpleNamespace(company_id=239, id=None)
    )
    h.worker._process_single_task(h.task)
    assert h.db.get_agent_by_name.call_args_list[0].kwargs == {'company_id': 65}
    h.worker._notify_task_completed.assert_called_once()


def test_wrong_company_agent_is_rejected_before_context_or_model(harness):
    h = harness
    h.db.get_agent_by_name.return_value = SimpleNamespace(company_id=239)
    h.worker._process_single_task(h.task)
    h.context_builder.assert_not_called()
    h.gateway.get_llm.assert_not_called()
    h.worker._notify_task_completed.assert_not_called()


@pytest.mark.parametrize('company', [None, '', 'bad', 0, -1, True, 65.5, '65.5'])
def test_invalid_company_never_reaches_database_or_model(harness, company):
    h = harness
    h.task['company_id'] = company
    h.worker._process_single_task(h.task)
    h.db.update_task_status.assert_not_called()
    h.gateway.get_llm.assert_not_called()
    h.context_builder.assert_not_called()


@pytest.mark.parametrize('result', [
    None, {}, {'messages': []}, {'messages': [HumanMessage(content='user query is not an answer')]},
    {'messages': [AIMessage(content='')]}, {'messages': [AIMessage(content='   ')]},
    {'messages': [AIMessage(content='not executed', tool_calls=[{'name': 'read', 'args': {}, 'id': 'fixture'}])]},
    {'messages': [AIMessage(content='invalid call', invalid_tool_calls=[{'name': 'read', 'args': '{', 'id': 'fixture', 'error': 'invalid'}])]},
])
def test_empty_or_nonfinal_graph_output_is_not_success(result):
    graph = SimpleNamespace(invoke=lambda _: result, ainvoke=AsyncMock(return_value=result))
    worker = worker_module.TaskWorker.__new__(worker_module.TaskWorker)
    with pytest.raises(ValueError, match='task_result_incomplete'):
        worker._execute_with_timeout(graph, {}, timeout=1)


def test_empty_model_result_marks_task_failed_not_completed(harness):
    h = harness
    h.llm.invoke.return_value = AIMessage(content='')
    h.llm.ainvoke.return_value = AIMessage(content='')
    h.worker._process_single_task(h.task)
    statuses = [c.args[1] for c in h.db.update_task_status.call_args_list]
    assert 'failed' in statuses and 'completed' not in statuses
    h.worker._notify_task_completed.assert_not_called()


def test_async_timeout_cancels_pending_graph_work():
    cancelled = []
    async def slow(_):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)
    graph = SimpleNamespace(ainvoke=slow, invoke=lambda _: {'messages': [AIMessage(content='wrong sync path')]})
    worker = worker_module.TaskWorker.__new__(worker_module.TaskWorker)
    with pytest.raises(TimeoutError):
        worker._execute_with_timeout(graph, {}, timeout=0.01)
    assert cancelled == [True]


def test_async_model_exception_remains_failed(harness):
    h = harness
    h.llm.ainvoke.side_effect = RuntimeError('synthetic model failure')
    h.worker._process_single_task(h.task)
    assert any(c.args[:2] == (17, 'failed') for c in h.db.update_task_status.call_args_list)
    h.worker._notify_task_completed.assert_not_called()


def test_numeric_company_string_is_normalized(harness):
    h = harness
    h.task['company_id'] = '65'
    h.worker._process_single_task(h.task)
    h.gateway.get_llm.assert_called_once_with(company_id=65)
    h.worker._notify_task_completed.assert_called_once()


def test_missing_agent_never_builds_context_or_model(harness):
    h = harness
    h.db.get_agent_by_name.return_value = None
    h.worker._process_single_task(h.task)
    h.context_builder.assert_not_called()
    h.gateway.get_llm.assert_not_called()
    h.worker._notify_task_failed.assert_called_once()


def test_evolution_reuses_verified_company_agent(harness):
    h = harness
    h.worker._process_single_task(h.task)
    h.db.get_agent_by_name.assert_called_once_with('warehouse_logistics', company_id=65)


def test_real_reaction_graph_executes_async_node_and_read_tool():
    from langchain_core.tools import tool

    from app.agent import build_reaction_graph

    calls = []

    @tool
    async def read_fixture() -> str:
        """Return a synthetic read-only test value."""
        calls.append('read')
        return 'fixture evidence'

    async def node(state):
        if isinstance(state['messages'][-1], HumanMessage):
            return {'messages': [AIMessage(content='', tool_calls=[
                {'name': 'read_fixture', 'args': {}, 'id': 'fixture-call'},
            ])]}
        return {'messages': [AIMessage(content='synthetic grounded answer')]}

    graph, _ = build_reaction_graph(node, [read_fixture], None)
    worker = worker_module.TaskWorker.__new__(worker_module.TaskWorker)
    result = worker._execute_with_timeout(graph, {'messages': [HumanMessage(content='read fixture')]}, timeout=2)
    assert result == 'synthetic grounded answer'
    assert calls == ['read']
