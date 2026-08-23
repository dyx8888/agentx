"""Normalization tests for sanitized browser connector capture events."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest


FIXTURE_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "browser_connector"


def _event(payload, *, event_id=101, platform="douyin", matched_rule="buyin-api"):
    from app.database.models import BrowserConnectorEvent

    return BrowserConnectorEvent(
        id=event_id,
        company_id=42,
        user_id=7,
        source="chrome-extension-mv3",
        platform=platform,
        matched_rule=matched_rule,
        api_url_hash="a" * 64,
        api_method="GET",
        status_code=200,
        response_mime="application/json",
        sanitized_payload_json=json.dumps(payload, ensure_ascii=False),
        payload_hash="b" * 64,
        captured_at=datetime(2026, 8, 13),
    )


def _load_fixture(name):
    return json.loads((FIXTURE_DIR / name).read_text(encoding="utf-8"))


def _event_from_fixture(fixture, *, event_id=201):
    meta = fixture["meta"]
    return _event(
        fixture["payload"],
        event_id=event_id,
        platform=meta["platform"],
        matched_rule=meta["matched_rule"],
    )


def test_normalizes_creator_profiles_from_author_list():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    event = _event(
        {
            "kind": "json",
            "value": {
                "authors": [
                    {
                        "nickname": "美妆达人A",
                        "uid": "dy-a",
                        "fans_count": "1.2万",
                        "interaction_rate": "4.5%",
                        "category": "美妆",
                        "avg_play_count": 50000,
                        "city": "杭州",
                        "is_verified": "已认证",
                    }
                ]
            },
        }
    )

    records = normalize_browser_connector_event(event)
    creator = next(record for record in records if record.kind == BrowserConnectorRecordKind.CREATOR_PROFILE)

    assert creator.company_id == 42
    assert creator.source_event_id == 101
    assert creator.record["name"] == "美妆达人A"
    assert creator.record["platform"] == "douyin"
    assert creator.record["platform_uid"] == "dy-a"
    assert creator.record["followers"] == 12000
    assert creator.record["engagement_rate"] == 4.5
    assert creator.record["category"] == "美妆"
    assert creator.record["avg_views"] == 50000
    assert creator.record["location"] == "杭州"
    assert creator.record["verified"] is True
    assert creator.record["data_source"] == "browser_connector"


def test_normalizes_campaign_metrics_and_derives_ratios():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    event = _event(
        {
            "kind": "json",
            "value": {
                "campaigns": [
                    {
                        "campaign_id": "qc-1",
                        "campaign_name": "夏季投放",
                        "impressions": "1,000",
                        "clicks": 50,
                        "orders": 5,
                        "spend": 250,
                        "gmv": 1000,
                    }
                ]
            },
        },
        matched_rule="oceanengine-campaign-api",
    )

    records = normalize_browser_connector_event(event)
    campaign = next(record for record in records if record.kind == BrowserConnectorRecordKind.CAMPAIGN_METRICS)

    assert campaign.record["campaign_id"] == "qc-1"
    assert campaign.record["campaign_name"] == "夏季投放"
    assert campaign.record["impressions"] == 1000
    assert campaign.record["clicks"] == 50
    assert campaign.record["conversions"] == 5
    assert campaign.record["spend"] == 250
    assert campaign.record["revenue"] == 1000
    assert campaign.record["ctr"] == 0.05
    assert campaign.record["cpa"] == 50
    assert campaign.record["roi"] == 4


def test_normalizes_knowledge_observations_from_insights():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    event = _event(
        {
            "kind": "json",
            "value": {
                "insights": [
                    {
                        "title": "直播复盘",
                        "summary": "达人短视频先种草再开播时，转化率明显提升。",
                        "tags": "livestream,creator",
                    }
                ]
            },
        }
    )

    records = normalize_browser_connector_event(event)
    knowledge = next(
        record for record in records if record.kind == BrowserConnectorRecordKind.KNOWLEDGE_OBSERVATION
    )

    assert knowledge.record["title"] == "直播复盘"
    assert "转化率明显提升" in knowledge.record["content"]
    assert knowledge.record["data_source"] == "browser_connector"
    assert "browser_connector" in knowledge.record["tags"]
    assert "douyin" in knowledge.record["tags"]


def test_normalized_source_uses_hashes_without_raw_api_url():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event

    event = _event({"kind": "json", "value": {"authors": [{"name": "A", "uid": "u1"}]}})

    [record] = normalize_browser_connector_event(event)
    serialized = json.dumps(record.to_dict(), ensure_ascii=False)

    assert "https://" not in serialized
    assert "api_url_hash" in serialized
    assert "payload_hash" in serialized


def test_unrecognized_payload_is_retained_as_pending_unmapped_record():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    event = _event({"kind": "json", "value": {"unknown_shape": {"nested": [1, 2, 3]}}})

    [record] = normalize_browser_connector_event(event)

    assert record.kind == BrowserConnectorRecordKind.UNMAPPED_CAPTURE
    assert record.record["status"] == "pending"
    assert record.record["reason"] == "no_normalization_rule_matched"
    assert record.record["source_note"] == "browser_connector_event:101"
    assert record.record["source_url_hash"] == "a" * 64


def test_normalization_rule_catalog_has_fixture_coverage():
    from app.services.browser_connector_rules import list_browser_connector_normalization_rules

    fixture_names = {path.name for path in FIXTURE_DIR.glob("*.json")}
    rules = list_browser_connector_normalization_rules()

    assert rules
    for rule in rules:
        assert rule.fixture_name in fixture_names
        fixture = _load_fixture(rule.fixture_name)
        assert fixture["meta"]["matched_rule"] == rule.matched_rule
        assert fixture["meta"]["platform"] == rule.platform
        assert rule.kind.value in fixture["meta"]["expected_kinds"]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "buyin_creator_search_sanitized.json",
        "oceanengine_campaign_snapshot_sanitized.json",
        "buyin_activity_insight_sanitized.json",
        "unmapped_safe_payload_sanitized.json",
    ],
)
def test_sanitized_platform_fixtures_normalize_to_expected_record_kinds(fixture_name):
    from app.services.browser_connector_normalizer import normalize_browser_connector_event

    fixture = _load_fixture(fixture_name)
    records = normalize_browser_connector_event(_event_from_fixture(fixture))
    actual_kinds = {record.kind.value for record in records}

    assert actual_kinds == set(fixture["meta"]["expected_kinds"])
    serialized = json.dumps([record.to_dict() for record in records], ensure_ascii=False).lower()
    assert "https://" not in serialized
    assert "request-body-should-not-be-collected" not in serialized
    assert "platform-cookie-should-not-be-collected" not in serialized
    assert "authorization" not in serialized
    assert "access_token" not in serialized


def test_creator_fixture_maps_core_profile_fields():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    fixture = _load_fixture("buyin_creator_search_sanitized.json")
    records = normalize_browser_connector_event(_event_from_fixture(fixture))
    creator = next(record for record in records if record.kind == BrowserConnectorRecordKind.CREATOR_PROFILE)

    assert creator.record["name"] == "护肤测评小鹿"
    assert creator.record["platform_uid"] == "dy_creator_001"
    assert creator.record["followers"] == 86000
    assert creator.record["engagement_rate"] == 3.8
    assert creator.record["category"] == "美妆护肤"
    assert creator.record["avg_views"] == 52000
    assert creator.record["avg_likes"] == 2100
    assert creator.record["verified"] is True


def test_campaign_fixture_maps_read_only_metrics():
    from app.services.browser_connector_normalizer import normalize_browser_connector_event
    from app.services.browser_connector_schemas import BrowserConnectorRecordKind

    fixture = _load_fixture("oceanengine_campaign_snapshot_sanitized.json")
    records = normalize_browser_connector_event(_event_from_fixture(fixture))
    campaign = next(record for record in records if record.kind == BrowserConnectorRecordKind.CAMPAIGN_METRICS)

    assert campaign.record["campaign_id"] == "ocpc-20260813-01"
    assert campaign.record["campaign_name"] == "护肤套装七夕投放"
    assert campaign.record["impressions"] == 120000
    assert campaign.record["clicks"] == 3600
    assert campaign.record["conversions"] == 180
    assert campaign.record["spend"] == 5400.50
    assert campaign.record["revenue"] == 27100
    assert campaign.record["ctr"] == 0.03
    assert campaign.record["roi"] == pytest.approx(27100 / 5400.50)
