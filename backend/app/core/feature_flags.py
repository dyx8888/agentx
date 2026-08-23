"""
FeatureFlagManager - 特性开关管理器

读取 config/feature_flags.yaml 提供特性开关的运行时判断。
支持环境变量覆盖：FEATURE_{NAME}=true/false
"""

import os
from pathlib import Path
from typing import Any, Optional

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)

# YAML 配置文件路径
_CONFIG_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "feature_flags.yaml"


class FeatureFlagManager:
    """特性开关管理器（单例模式）

    读取 YAML 配置，提供 is_enabled / get_phase / get_all_enabled 方法。
    支持通过环境变量 FEATURE_{NAME}=true/false 覆盖配置。
    """

    _instance: Optional["FeatureFlagManager"] = None

    def __new__(cls) -> "FeatureFlagManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._flags: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        """从 YAML 文件加载特性开关配置"""
        if not _CONFIG_PATH.exists():
            logger.warning(
                "feature_flags_config_not_found",
                path=str(_CONFIG_PATH),
            )
            return

        try:
            with open(_CONFIG_PATH, encoding="utf-8") as f:
                config = yaml.safe_load(f)
            raw_features = config.get("features", {}) if isinstance(config, dict) else {}
            self._flags = dict(raw_features)
            logger.info("feature_flags_loaded", count=len(self._flags))
        except Exception as e:
            logger.error("feature_flags_load_failed", error=str(e))

    def is_enabled(self, feature_name: str) -> bool:
        """检查特性是否启用

        优先级：环境变量 FEATURE_{NAME} > YAML 配置
        """
        env_var = f"FEATURE_{feature_name.upper()}"
        env_val = os.getenv(env_var)
        if env_val is not None:
            return env_val.lower() in ("true", "1", "yes")

        flag = self._flags.get(feature_name)
        if flag is None:
            logger.debug("feature_flag_not_found", feature=feature_name)
            return False
        return bool(flag.get("enabled", False))

    def is_enabled_for_context(
        self,
        feature_name: str,
        *,
        tenant_id: int | str | None = None,
        user_id: int | str | None = None,
    ) -> bool:
        """检查特性是否对当前租户或用户开放。

        优先使用全局开关；全局关闭时，可通过 YAML allowlist 或环境变量
        FEATURE_{NAME}_TENANT_IDS / FEATURE_{NAME}_USER_IDS 开启试点租户。
        """
        if self.is_enabled(feature_name):
            return True

        tenant = _coerce_int(tenant_id)
        user = _coerce_int(user_id)
        if tenant is not None and tenant in self._allowlist_ids(
            feature_name,
            config_key="tenant_allowlist",
            env_suffix="TENANT_IDS",
        ):
            return True
        if user is not None and user in self._allowlist_ids(
            feature_name,
            config_key="user_allowlist",
            env_suffix="USER_IDS",
        ):
            return True
        return False

    def _allowlist_ids(self, feature_name: str, *, config_key: str, env_suffix: str) -> set[int]:
        env_var = f"FEATURE_{feature_name.upper()}_{env_suffix}"
        env_val = os.getenv(env_var)
        if env_val is not None:
            return _parse_id_list(env_val)

        flag = self._flags.get(feature_name) or {}
        return _parse_id_list(flag.get(config_key, []))

    def get_phase(self, feature_name: str) -> int | None:
        """获取特性的上线阶段"""
        flag = self._flags.get(feature_name)
        if flag is None:
            return None
        return flag.get("phase")

    def get_all_enabled(self) -> list[str]:
        """获取所有当前启用的特性名称列表"""
        return [name for name in self._flags if self.is_enabled(name)]


def get_feature_flags() -> FeatureFlagManager:
    """获取全局 FeatureFlagManager 单例"""
    return FeatureFlagManager()


def _parse_id_list(raw_value: Any) -> set[int]:
    if raw_value is None:
        return set()
    if isinstance(raw_value, str):
        values = raw_value.split(",")
    elif isinstance(raw_value, (list, tuple, set)):
        values = raw_value
    else:
        values = [raw_value]

    parsed: set[int] = set()
    for value in values:
        coerced = _coerce_int(value)
        if coerced is not None:
            parsed.add(coerced)
    return parsed


def _coerce_int(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None
