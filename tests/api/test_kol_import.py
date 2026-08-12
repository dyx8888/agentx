from unittest.mock import MagicMock

import pytest
from pydantic import ValidationError


@pytest.fixture
def mock_db_adapter():
    adapter = MagicMock()
    mock_session = MagicMock()
    adapter.get_session.return_value.__enter__.return_value = mock_session
    return adapter, mock_session


@pytest.fixture
def setup_db_proxy(mock_db_adapter):
    from app.database import db as db_proxy

    adapter, _ = mock_db_adapter
    db_proxy._instance = adapter
    yield
    db_proxy._instance = None


def _query_first_chain(session, side_effect):
    query = MagicMock()
    filtered = MagicMock()
    session.query.return_value = query
    query.filter.return_value = filtered
    filtered.first.side_effect = side_effect
    return query, filtered


def test_kol_import_rejects_seed_source():
    from app.api.kol import KolImportItem

    with pytest.raises(ValidationError):
        KolImportItem(
            name="Seed达人",
            platform="douyin",
            data_source="seed",
        )


def test_kol_import_rejects_all_platform():
    from app.api.kol import KolImportItem

    with pytest.raises(ValidationError):
        KolImportItem(
            name="达人",
            platform="all",
            data_source="manual_upload",
        )


@pytest.mark.asyncio
async def test_kol_import_dry_run_does_not_write(setup_db_proxy, mock_db_adapter):
    _, session = mock_db_adapter
    _query_first_chain(session, [None])

    from app.api.kol import KolImportItem, KolImportRequest, import_kols_endpoint

    current_user = MagicMock(company_id=7)
    result = await import_kols_endpoint(
        KolImportRequest(
            dry_run=True,
            items=[
                KolImportItem(
                    name="公开网页达人",
                    platform="douyin",
                    followers=100000,
                    category="护肤",
                    data_source="public_web",
                    source_url="https://public-source.invalid/kol",
                )
            ],
        ),
        current_user=current_user,
    )

    assert result.imported == 1
    assert result.updated == 0
    assert result.dry_run is True
    assert result.data_source_summary == {"public_web": 1}
    assert result.data_source_warning is not None
    session.add.assert_not_called()
    session.commit.assert_not_called()


@pytest.mark.asyncio
async def test_kol_import_creates_and_updates(setup_db_proxy, mock_db_adapter):
    _, session = mock_db_adapter
    existing = MagicMock()
    _query_first_chain(session, [None, existing])

    from app.api.kol import KolImportItem, KolImportRequest, import_kols_endpoint

    current_user = MagicMock(company_id=9)
    result = await import_kols_endpoint(
        KolImportRequest(
            items=[
                KolImportItem(
                    name="新增达人",
                    platform="xiaohongshu",
                    platform_uid="xhs-new-001",
                    followers=82000,
                    engagement_rate=4.8,
                    category="护肤",
                    data_source="manual_upload",
                    source_url="https://example.com/new-kol",
                    source_note="人工表格导入",
                ),
                KolImportItem(
                    name="更新达人",
                    platform="douyin",
                    platform_uid="dy-existing-001",
                    followers=230000,
                    engagement_rate=3.2,
                    category="美妆",
                    data_source="cached_snapshot",
                    source_note="用户导出的历史快照",
                ),
            ],
        ),
        current_user=current_user,
    )

    assert result.imported == 1
    assert result.updated == 1
    assert result.skipped == 0
    assert result.data_source_summary == {"manual_upload": 1, "cached_snapshot": 1}
    assert session.add.call_count == 1
    session.commit.assert_called_once()
    added = session.add.call_args.args[0]
    assert added.source_url == "https://example.com/new-kol"
    assert added.source_note == "人工表格导入"
    assert existing.name == "更新达人"
    assert existing.data_source == "cached_snapshot"
    assert existing.source_note == "用户导出的历史快照"
