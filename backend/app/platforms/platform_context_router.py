"""
PlatformContextRouter - Multi-platform context sandbox for content operations

Creates isolated context spaces per platform (Douyin/Xiaohongshu/Taobao/Pinduoduo)
to prevent context explosion and cross-platform information contamination.
"""

from dataclasses import dataclass, field


@dataclass
class PlatformContext:
    platform: str
    brand_voice: str
    content_history: list[dict] = field(default_factory=list)
    active_template: str = ""
    platform_rules: dict = field(default_factory=dict)
    current_topic: str = ""
    session_state: dict = field(default_factory=dict)


class PlatformContextRouter:
    """Creates and manages isolated context sandboxes per platform."""

    PLATFORM_CONFIGS: dict[str, dict] = {
        "douyin": {
            "name_display": "\u6296\u97f3",
            "content_style": "\u5feb\u8282\u594f\u3001\u524d3\u79d2\u94a9\u5b50\u3001\u53e3\u8bed\u5316\u3001\u8282\u594f\u7d27\u51d1",
            "video_duration": "15-60\u79d2",
            "image_ratio": "9:16",
            "hashtag_style": "\u77ed\u5c3e\u70ed\u641c\u8bcd\u53e0\u52a0",
            "forbidden_keywords": ["\u6700", "\u7b2c\u4e00", "\u56fd\u5bb6\u7ea7", "\u7edd\u5bf9", "\u6c38\u4e45"],
            "review_policy": "\u5e7f\u544a\u6cd5\u4e25\u683c\u6267\u884c\uff0c\u533b\u7f8e/\u91d1\u878d\u9700\u8d44\u8d28\u5907\u6848",
            "publishing_tips": "\u6570\u636e\u597d\u65f6\u6bb5 12:00/18:00/21:00\uff0c\u89c6\u9891\u4e0a\u70ed\u95e8\u63a8\u8350\u7b97\u6cd5",
        },
        "xiaohongshu": {
            "name_display": "\u5c0f\u7ea2\u4e66",
            "content_style": "\u7cbe\u81f4\u5c01\u9762\u3001\u7ed3\u6784\u5316\u6392\u7248\u3001\u4eb2\u8eab\u6d4b\u8bc4\u611f\u3001\u5173\u952e\u8bcdSEO",
            "image_ratio": "3:4",
            "hashtag_style": "#\u8bdd\u9898\u6807\u7b7e\u7ec4\u5408\u3001\u517c\u987e\u641c\u7d22\u548c\u63a8\u8350",
            "forbidden_keywords": ["\u6700", "\u7b2c\u4e00", "\u5168\u7f51", "\u552f\u4e00", "\u6b63\u54c1\u4fdd\u8bc1"],
            "review_policy": "\u5e7f\u544a\u5fc5\u987b\u6807\u6ce8\uff0c\u533b\u7f8e\u5185\u5bb9\u9650\u6d41\u4e25\u91cd",
            "publishing_tips": "\u65e9\u665a\u901a\u52e4\u6d41\u91cf\u9ad8\u5cf0 8:00/19:00\uff0c\u5c01\u9762\u6bd4\u6587\u6848\u66f4\u91cd\u8981",
        },
        "taobao": {
            "name_display": "\u6dd8\u5b9d\u5929\u732b",
            "content_style": "\u4ea7\u54c1\u8be6\u60c5\u4e3a\u4e3b\u3001\u89c4\u683c\u53c2\u6570\u6e05\u6670\u3001\u573a\u666f\u5316\u56fe\u7247",
            "image_ratio": "1:1\u4e3b\u56fe\uff0c3:4\u8be6\u60c5\u56fe",
            "hashtag_style": "\u5185\u90e8\u641c\u7d22\u5173\u952e\u8bcd\u4f18\u5316\u4e3a\u4e3b",
            "forbidden_keywords": ["\u5dee\u8bc4\u5220\u9664", "\u5237\u5355", "\u865a\u5047\u4ea4\u6613"],
            "review_policy": "\u5e7f\u544a\u6cd5\u4e25\u683c\u6267\u884c\uff0c\u4ef7\u683c\u8868\u8ff0\u5fc5\u987b\u51c6\u786e",
            "publishing_tips": "\u4e3b\u56fe800x800\uff0c\u7b2c5\u5f20\u5fc5\u987b\u767d\u5e95\u56fe",
        },
        "pinduoduo": {
            "name_display": "\u62fc\u591a\u591a",
            "content_style": "\u7a81\u51fa\u6027\u4ef7\u6bd4\u3001\u4ef7\u683c\u523a\u6fc0\u3001\u76f4\u63a5\u7c97\u66b4",
            "image_ratio": "1:1",
            "hashtag_style": "\u641c\u7d22\u5173\u952e\u8bcd\u4f18\u5148",
            "forbidden_keywords": ["\u5dee\u8bc4\u5220\u9664", "\u5237\u5355"],
            "review_policy": "\u4ef7\u683c\u8868\u8ff0\u5fc5\u987b\u51c6\u786e\uff0c\u5bf9\u6bd4\u4ef7\u9700\u6709\u4f9d\u636e",
            "publishing_tips": "\u4e3b\u56fe750x750\uff0c\u4ef7\u683c\u662f\u6700\u5927\u653b\u51fb\u70b9",
        },
    }

    def __init__(self):
        self._sessions: dict[str, dict[str, PlatformContext]] = {}

    def _session_key(self, company_id: str, agent_id: str) -> str:
        return f"{company_id}:{agent_id}"

    def create_sandbox(
        self, company_id: str, agent_id: str, platform: str, brand_voice: str = ""
    ) -> PlatformContext:
        config = self.PLATFORM_CONFIGS.get(platform, {})
        key = self._session_key(company_id, agent_id)

        if key not in self._sessions:
            self._sessions[key] = {}

        ctx = PlatformContext(
            platform=platform,
            brand_voice=brand_voice,
            platform_rules=config,
        )
        self._sessions[key][platform] = ctx
        return ctx

    def get_context(self, company_id: str, agent_id: str, platform: str) -> PlatformContext | None:
        key = self._session_key(company_id, agent_id)
        return self._sessions.get(key, {}).get(platform)

    def switch_platform(self, company_id: str, agent_id: str, platform: str) -> PlatformContext:
        key = self._session_key(company_id, agent_id)
        if key in self._sessions and platform in self._sessions[key]:
            return self._sessions[key][platform]
        return self.create_sandbox(company_id, agent_id, platform)

    def get_platform_config(self, platform: str) -> dict:
        return self.PLATFORM_CONFIGS.get(platform, {})

    def adapt_content(self, content: str, from_platform: str, to_platform: str) -> dict:
        from_config = self.get_platform_config(from_platform)
        to_config = self.get_platform_config(to_platform)

        return {
            "original": content,
            "original_platform": from_platform,
            "target_platform": to_platform,
            "adaptation_notes": [
                f"\u98ce\u683c\u8f6c\u6362\uff1a{from_config.get('content_style', 'N/A')} \u2192 {to_config.get('content_style', 'N/A')}",
                f"\u5c3a\u5bf8\u8c03\u6574\uff1a{from_config.get('image_ratio', 'N/A')} \u2192 {to_config.get('image_ratio', 'N/A')}",
                f"\u8bdd\u9898\u6807\u7b7e\u98ce\u683c\uff1a{to_config.get('hashtag_style', 'N/A')}",
            ],
            "forbidden_keywords_to_remove": to_config.get("forbidden_keywords", []),
        }

    def inject_context(self, company_id: str, agent_id: str, platform: str, context_data: dict) -> None:
        ctx = self.get_context(company_id, agent_id, platform)
        if ctx:
            ctx.content_history.append(context_data)
            ctx.session_state.update(context_data.get("state", {}))

    def clear_session(self, company_id: str, agent_id: str) -> None:
        key = self._session_key(company_id, agent_id)
        self._sessions.pop(key, None)

    def get_all_platform_contexts(self, company_id: str, agent_id: str) -> dict[str, PlatformContext]:
        key = self._session_key(company_id, agent_id)
        return self._sessions.get(key, {})


_platform_context_router: PlatformContextRouter | None = None


def get_platform_context_router() -> PlatformContextRouter:
    global _platform_context_router
    if _platform_context_router is None:
        _platform_context_router = PlatformContextRouter()
    return _platform_context_router
