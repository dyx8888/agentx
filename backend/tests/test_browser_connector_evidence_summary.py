import json
from types import SimpleNamespace


def test_capture_evidence_prefers_platform_page_items():
    from app.services.browser_connector_jobs import build_capture_evidence_summary

    event = SimpleNamespace(
        id=10,
        sanitized_payload_json=json.dumps(
            {
                "title": "小红书发现",
                "data": {
                    "visible_text": "导航 备案信息 页脚",
                    "page_items": [
                        {"text": "公开笔记标题 公开笔记内容", "url": "https://www.xiaohongshu.com/explore/abc"}
                    ],
                },
            }
        ),
        platform="xiaohongshu",
        api_url_hash="hash",
    )
    job = SimpleNamespace(classification="content_reference")

    evidence = build_capture_evidence_summary(job, event)

    assert evidence["excerpt"] == "公开笔记标题 公开笔记内容"
