"""
工具调用安全/权限系统 (Tool Call Security & Permission System)

基于 4.docx（AI应用系统设计）设计文档，实现工具调用的六道安全关卡：
  1. 参数校验 (Parameter Validation)   — 根据 JSON Schema 校验输入参数
  2. 权限校验 (Permission Check)       — 验证用户/租户是否有权调用该工具
  3. 风险等级 (Risk Level)             — READ_ONLY / WRITE_LOW_RISK / WRITE_HIGH_RISK
  4. 审计日志 (Audit Log)              — 记录每一次工具调用尝试
  5. 二次确认 (Confirmation)           — WRITE_HIGH_RISK 工具需要人工确认
  6. 限流 (Rate Limiting)              — 按工具维度进行速率限制

所有关卡均通过后，工具调用才被允许执行。
"""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

from jsonschema import validate, ValidationError

from app.core.logging import get_logger

logger = get_logger(__name__)


# =============================================================================
# 风险等级枚举 — ToolRiskLevel
# 基于 4.docx 第 3 节：工具风险分级
# =============================================================================

class ToolRiskLevel(str, Enum):
    """工具风险等级，来源于 4.docx 中的安全设计规范。

    READ_ONLY:
        只读操作，如查询、搜索、统计。不会对系统状态产生任何副作用。
    WRITE_LOW_RISK:
        低风险写操作，如创建草稿、更新备注、发送通知。影响范围可控。
    WRITE_HIGH_RISK:
        高风险写操作，如删除数据、执行 SQL、发起支付、修改权限。
        此类操作需要二次确认（见第 5 关卡）。
    """
    READ_ONLY = "READ_ONLY"
    WRITE_LOW_RISK = "WRITE_LOW_RISK"
    WRITE_HIGH_RISK = "WRITE_HIGH_RISK"


# =============================================================================
# 工具权限配置 — ToolPermission
# 基于 4.docx 第 2 节：权限模型
# =============================================================================

@dataclass
class ToolPermission:
    """工具权限配置数据类，描述单个工具的安全属性。

    每个工具在注册时需绑定一个 ToolPermission 实例，SecurityGuard
    在运行时根据该配置执行所有安全检查。

    Attributes:
        tool_name: 工具名称，与注册表中的 key 一致。
        risk_level: 风险等级，决定是否触发二次确认。
        required_permissions: 调用该工具所需的权限标识列表，例如 ["user:read", "order:write"]。
        require_confirmation: 是否强制要求二次确认（仅对 WRITE_HIGH_RISK 默认 True）。
        rate_limit: 速率限制，格式为 (max_calls, window_seconds)。None 表示不限流。
        description: 工具用途描述，用于审计日志和二次确认提示。
    """
    tool_name: str
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY
    required_permissions: List[str] = field(default_factory=list)
    require_confirmation: bool = False
    rate_limit: Optional[tuple[int, float]] = None  # (max_calls, window_seconds)
    description: str = ""

    def __post_init__(self):
        # 根据 4.docx 第 5 节：WRITE_HIGH_RISK 工具默认需要二次确认
        if self.risk_level == ToolRiskLevel.WRITE_HIGH_RISK:
            self.require_confirmation = True


# =============================================================================
# 审计记录 — ToolAuditRecord
# 基于 4.docx 第 4 节：审计日志规范
# =============================================================================

@dataclass
class ToolAuditRecord:
    """工具调用审计记录，参照 4.docx 第 4 节审计日志字段定义。

    每一次工具调用（无论成功或失败）都会生成一条审计记录，
    用于事后追溯和安全审计。

    Attributes:
        record_id: 审计记录唯一 ID。
        timestamp: 调用时间戳（Unix epoch）。
        tool_name: 被调用的工具名称。
        user_id: 发起调用的用户 ID。
        tenant_id: 发起调用的租户 ID。
        parameters: 调用参数（敏感字段已脱敏）。
        risk_level: 工具的风险等级。
        result: 调用结果，'allowed' / 'denied' / 'pending_confirmation'。
        deny_reason: 如果被拒绝，拒绝原因。
        confirmation_id: 二次确认 ID（如有）。
        latency_ms: 安全检查耗时（毫秒）。
    """
    record_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    timestamp: float = field(default_factory=time.time)
    tool_name: str = ""
    user_id: str = ""
    tenant_id: str = ""
    parameters: Dict[str, Any] = field(default_factory=dict)
    risk_level: ToolRiskLevel = ToolRiskLevel.READ_ONLY
    result: str = ""  # allowed / denied / pending_confirmation
    deny_reason: str = ""
    confirmation_id: str = ""
    latency_ms: float = 0.0


# =============================================================================
# 安全检查结果
# =============================================================================

@dataclass
class SecurityCheckResult:
    """安全检查综合结果，汇总六个关卡的判定。

    Attributes:
        allowed: 是否允许执行。
        deny_reason: 拒绝原因（allowed=False 时填写）。
        pending_confirmation: 是否需要二次确认。
        confirmation_id: 二次确认会话 ID。
        audit_record: 完整的审计记录。
    """
    allowed: bool = True
    deny_reason: str = ""
    pending_confirmation: bool = False
    confirmation_id: str = ""
    audit_record: Optional[ToolAuditRecord] = None


# =============================================================================
# 率限制器 — RateLimiter
# 基于 4.docx 第 6 节：限流策略
# =============================================================================

class RateLimiter:
    """简易内存速率限制器，按工具维度进行限流。

    使用滑动窗口算法，记录每个工具在时间窗口内的调用时间戳。
    生产环境可替换为 Redis 实现。

    Attributes:
        _storage: {tool_name: [timestamp, ...]} 格式的调用记录。
    """

    def __init__(self):
        self._storage: Dict[str, List[float]] = {}
        self._lock = asyncio.Lock()

    async def is_allowed(self, tool_name: str, max_calls: int, window_seconds: float) -> bool:
        """检查指定工具在当前窗口内是否超过限流阈值。

        Args:
            tool_name: 工具名称。
            max_calls: 窗口内最大调用次数。
            window_seconds: 时间窗口长度（秒）。

        Returns:
            True 表示未超限，允许调用；False 表示已超限。
        """
        async with self._lock:
            now = time.time()
            if tool_name not in self._storage:
                self._storage[tool_name] = []

            # 清理过期记录（滑动窗口）
            window_start = now - window_seconds
            self._storage[tool_name] = [
                ts for ts in self._storage[tool_name] if ts > window_start
            ]

            if len(self._storage[tool_name]) >= max_calls:
                return False

            self._storage[tool_name].append(now)
            return True


# =============================================================================
# 工具安全守卫 — ToolSecurityGuard
# 基于 4.docx 全文六道关卡设计
# =============================================================================

class ToolSecurityGuard:
    """工具调用安全守卫，串联执行六道安全检查关卡。

    使用方式：
        guard = ToolSecurityGuard(permissions_registry, rate_limiter, permission_checker)
        result = await guard.check(tool_name, parameters, user_context)

    六道关卡（按顺序）：
        1. 参数校验  — validate_parameters()
        2. 权限校验  — check_permissions()
        3. 风险分级  — assess_risk()
        4. 审计记录  — create_audit_record()
        5. 二次确认  — require_confirmation()
        6. 限流检查  — check_rate_limit()

    参考文档：4.docx（AI应用系统设计）安全章节。
    """

    def __init__(
        self,
        permissions_registry: Dict[str, ToolPermission],
        rate_limiter: Optional[RateLimiter] = None,
        permission_checker: Optional[Callable[[str, List[str]], bool]] = None,
    ):
        """初始化安全守卫。

        Args:
            permissions_registry: 工具名 -> ToolPermission 的注册表。
            rate_limiter: 速率限制器实例，不传则使用默认内存实现。
            permission_checker: 自定义权限校验函数，签名为 (user_id, required_permissions) -> bool。
                                不传则默认放行所有权限校验。
        """
        self._registry = permissions_registry
        self._rate_limiter = rate_limiter or RateLimiter()
        self._permission_checker = permission_checker or self._default_permission_checker

    # -------------------------------------------------------------------------
    # 公开接口
    # -------------------------------------------------------------------------

    async def check(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        user_context: Dict[str, Any],
        json_schema: Optional[Dict[str, Any]] = None,
    ) -> SecurityCheckResult:
        """执行全部六道安全检查。

        Args:
            tool_name: 工具名称。
            parameters: 工具调用参数。
            user_context: 用户上下文，必须包含 user_id，可选 tenant_id。
            json_schema: 参数的 JSON Schema，用于校验。None 则跳过参数校验。

        Returns:
            SecurityCheckResult 包含所有检查结果。
        """
        t_start = time.perf_counter()

        user_id = user_context.get("user_id", "anonymous")
        tenant_id = user_context.get("tenant_id", "default")

        # 获取工具权限配置
        tool_perm = self._registry.get(tool_name)
        if tool_perm is None:
            # 未注册的工具默认拒绝（安全优先原则）
            latency_ms = (time.perf_counter() - t_start) * 1000
            record = ToolAuditRecord(
                tool_name=tool_name,
                user_id=user_id,
                tenant_id=tenant_id,
                parameters=self._sanitize_params(parameters),
                risk_level=ToolRiskLevel.WRITE_HIGH_RISK,
                result="denied",
                deny_reason=f"未注册的工具: {tool_name}",
                latency_ms=latency_ms,
            )
            self._log_audit(record)
            return SecurityCheckResult(
                allowed=False,
                deny_reason=record.deny_reason,
                audit_record=record,
            )

        # ---- 关卡 1：参数校验 (4.docx 第 1 节) ----
        if json_schema is not None:
            validation_error = self._validate_parameters(tool_name, parameters, json_schema)
            if validation_error:
                latency_ms = (time.perf_counter() - t_start) * 1000
                record = ToolAuditRecord(
                    tool_name=tool_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    parameters=self._sanitize_params(parameters),
                    risk_level=tool_perm.risk_level,
                    result="denied",
                    deny_reason=f"参数校验失败: {validation_error}",
                    latency_ms=latency_ms,
                )
                self._log_audit(record)
                return SecurityCheckResult(
                    allowed=False,
                    deny_reason=record.deny_reason,
                    audit_record=record,
                )

        # ---- 关卡 2：权限校验 (4.docx 第 2 节) ----
        if tool_perm.required_permissions:
            has_permission = self._check_permissions(
                user_id, tool_perm.required_permissions
            )
            if not has_permission:
                latency_ms = (time.perf_counter() - t_start) * 1000
                record = ToolAuditRecord(
                    tool_name=tool_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    parameters=self._sanitize_params(parameters),
                    risk_level=tool_perm.risk_level,
                    result="denied",
                    deny_reason=f"权限不足，需要: {tool_perm.required_permissions}",
                    latency_ms=latency_ms,
                )
                self._log_audit(record)
                return SecurityCheckResult(
                    allowed=False,
                    deny_reason=record.deny_reason,
                    audit_record=record,
                )

        # ---- 关卡 3：风险等级评定 (4.docx 第 3 节) ----
        risk_level = tool_perm.risk_level

        # ---- 关卡 5：二次确认 (4.docx 第 5 节) ----
        pending_confirmation = False
        confirmation_id = ""
        if tool_perm.require_confirmation:
            pending_confirmation = True
            confirmation_id = uuid.uuid4().hex
            logger.info(
                "工具 [%s] 风险等级为 %s，需要二次确认。confirmation_id=%s",
                tool_name, risk_level.value, confirmation_id,
            )

        # ---- 关卡 6：限流检查 (4.docx 第 6 节) ----
        if tool_perm.rate_limit is not None:
            max_calls, window_seconds = tool_perm.rate_limit
            rate_ok = await self._rate_limiter.is_allowed(
                tool_name, max_calls, window_seconds
            )
            if not rate_ok:
                latency_ms = (time.perf_counter() - t_start) * 1000
                record = ToolAuditRecord(
                    tool_name=tool_name,
                    user_id=user_id,
                    tenant_id=tenant_id,
                    parameters=self._sanitize_params(parameters),
                    risk_level=risk_level,
                    result="denied",
                    deny_reason=f"限流: {max_calls}次/{window_seconds}秒",
                    latency_ms=latency_ms,
                )
                self._log_audit(record)
                return SecurityCheckResult(
                    allowed=False,
                    deny_reason=record.deny_reason,
                    audit_record=record,
                )

        # ---- 关卡 4：审计日志 (4.docx 第 4 节) ----
        latency_ms = (time.perf_counter() - t_start) * 1000
        result_status = "pending_confirmation" if pending_confirmation else "allowed"
        record = ToolAuditRecord(
            tool_name=tool_name,
            user_id=user_id,
            tenant_id=tenant_id,
            parameters=self._sanitize_params(parameters),
            risk_level=risk_level,
            result=result_status,
            confirmation_id=confirmation_id,
            latency_ms=latency_ms,
        )
        self._log_audit(record)

        logger.info(
            "工具安全检查完成: tool=%s user=%s risk=%s allowed=%s confirmation=%s latency=%.2fms",
            tool_name, user_id, risk_level.value,
            "yes" if not pending_confirmation else "pending",
            "yes" if pending_confirmation else "no",
            latency_ms,
        )

        return SecurityCheckResult(
            allowed=not pending_confirmation,
            deny_reason="",
            pending_confirmation=pending_confirmation,
            confirmation_id=confirmation_id,
            audit_record=record,
        )

    async def confirm(self, confirmation_id: str, approved: bool) -> bool:
        """处理二次确认结果。

        Args:
            confirmation_id: 二次确认会话 ID。
            approved: 用户是否批准。

        Returns:
            True 表示批准通过，允许执行。
        """
        if approved:
            logger.info("二次确认通过: confirmation_id=%s", confirmation_id)
            return True
        else:
            logger.warning("二次确认被拒绝: confirmation_id=%s", confirmation_id)
            return False

    # -------------------------------------------------------------------------
    # 关卡实现（私有方法）
    # -------------------------------------------------------------------------

    def _validate_parameters(
        self,
        tool_name: str,
        parameters: Dict[str, Any],
        json_schema: Dict[str, Any],
    ) -> Optional[str]:
        """关卡 1：参数校验 — 基于 4.docx 第 1 节。

        使用 jsonschema 库校验输入参数是否符合工具定义的 JSON Schema。
        """
        try:
            validate(instance=parameters, schema=json_schema)
            logger.debug("参数校验通过: tool=%s", tool_name)
            return None
        except ValidationError as e:
            logger.warning("参数校验失败: tool=%s error=%s", tool_name, e.message)
            return e.message

    def _check_permissions(
        self,
        user_id: str,
        required_permissions: List[str],
    ) -> bool:
        """关卡 2：权限校验 — 基于 4.docx 第 2 节。

        通过注入的 permission_checker 函数验证用户是否拥有所需权限。
        """
        return self._permission_checker(user_id, required_permissions)

    @staticmethod
    def _default_permission_checker(
        user_id: str,
        required_permissions: List[str],
    ) -> bool:
        """默认权限校验器：记录警告后放行。

        生产环境必须替换为真实的 RBAC/ABAC 权限校验逻辑。
        """
        logger.warning(
            "使用默认权限校验器（始终放行）。user=%s permissions=%s",
            user_id, required_permissions,
        )
        return True

    def _log_audit(self, record: ToolAuditRecord) -> None:
        """关卡 4：审计日志记录 — 基于 4.docx 第 4 节。

        将审计记录写入日志系统。生产环境可扩展为写入数据库或消息队列。
        """
        log_data = {
            "audit": {
                "record_id": record.record_id,
                "timestamp": record.timestamp,
                "tool_name": record.tool_name,
                "user_id": record.user_id,
                "tenant_id": record.tenant_id,
                "parameters": record.parameters,
                "risk_level": record.risk_level.value,
                "result": record.result,
                "deny_reason": record.deny_reason,
                "confirmation_id": record.confirmation_id,
                "latency_ms": round(record.latency_ms, 3),
            }
        }
        if record.result == "denied":
            logger.warning("AUDIT_DENIED: %s", json.dumps(log_data, ensure_ascii=False))
        else:
            logger.info("AUDIT: %s", json.dumps(log_data, ensure_ascii=False))

    @staticmethod
    def _sanitize_params(parameters: Dict[str, Any]) -> Dict[str, Any]:
        """脱敏处理：对敏感字段进行掩码，避免审计日志泄露。

        参照 4.docx 第 4 节中关于敏感数据保护的要求。
        """
        sensitive_keys = {"password", "secret", "token", "api_key", "authorization", "credential"}
        sanitized = {}
        for key, value in parameters.items():
            if key.lower() in sensitive_keys:
                sanitized[key] = "***REDACTED***"
            elif isinstance(value, dict):
                sanitized[key] = ToolSecurityGuard._sanitize_params(value)
            elif isinstance(value, list):
                sanitized[key] = [
                    ToolSecurityGuard._sanitize_params(v) if isinstance(v, dict) else v
                    for v in value
                ]
            else:
                sanitized[key] = value
        return sanitized

    def register_tool(self, permission: ToolPermission) -> None:
        """注册工具权限配置。

        Args:
            permission: 工具权限配置实例。
        """
        self._registry[permission.tool_name] = permission
        logger.info(
            "工具已注册: name=%s risk=%s confirmation=%s rate_limit=%s",
            permission.tool_name,
            permission.risk_level.value,
            permission.require_confirmation,
            permission.rate_limit,
        )

    def unregister_tool(self, tool_name: str) -> None:
        """注销工具权限配置。

        Args:
            tool_name: 工具名称。
        """
        self._registry.pop(tool_name, None)
        logger.info("工具已注销: name=%s", tool_name)