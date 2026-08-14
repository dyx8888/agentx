"""
Base Platform Adapter for AgentX Stage 23
Provides abstract interface for different e-commerce platforms
"""

from abc import ABC, abstractmethod
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)


class PlatformAdapterUnavailable(RuntimeError):
    """Raised when a platform adapter cannot return verified external data."""

    def __init__(
        self,
        *,
        platform: str,
        operation: str,
        code: str,
        message: str,
        requires_config: bool = False,
    ):
        super().__init__(message)
        self.status = "unavailable"
        self.platform = platform
        self.operation = operation
        self.code = code
        self.requires_config = requires_config
        self.message = message

    def to_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "platform": self.platform,
            "operation": self.operation,
            "code": self.code,
            "message": self.message,
            "requires_config": self.requires_config,
        }


class PlatformAdapter(ABC):
    """
    Abstract base class for platform adapters
    Defines the interface that all platform adapters must implement
    """

    @abstractmethod
    def search_creators(self, category: str, count: int = 10) -> list[dict[str, Any]]:
        """
        Search for creators/KOLs on the platform
        
        Args:
            category: Category to search for (e.g., "beauty", "fashion")
            count: Number of results to return
            
        Returns:
            List of creator dictionaries with platform-specific data
        """
        pass

    @abstractmethod
    def get_campaign_report(self, kol_id: str, campaign_id: str) -> dict[str, Any] | None:
        """
        Get campaign performance data for a specific KOL
        
        Args:
            kol_id: Platform-specific KOL identifier
            campaign_id: Campaign identifier
            
        Returns:
            Campaign performance data or None if not found
        """
        pass

    @abstractmethod
    def get_platform_info(self) -> dict[str, Any]:
        """
        Get platform information and capabilities
        
        Returns:
            Dictionary containing platform metadata
        """
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """
        Check if the platform adapter is properly configured and available
        
        Returns:
            True if platform is ready to use
        """
        pass

    @abstractmethod
    def get_shop_data(self, shop_id: str, metrics: list[str] | None = None) -> dict[str, Any]:
        """
        Get shop/store operational data from the platform
        
        Args:
            shop_id: Platform-specific shop/store identifier
            metrics: List of metrics to retrieve (e.g., ["gmv", "uv", "conversion_rate"])
                    If None, returns all available metrics
            
        Returns:
            Dictionary containing shop operational metrics
        """
        pass

    def _log_api_call(self, method: str, url: str, params: dict[str, Any],
                   success: bool, response: Any = None, error: str = None):
        """Log API calls for debugging (params and response redacted for safety)"""
        status = "SUCCESS" if success else "FAILED"
        logger.info(
            "platform_api_call",
            status=status,
            method=method,
            url=url,
            param_count=len(params) if params else 0,
        )
        if response:
            logger.info(
                "platform_api_response",
                response_type=type(response).__name__,
                response_length=len(str(response)) if response else 0,
            )
        if error:
            logger.error("platform_api_error", error=error)

    def _platform_code(self) -> str:
        try:
            info = self.get_platform_info()
            return str(info.get("code") or info.get("name") or self.__class__.__name__)
        except Exception:
            return self.__class__.__name__

    def _raise_unavailable(
        self,
        operation: str,
        code: str,
        message: str,
        *,
        requires_config: bool = False,
    ) -> None:
        raise PlatformAdapterUnavailable(
            platform=self._platform_code(),
            operation=operation,
            code=code,
            message=message,
            requires_config=requires_config,
        )

    def _require_available(self, operation: str) -> None:
        if self.is_available():
            return
        self._raise_unavailable(
            operation,
            "requires_config",
            f"{self._platform_code()}.{operation} requires verified platform credentials.",
            requires_config=True,
        )

    def _raise_external_api_unavailable(
        self,
        operation: str,
        error: Exception | None = None,
        *,
        fallback_attempted: bool = False,
    ) -> None:
        code = "external_api_unavailable"
        if fallback_attempted:
            try:
                from app.mcp_servers.mock_policy import mock_fallback_enabled

                if not mock_fallback_enabled():
                    code = "mock_fallback_blocked"
            except Exception:
                pass
        detail = f": {error}" if error else ""
        self._raise_unavailable(
            operation,
            code,
            f"{self._platform_code()}.{operation} cannot return verified external data{detail}.",
            requires_config=False,
        )

    def _handle_api_error(
        self, error: Exception, fallback_data: Any = None, operation: str = "api_call"
    ) -> Any:
        """
        Handle API errors without returning mock fallback data.
        
        Args:
            error: The exception that occurred
            fallback_data: Legacy fallback data. It is never returned.
            
        Returns:
            Never returns; raises a structured unavailable error.
        """
        logger.error("platform_api_error_handled", error=str(error))
        if fallback_data is not None:
            logger.warning("platform_api_mock_fallback_blocked", operation=operation)
        self._raise_external_api_unavailable(
            operation,
            error,
            fallback_attempted=fallback_data is not None,
        )
