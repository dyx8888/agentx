"""
MetricsCollector & AlertManager - 上线质量监控

MetricsCollector: 收集和导出核心质量指标
AlertManager: 基于阈值检查指标并记录告警日志
"""

import threading
from typing import Any, Optional

from app.core.logging import get_logger

logger = get_logger(__name__)


class MetricsCollector:
    """指标收集器

    收集和导出上线质量相关的核心指标：
      - idempotency_hit_rate: 幂等缓存命中率
      - checkpoint_success_rate: checkpoint 成功率
      - loop_false_positive_rate: 循环检测误报率
      - tool_timeout_rate: 工具超时率
      - degradation_trigger_rate: 降级触发率
      - mcp_unhealthy_count: MCP 不健康服务器数量
      - avg_tool_duration_ms: 平均工具调用耗时
      - token_per_request: 每次请求 token 消耗
      - perception_pipeline_latency_ms: 感知管线延迟
    """

    _instance: Optional["MetricsCollector"] = None

    def __new__(cls) -> "MetricsCollector":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._lock = threading.Lock()

        # ── 幂等性指标 ──
        self._idempotency_hits: int = 0
        self._idempotency_total: int = 0

        # ── Checkpoint 指标 ──
        self._checkpoint_successes: int = 0
        self._checkpoint_total: int = 0

        # ── 循环检测指标 ──
        self._loop_false_positives: int = 0
        self._loop_detections_total: int = 0

        # ── 工具超时指标 ──
        self._tool_timeouts: int = 0
        self._tool_calls_total: int = 0

        # ── 降级触发指标 ──
        self._degradation_triggers: int = 0
        self._degradation_checks_total: int = 0

        # ── MCP 健康指标 ──
        self._mcp_unhealthy_count: int = 0

        # ── 工具耗时指标 ──
        self._tool_duration_ms_sum: float = 0.0
        self._tool_duration_count: int = 0

        # ── Token 消耗指标 ──
        self._token_sum: int = 0
        self._token_request_count: int = 0

        # ── 感知管线延迟指标 ──
        self._perception_latency_ms_sum: float = 0.0
        self._perception_latency_count: int = 0

    # ── 记录方法 ─────────────────────────────────────────────────

    def record_idempotency(self, hit: bool) -> None:
        """记录一次幂等检查结果"""
        with self._lock:
            self._idempotency_total += 1
            if hit:
                self._idempotency_hits += 1

    def record_checkpoint(self, success: bool) -> None:
        """记录一次 checkpoint 操作结果"""
        with self._lock:
            self._checkpoint_total += 1
            if success:
                self._checkpoint_successes += 1

    def record_loop_detection(self, false_positive: bool) -> None:
        """记录一次循环检测结果"""
        with self._lock:
            self._loop_detections_total += 1
            if false_positive:
                self._loop_false_positives += 1

    def record_tool_timeout(self, timeout: bool) -> None:
        """记录一次工具调用超时情况"""
        with self._lock:
            self._tool_calls_total += 1
            if timeout:
                self._tool_timeouts += 1

    def record_degradation(self, triggered: bool) -> None:
        """记录一次降级检查结果"""
        with self._lock:
            self._degradation_checks_total += 1
            if triggered:
                self._degradation_triggers += 1

    def set_mcp_unhealthy_count(self, count: int) -> None:
        """设置 MCP 不健康服务器数量"""
        with self._lock:
            self._mcp_unhealthy_count = count

    def record_tool_duration(self, duration_ms: float) -> None:
        """记录一次工具调用耗时（毫秒）"""
        with self._lock:
            self._tool_duration_ms_sum += duration_ms
            self._tool_duration_count += 1

    def record_token_usage(self, token_count: int) -> None:
        """记录一次请求的 token 消耗"""
        with self._lock:
            self._token_sum += token_count
            self._token_request_count += 1

    def record_perception_latency(self, latency_ms: float) -> None:
        """记录一次感知管线延迟（毫秒）"""
        with self._lock:
            self._perception_latency_ms_sum += latency_ms
            self._perception_latency_count += 1

    # ── 导出方法 ─────────────────────────────────────────────────

    def get_idempotency_hit_rate(self) -> float:
        """获取幂等缓存命中率 (0.0 ~ 1.0)"""
        with self._lock:
            if self._idempotency_total == 0:
                return 0.0
            return self._idempotency_hits / self._idempotency_total

    def get_checkpoint_success_rate(self) -> float:
        """获取 checkpoint 成功率 (0.0 ~ 1.0)"""
        with self._lock:
            if self._checkpoint_total == 0:
                return 1.0
            return self._checkpoint_successes / self._checkpoint_total

    def get_loop_false_positive_rate(self) -> float:
        """获取循环检测误报率 (0.0 ~ 1.0)"""
        with self._lock:
            if self._loop_detections_total == 0:
                return 0.0
            return self._loop_false_positives / self._loop_detections_total

    def get_tool_timeout_rate(self) -> float:
        """获取工具超时率 (0.0 ~ 1.0)"""
        with self._lock:
            if self._tool_calls_total == 0:
                return 0.0
            return self._tool_timeouts / self._tool_calls_total

    def get_degradation_trigger_rate(self) -> float:
        """获取降级触发率 (0.0 ~ 1.0)"""
        with self._lock:
            if self._degradation_checks_total == 0:
                return 0.0
            return self._degradation_triggers / self._degradation_checks_total

    def get_mcp_unhealthy_count(self) -> int:
        """获取 MCP 不健康服务器数量"""
        with self._lock:
            return self._mcp_unhealthy_count

    def get_avg_tool_duration_ms(self) -> float:
        """获取平均工具调用耗时（毫秒）"""
        with self._lock:
            if self._tool_duration_count == 0:
                return 0.0
            return self._tool_duration_ms_sum / self._tool_duration_count

    def get_avg_tokens_per_request(self) -> float:
        """获取平均每次请求 token 消耗"""
        with self._lock:
            if self._token_request_count == 0:
                return 0.0
            return self._token_sum / self._token_request_count

    def get_avg_perception_latency_ms(self) -> float:
        """获取平均感知管线延迟（毫秒）"""
        with self._lock:
            if self._perception_latency_count == 0:
                return 0.0
            return self._perception_latency_ms_sum / self._perception_latency_count

    def get_all_metrics(self) -> dict[str, Any]:
        """获取所有指标的快照"""
        return {
            "idempotency_hit_rate": self.get_idempotency_hit_rate(),
            "checkpoint_success_rate": self.get_checkpoint_success_rate(),
            "loop_false_positive_rate": self.get_loop_false_positive_rate(),
            "tool_timeout_rate": self.get_tool_timeout_rate(),
            "degradation_trigger_rate": self.get_degradation_trigger_rate(),
            "mcp_unhealthy_count": self.get_mcp_unhealthy_count(),
            "avg_tool_duration_ms": self.get_avg_tool_duration_ms(),
            "avg_tokens_per_request": self.get_avg_tokens_per_request(),
            "avg_perception_latency_ms": self.get_avg_perception_latency_ms(),
        }


class AlertManager:
    """告警管理器

    基于阈值检查 MetricsCollector 中的指标，超过阈值时记录 WARNING 日志。
    9 条阈值规则覆盖关键质量指标。
    """

    # 阈值规则: (指标名, 阈值, 比较方向, 告警消息)
    THRESHOLD_RULES: list[tuple[str, float, str, str]] = [
        (
            "idempotency_hit_rate",
            0.50,
            "gt",
            "idempotency_hit_rate > 50%: possible cache staleness",
        ),
        (
            "checkpoint_success_rate",
            0.95,
            "lt",
            "checkpoint_success_rate < 95%: possible Redis issues",
        ),
        (
            "loop_false_positive_rate",
            0.10,
            "gt",
            "loop_false_positive_rate > 10%: detection too aggressive",
        ),
        (
            "tool_timeout_rate",
            0.20,
            "gt",
            "tool_timeout_rate > 20%: tools may be overloaded",
        ),
        (
            "degradation_trigger_rate",
            0.10,
            "gt",
            "degradation_trigger_rate > 10%: frequent fallback to degradation",
        ),
        (
            "mcp_unhealthy_count",
            0,
            "gt",
            "mcp_unhealthy_count > 0: MCP server issues detected",
        ),
        (
            "avg_tool_duration_ms",
            5000,
            "gt",
            "avg_tool_duration_ms > 5000: tool calls are slow",
        ),
        (
            "avg_tokens_per_request",
            50000,
            "gt",
            "avg_tokens_per_request > 50000: high token consumption",
        ),
        (
            "avg_perception_latency_ms",
            1000,
            "gt",
            "avg_perception_latency_ms > 1000: perception pipeline slow",
        ),
    ]

    _instance: Optional["AlertManager"] = None

    def __new__(cls) -> "AlertManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        self._initialized = True
        self._collector = get_metrics_collector()

    def check_all(self) -> list[dict[str, Any]]:
        """检查所有阈值规则，返回触发的告警列表"""
        alerts: list[dict[str, Any]] = []
        metrics = self._collector.get_all_metrics()

        for metric_name, threshold, direction, message in self.THRESHOLD_RULES:
            current_value = metrics.get(metric_name)
            if current_value is None:
                continue

            triggered = False
            if direction == "gt":
                triggered = current_value > threshold
            elif direction == "lt":
                triggered = current_value < threshold

            if triggered:
                alert = {
                    "metric": metric_name,
                    "current_value": current_value,
                    "threshold": threshold,
                    "direction": direction,
                    "message": message,
                }
                alerts.append(alert)
                logger.warning(
                    "monitoring_alert_threshold_breached",
                    metric=metric_name,
                    current_value=current_value,
                    threshold=threshold,
                    message=message,
                )

        return alerts

    def check_metric(self, metric_name: str) -> Optional[dict[str, Any]]:
        """检查单个指标的阈值，若触发则返回告警详情，否则返回 None"""
        metrics = self._collector.get_all_metrics()
        current_value = metrics.get(metric_name)
        if current_value is None:
            return None

        for rule_metric, threshold, direction, message in self.THRESHOLD_RULES:
            if rule_metric != metric_name:
                continue

            triggered = False
            if direction == "gt":
                triggered = current_value > threshold
            elif direction == "lt":
                triggered = current_value < threshold

            if triggered:
                alert = {
                    "metric": metric_name,
                    "current_value": current_value,
                    "threshold": threshold,
                    "direction": direction,
                    "message": message,
                }
                logger.warning(
                    "monitoring_alert_threshold_breached",
                    metric=metric_name,
                    current_value=current_value,
                    threshold=threshold,
                    message=message,
                )
                return alert

        return None


# ── 全局单例 ─────────────────────────────────────────────────────

_metrics_collector: Optional[MetricsCollector] = None
_alert_manager: Optional[AlertManager] = None


def get_metrics_collector() -> MetricsCollector:
    """获取全局 MetricsCollector 单例"""
    global _metrics_collector
    if _metrics_collector is None:
        _metrics_collector = MetricsCollector()
    return _metrics_collector


def get_alert_manager() -> AlertManager:
    """获取全局 AlertManager 单例"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = AlertManager()
    return _alert_manager