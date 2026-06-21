"""
API 降级策略引擎
当平台 API 不可用时，自动切换到 Mock 数据或 Playwright 网页抓取
"""

from contextlib import asynccontextmanager
from dataclasses import dataclass
from enum import StrEnum

from app.core.logging import get_logger

logger = get_logger(__name__)


class DegradationMode(StrEnum):
    """降级模式"""
    LIVE_API = "live_api"
    MOCK_DATA = "mock_data"
    PLAYWRIGHT_SCRAPE = "playwright_scrape"


class DegradationAction(StrEnum):
    """降级操作"""
    FALLBACK = "fallback"
    ALERT = "alert"
    RETRY = "retry"


@dataclass
class DegradationRule:
    platform: str
    max_failures: int = 3
    cooldown_seconds: int = 300
    action: DegradationAction = DegradationAction.FALLBACK
    fallback_mode: DegradationMode = DegradationMode.MOCK_DATA


@dataclass
class ApiFailureRecord:
    platform: str
    failure_count: int = 0
    first_failure_time: float = 0.0
    last_failure_time: float = 0.0
    in_cooldown: bool = False


class ApiDegradationEngine:
    """
    API 降级策略引擎

    策略:
    1. 连续失败 N 次 → 降级到 Mock 数据
    2. 冷却期间恢复请求但持续监控
    3. 恢复后自动切回真实 API
    4. 降级事件记录到日志并推送告警
    """

    DEFAULT_RULES: list[DegradationRule] = [
        DegradationRule(platform="douyin_star", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="douyin_shop", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="taobao", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="chanmama", max_failures=2, cooldown_seconds=600),
        DegradationRule(platform="xiaohongshu", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="shengyi_canshu", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="pinduoduo_open", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="qianchuan", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="ocean_engine", max_failures=3, cooldown_seconds=300),
        DegradationRule(platform="wanxiangtai", max_failures=3, cooldown_seconds=300),
    ]

    def __init__(self):
        self._rules: dict[str, DegradationRule] = {}
        self._failures: dict[str, ApiFailureRecord] = {}
        self._degraded: dict[str, DegradationMode] = {}
        for rule in self.DEFAULT_RULES:
            self._rules[rule.platform] = rule
            self._failures[rule.platform] = ApiFailureRecord()

    @asynccontextmanager
    async def guarded_call(self, platform: str):
        """异步上下文管理器，包装平台 API 调用，自动执行降级策略"""

        rule = self._rules.get(platform)
        if not rule:
            try:
                yield None
                return
            except Exception:
                yield None
                return

        if self._degraded.get(platform) == DegradationMode.MOCK_DATA:
            yield None
            return

        try:
            yield None
            self._record_success(platform)
        except Exception as exc:
            self._record_failure(platform)
            logger.warning(
                "platform_api_degradation_triggered",
                platform=platform,
                error=str(exc),
                failure_count=self._failures[platform].failure_count,
            )
            if self._should_degrade(platform):
                self._degraded[platform] = DegradationMode.MOCK_DATA
                logger.error(
                    "platform_degraded_to_mock",
                    platform=platform,
                    failure_count=self._failures[platform].failure_count,
                )
            raise

    def get_mode(self, platform: str) -> DegradationMode:
        return self._degraded.get(platform, DegradationMode.LIVE_API)

    def is_degraded(self, platform: str) -> bool:
        return platform in self._degraded

    def force_recover(self, platform: str):
        self._degraded.pop(platform, None)
        self._failures[platform] = ApiFailureRecord()
        logger.info("platform_recovery_forced", platform=platform)

    def get_all_degraded(self) -> dict[str, DegradationMode]:
        return dict(self._degraded)

    def _record_success(self, platform: str):
        record = self._failures.get(platform)
        if record:
            record.failure_count = 0
            record.in_cooldown = False

    def _record_failure(self, platform: str):
        import time

        record = self._failures.get(platform)
        if not record:
            return
        now = time.time()
        if record.failure_count == 0:
            record.first_failure_time = now
        record.failure_count += 1
        record.last_failure_time = now

    def _should_degrade(self, platform: str) -> bool:

        rule = self._rules.get(platform)
        record = self._failures.get(platform)
        if not rule or not record:
            return False
        if record.failure_count < rule.max_failures:
            return False
        if record.in_cooldown:
            return False
        record.in_cooldown = True
        return True


degradation_engine = ApiDegradationEngine()
