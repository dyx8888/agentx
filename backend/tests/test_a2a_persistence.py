from types import SimpleNamespace


class FakeDB:
    def __init__(self):
        self.created = []
        self.updated = []
        self.status = {}
        self.fail_create = False
        self.fail_update = False

    def get_agent_by_name(self, name, company_id=None):
        if company_id not in {None, 239}:
            return None
        return SimpleNamespace(name=name, company_id=239)

    def create_a2a_message(self, **kwargs):
        if self.fail_create:
            raise RuntimeError("database unavailable")
        message_id = f"uuid-{len(self.created) + 1}"
        self.created.append(kwargs)
        self.status[message_id] = {
            "task_id": message_id,
            "status": "pending",
            "created_at": "2026-09-12T00:00:00",
            "completed_at": None,
        }
        return message_id

    def update_a2a_message_status(self, message_id, status, result=None):
        self.updated.append((message_id, status, result))
        if self.fail_update:
            return False
        self.status[message_id]["status"] = status
        return True

    def get_a2a_message_status(self, message_id):
        return self.status.get(message_id)


class FakeRedis:
    def __init__(self):
        self.values = {}
        self.hset_calls = []

    def hget(self, key, field):
        return self.values.get(key, {}).get(field)

    def hgetall(self, key):
        return dict(self.values.get(key, {}))

    def hset(self, key, mapping):
        self.hset_calls.append((key, dict(mapping)))
        self.values.setdefault(key, {}).update(mapping)

    def expire(self, _key, _seconds):
        return True


def test_store_task_uses_database_adapter_contract_and_database_generated_id(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    db = FakeDB()
    adapter = A2AAdapter(db)
    monkeypatch.setattr(adapter, "_get_redis", lambda: None)

    result = adapter.send_task("brand_bd", "draft outreach", company_id=239)

    assert result["success"] is True
    assert result["task_id"] == "uuid-1"
    assert db.created == [
        {
            "sender": "a2a_service",
            "recipients": "brand_bd",
            "task": "draft outreach",
            "task_type": "general",
            "company_id": 239,
            "payload": {},
        }
    ]


def test_send_task_reports_failure_when_persistence_fails(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    db = FakeDB()
    db.fail_create = True
    adapter = A2AAdapter(db)
    monkeypatch.setattr(adapter, "_get_redis", lambda: None)

    result = adapter.send_task("brand_bd", "draft outreach", company_id=239)

    assert result == {"success": False, "error": "Task persistence failed"}


def test_status_update_persists_before_refreshing_redis(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    db = FakeDB()
    db.status["uuid-1"] = {"task_id": "uuid-1", "status": "pending"}
    redis = FakeRedis()
    redis.values[adapter_key := "a2a:task:uuid-1"] = {"status": "pending"}
    adapter = A2AAdapter(db)
    monkeypatch.setattr(adapter, "_get_redis", lambda: redis)

    assert adapter.set_task_status("uuid-1", "running", result={"ok": True}) is True
    assert db.updated == [("uuid-1", "running", '{"ok": true}')]
    assert redis.values[adapter_key]["status"] == "running"


def test_status_update_does_not_publish_redis_success_when_database_fails(monkeypatch):
    from app.communication.a2a_adapter import A2AAdapter

    db = FakeDB()
    db.status["uuid-1"] = {"task_id": "uuid-1", "status": "pending"}
    db.fail_update = True
    redis = FakeRedis()
    redis.values["a2a:task:uuid-1"] = {"status": "pending"}
    adapter = A2AAdapter(db)
    monkeypatch.setattr(adapter, "_get_redis", lambda: redis)

    assert adapter.set_task_status("uuid-1", "running") is False
    assert redis.values["a2a:task:uuid-1"]["status"] == "pending"
