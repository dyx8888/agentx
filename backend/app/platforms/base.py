"""
Base Platform Adapter for AgentX Stage 23
Provides abstract interface for different e-commerce platforms
"""

from abc import ABC, abstractmethod
from typing import Any

from app.core.logging import get_logger

logger = get_logger(__name__)

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

    def _handle_api_error(self, error: Exception, fallback_data: Any = None) -> Any:
        """
        Handle API errors with fallback to mock data
        
        Args:
            error: The exception that occurred
            fallback_data: Data to return when API fails
            
        Returns:
            Fallback data or error message
        """
        logger.error("platform_api_error_handled", error=str(error))
        logger.info("platform_api_fallback_to_mock")
        return fallback_data
