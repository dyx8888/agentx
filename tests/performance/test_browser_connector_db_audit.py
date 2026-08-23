import json
from datetime import datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from tests.performance import browser_connector_db_audit as audit


def _db_session(database_url="sqlite:///:memory:"):
    from app.database.models import Base

    engine = create_engine(
        database_url,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    return SessionLocal()


def _event(**overrides):
    from app.database.models import BrowserConnectorEvent

    defaults = {
        "company_id": 42,
        "user_id": 7,
        "source": "chrome-extension-mv3",
        "platform": "douyin",
        "matched_rule": "buyin-api",
        "api_url_hash": "a" * 64,
        "api_method": "GET",
        "status_code": 200,
        "response_mime": "application/json",
        "sanitized_payload_json": json.dumps(
            {
                "kind": "json",
                "value": {
                    "authors": [
                        {
                            "name": "creator-a",
                            "uid": "creator-1",
                            "followers": 12000,
                        }
                    ],
                    "total": 1,
                },
            },
            ensure_ascii=False,
        ),
        "payload_hash": "b" * 64,
        "captured_at": datetime(2026, 8, 13),
    }
    defaults.update(overrides)
    return BrowserConnectorEvent(**defaults)


def test_db_audit_passes_for_safe_connector_event():
    db = _db_session()
    try:
        db.add(_event())
        db.commit()

        report = audit.run_audit(db, company_id=42)

        assert report["summary"]["passed"] is True
        assert report["summary"]["total_events"] == 1
        assert report["summary"]["normalized_record_counts"]["creator_profile"] == 1
        assert report["findings"]["sensitive_markers"] == []
    finally:
        db.close()


def test_db_audit_fails_when_no_events_exist_for_tenant():
    db = _db_session()
    try:
        db.add(_event(company_id=99))
        db.commit()

        report = audit.run_audit(db, company_id=42)

        assert report["summary"]["passed"] is False
        failed = {check["name"] for check in report["checks"] if not check["passed"]}
        assert "tenant has connector events" in failed
    finally:
        db.close()


def test_db_audit_flags_sensitive_stored_payload_markers():
    db = _db_session()
    try:
        db.add(
            _event(
                sanitized_payload_json=json.dumps(
                    {"kind": "json", "value": {"token": "must-not-appear"}},
                    ensure_ascii=False,
                )
            )
        )
        db.commit()

        report = audit.run_audit(db, company_id=42)

        assert report["summary"]["passed"] is False
        assert report["findings"]["sensitive_markers"][0]["marker"] == "token"
        assert "must-not-appear" not in json.dumps(report, ensure_ascii=False)
    finally:
        db.close()


def test_db_audit_flags_invalid_hashes_and_raw_api_url_metadata():
    db = _db_session()
    try:
        db.add(_event(api_url_hash="https://buyin.jinritemai.com/path?token=x", payload_hash="bad"))
        db.commit()

        report = audit.run_audit(db, company_id=42)

        failed = {check["name"] for check in report["checks"] if not check["passed"]}
        assert "sampled rows have valid hashes" in failed
        assert "sampled metadata has no raw api url" in failed
        assert report["findings"]["invalid_hash_event_ids"] == [1]
        assert report["findings"]["raw_url_metadata_event_ids"] == [1]
    finally:
        db.close()


def test_db_audit_database_meta_redacts_database_url(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'audit.db'}"
    db = _db_session(db_url)
    try:
        db.add(_event())
        db.commit()
    finally:
        db.close()

    report = audit.run_audit_from_database_url(db_url, company_id=42)
    out = tmp_path / "report.json"
    out.write_text(json.dumps(report, ensure_ascii=False), encoding="utf-8")

    written = out.read_text(encoding="utf-8")
    assert "creator_profile" in written
    assert db_url not in written
