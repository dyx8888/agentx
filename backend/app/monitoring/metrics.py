"""
监控指标模块
定义 Prometheus 指标并暴露 /metrics 端点
"""

import time

from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest

# 全局指标对象
REQUESTS_TOTAL = Counter(
    'agentx_requests_total',
    'Total HTTP requests',
    ['method', 'endpoint', 'status_code']
)

REQUEST_LATENCY = Histogram(
    'agentx_request_latency_seconds',
    'HTTP request latency in seconds',
    buckets=[0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0]
)

AGENT_TASKS_TOTAL = Counter(
    'agentx_agent_tasks_total',
    'Total agent tasks executed',
    ['agent_name', 'status']
)

TOOL_CALLS_TOTAL = Counter(
    'agentx_tool_calls_total',
    'Total MCP tool calls',
    ['tool_name']
)

LLM_TOKENS_TOTAL = Counter(
    'agentx_llm_tokens_total',
    'Total LLM tokens consumed',
    ['model']
)

# 全局中间件状态
_start_time = None

def setup_metrics(app: FastAPI):
    """
    设置监控指标和中间件
    
    Args:
        app: FastAPI 应用实例
    """
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next):
        global _start_time
        _start_time = time.monotonic()

        # 调用下一个中间件
        response = await call_next(request)

        # 记录请求指标
        method = request.method
        endpoint = request.url.path
        status_code = response.status_code

        # 增加请求计数
        REQUESTS_TOTAL.labels(
            method=method,
            endpoint=endpoint,
            status_code=status_code
        ).inc()

        # 记录请求耗时
        if _start_time is not None:
            latency = time.monotonic() - _start_time
            REQUEST_LATENCY.observe(latency)

        return response

    @app.get("/metrics")
    async def metrics_endpoint():
        """Prometheus 指标端点"""
        try:
            # 生成 Prometheus 格式的指标数据
            metrics_data = generate_latest(
                REQUESTS_TOTAL,
                REQUEST_LATENCY,
                AGENT_TASKS_TOTAL,
                TOOL_CALLS_TOTAL,
                LLM_TOKENS_TOTAL
            )

            return Response(
                content=metrics_data,
                media_type="text/plain; version=0.0.4"
            )
        except Exception as e:
            return Response(
                content=f"Error generating metrics: {str(e)}",
                status_code=500,
                media_type="text/plain"
            )

def record_agent_task(agent_name: str, status: str):
    """
    记录数字员工任务执行
    
    Args:
        agent_name: Agent 名称
        status: 任务状态
    """
    AGENT_TASKS_TOTAL.labels(
        agent_name=agent_name,
        status=status
    ).inc()

def record_tool_call(tool_name: str):
    """
    记录 MCP 工具调用
    
    Args:
        tool_name: 工具名称
    """
    TOOL_CALLS_TOTAL.labels(tool_name=tool_name).inc()

def record_llm_tokens(model: str, input_tokens: int, output_tokens: int):
    """
    记录 LLM token 消耗
    
    Args:
        model: 模型名称
        input_tokens: 输入 token 数量
        output_tokens: 输出 token 数量
    """
    total_tokens = input_tokens + output_tokens
    LLM_TOKENS_TOTAL.labels(model=model).inc(total_tokens)
