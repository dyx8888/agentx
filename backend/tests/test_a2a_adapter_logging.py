from types import SimpleNamespace


def test_a2a_adapter_structured_logger_accepts_event_fields(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    adapter = A2AAdapter(
        SimpleNamespace(
            get_a2a_message_status=lambda _task_id: None,
        )
    )
    monkeypatch.setattr(adapter, "_get_redis", lambda: None)
    monkeypatch.setattr(
        adapter,
        "_update_task_status_db",
        lambda _task_id, _status, **_kwargs: True,
    )

    # The fallback path must be able to log keyword fields without Logger._log errors.
    assert adapter.set_task_status("task-1", "running") is True
