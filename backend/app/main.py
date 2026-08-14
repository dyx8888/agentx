# FastAPI 主应用模块 —— 作为整个后端服务的单一入口点，负责组装所有中间件、路由和生命周期管理
# 采用统一入口模式而非多文件启动，便于集中管理 CORS、异常处理、监控等横切关注点
"""
FastAPI Main Application for AgentX Platform
Entry point for the web API with chat and feedback endpoints
"""

import datetime  # 用于异常响应中生成 UTC 时间戳，确保跨时区客户端能统一解析

import os  # 读取环境变量判断数据库类型（PostgreSQL/SQLite），以及 Redis/Milvus 连接参数
import signal  # 捕获 SIGTERM/SIGINT 信号实现优雅停机，避免进程被直接 kill 导致资源泄漏
import sys  # sys.excepthook 用于拦截未被线程捕获的异常，防止静默崩溃
from contextlib import asynccontextmanager  # FastAPI 推荐的 lifespan 模式，比 on_event 更符合 asyncio 语义

from dotenv import load_dotenv  # 在代码最早期加载 .env 文件，确保后续所有 os.getenv 调用都能读取到配置

load_dotenv()  # 必须在任何配置读取之前调用，否则 os.getenv 会返回 None 导致数据库等连接失败

import uvicorn  # 仅用于 __main__ 块中的开发服务器启动，生产环境用 gunicorn + uvicorn workers 替代
from fastapi import FastAPI, HTTPException, Request  # HTTPException 用于全局异常处理器路由；Request 用于提取请求元数据做日志追踪
from fastapi.middleware.cors import CORSMiddleware  # 浏览器同源策略下，前后端分离部署必须配置 CORS，否则前端请求会被拦截
from fastapi.responses import JSONResponse  # 异常处理器返回统一 JSON 格式，方便客户端统一解析错误信息

from app.core.logging import get_logger, log_error  # 使用结构化日志而非 print，便于接入 ELK/Loki 等日志系统做聚合查询

logger = get_logger(__name__)  # 模块级别的 logger，__name__ 确保日志来源可追溯到 main 模块


def _is_production() -> bool:
    env = (os.getenv("ENVIRONMENT") or os.getenv("ENV") or "").strip().lower()
    return env in {"production", "prod"}


def _env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _split_csv_env(name: str) -> list[str]:
    raw = os.getenv(name, "")
    return [value.strip().rstrip("/") for value in raw.split(",") if value.strip()]


def _get_cors_origins() -> list[str]:
    origins = _split_csv_env("CORS_ORIGINS")
    if not origins and _is_production():
        frontend_url = os.getenv("FRONTEND_URL", "").strip().rstrip("/")
        origins = [frontend_url] if frontend_url else []
    if not origins:
        origins = [
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ]

    if _is_production():
        if not origins:
            raise RuntimeError("CORS_ORIGINS or FRONTEND_URL must be set in production")
        if "*" in origins:
            raise RuntimeError("CORS_ORIGINS cannot contain '*' in production")
    return origins


def _docs_enabled() -> bool:
    return _env_flag("ENABLE_PUBLIC_DOCS", default=not _is_production())


def _evolution_api_enabled() -> bool:
    return _env_flag("ENABLE_EVOLUTION_API", default=not _is_production())


CORS_ALLOW_ORIGINS = _get_cors_origins()
DOCS_ENABLED = _docs_enabled()
EVOLUTION_API_ENABLED = _evolution_api_enabled()


def _is_origin_allowed(origin: str) -> bool:
    normalized = (origin or "").strip().rstrip("/")
    return bool(normalized) and ("*" in CORS_ALLOW_ORIGINS or normalized in CORS_ALLOW_ORIGINS)


def _install_excepthook():
    # FastAPI 的异常处理器只能捕获 HTTP 请求线程中的异常，后台线程（如定时任务、线程池）中的异常会静默丢失
    # 通过 sys.excepthook 兜底拦截所有未被捕获的异常，确保生产环境问题可追溯
    """Install global exception hook for unhandled exceptions in non-HTTP threads"""
    _original_excepthook = sys.excepthook  # 保存原始 hook 以便在自定义处理之后继续执行默认行为（打印 traceback）

    def _global_excepthook(exc_type, exc_value, exc_tb):
        logger.critical(  # 使用 critical 级别，因为未处理异常意味着程序状态可能已损坏，需要最高优先级告警
            "unhandled_exception",
            exc_type=exc_type.__name__ if exc_type else "None",  # exc_type 可能为 None（某些边缘情况），防御性处理避免 AttributeError
            error_message=str(exc_value),
        )
        _original_excepthook(exc_type, exc_value, exc_tb)  # 调用原始 hook 保留标准错误输出，不影响开发调试体验

    sys.excepthook = _global_excepthook
    logger.info("global_excepthook_installed")  # 确认安装成功，便于排查"为什么异常没有日志"的问题


def _install_signal_handlers():
    # Docker/K8s 环境下通过 SIGTERM 通知容器停止，SIGINT 用于本地 Ctrl+C
    # 如果不捕获这些信号，进程会被直接终止，可能导致正在处理的请求丢失或数据库连接未释放
    """Install signal handlers for graceful shutdown with crash logging"""

    def _handle_signal(signum, frame):
        sig_name = signal.Signals(signum).name  # 将信号编号转为可读名称，方便日志检索和告警规则匹配
        logger.warning(  # warning 级别因为正常关停是预期行为，但需要记录以便排查"为什么服务重启了"
            "signal_received",
            signal=sig_name,
            signal_number=signum,  # 同时保留编号，某些环境下信号名称可能因平台差异而不同
        )
        sys.exit(0)  # 以 0 退出表示正常关停，避免容器编排系统误判为崩溃重启

    signal.signal(signal.SIGTERM, _handle_signal)  # SIGTERM 是 K8s pod 终止的标准信号
    signal.signal(signal.SIGINT, _handle_signal)  # SIGINT 是本地开发 Ctrl+C 的信号，逻辑一致所以复用同一 handler
    logger.info("signal_handlers_installed")


_install_excepthook()  # 在模块加载的最早期安装，确保任何后续 import 触发的线程异常都能被捕获
_install_signal_handlers()  # 紧随其后安装信号处理器，因为 import 阶段也可能收到终止信号

# Import API routers
# Legacy get_agent_async removed; unified AgentRuntime is the single agent entry point
from app.api.admin.admin import router as admin_router  # admin 路由单独命名以区分其他 admin 子模块
from app.api.a2a import router as a2a_router
from app.api.agent_communication import router as agent_communication_router  # agent 间通信路由，支持多 agent 协作消息传递
from app.api.agents import router as agents_router
from app.api.auth_router import router as auth_router
from app.api.chat import router as chat_router  # 核心聊天接口，所有用户对话的入口
from app.api.companies import router as companies_router
from app.api.dashboard import router as dashboard_router  # 仪表盘数据聚合接口
from app.api.feedback import router as feedback_router  # 用户反馈收集，用于 RLHF 和模型优化
from app.api.knowledge import router as knowledge_router  # 知识库管理，RAG 检索增强的数据源
from app.api.subscription import router as subscription_router
from app.api.conversations import router as conversations_router
from app.api.tools import router as tools_router
from app.middleware.logging import setup_logging_middleware  # 请求日志中间件，自动记录每个请求的耗时、状态码等
from app.monitoring.metrics import setup_metrics  # Prometheus 指标暴露，用于 Grafana 监控面板
from app.runtime.orchestrator import AgentRuntime  # New AgentRuntime for Plan-Execute-Reflect
# Plan-Execute-Reflect 模式：先规划 → 执行 → 反思，比纯 ReAct 模式更适合多步骤复杂任务
from app.skills.registry import skill_registry  # 技能注册表，管理 agent 可调用的结构化技能
from app.tools.registry import registry  # 工具注册表，管理 agent 可调用的外部工具（API、函数等）


@asynccontextmanager  # 使用 async context manager 而非 on_event 装饰器：lifespan 模式是 FastAPI 推荐的现代写法，支持 async 初始化
async def lifespan(app: FastAPI):
    # lifespan 分为 yield 前（启动）和 yield 后（关闭）两个阶段，保证资源初始化和释放的对称性
    """Initialize Agent on startup"""
    from app.database import init_database  # 延迟导入避免循环依赖：main 是入口模块，提前导入所有子模块可能产生循环引用

    init_database()  # 在 agent runtime 之前初始化数据库，因为 runtime 启动时就需要读取 agent 配置
    logger.info("database_initialized")

    logger.info("tool_registry_initializing")
    registry.initialize_from_config()  # 工具注册必须先于 skill 注册，因为 skill 可能依赖已注册的工具

    logger.info("skill_registry_initializing")
    skill_registry.load_from_config()  # 技能加载在 runtime 初始化之前，确保 agent 启动时所有技能立即可用

    runtime = AgentRuntime()  # AgentRuntime 是全局单例，管理所有 agent 的生命周期和执行调度
    await runtime.initialize()  # async 初始化：可能涉及模型加载、外部服务连接等 I/O 操作
    app.state.runtime = runtime  # 挂载到 app.state 上，所有请求处理器通过 request.app.state.runtime 访问
    logger.info("agent_runtime_initialized")

    logger.info("startup_complete")  # 标记所有初始化步骤完成，日志中这条记录之后才代表服务真正就绪

    # Start evolution services (sleep consolidation, memory auto-write)
    if EVOLUTION_API_ENABLED:
        from app.services.evolution import start_evolution_services  # 延迟导入避免循环依赖
        start_evolution_services()  # 进化服务包括睡眠记忆整合和自动写回，在运行时启动后异步运行
        logger.info("evolution_services_started")
    else:
        logger.info("evolution_services_disabled")

    yield  # yield 之前是 startup 阶段，之后是 shutdown 阶段；当服务收到终止信号时从 yield 处恢复执行

    # Stop evolution services on shutdown
    if EVOLUTION_API_ENABLED:
        from app.services.evolution import stop_evolution_services
        stop_evolution_services()  # 确保后台定时任务停止，防止进程退出后仍有残留线程
    logger.info("shutting_down")  # 最后一条日志，标志着优雅关闭流程完成

# Create FastAPI application
app = FastAPI(
    title="AgentX Platform API",  # OpenAPI 文档标题，自动生成到 /docs 和 /redoc 页面
    description="Brand Business Digital Assistant API",  # 描述信息会显示在 Swagger UI 顶部，帮助前端开发者理解 API 用途
    version="1.0.0",  # API 版本号，用于 OpenAPI schema 的 version 字段，方便客户端做版本兼容
    lifespan=lifespan,  # 将 lifespan 上下文管理器绑定到 app，替代旧的 on_event("startup")/on_event("shutdown") 模式
    docs_url="/docs" if DOCS_ENABLED else None,
    redoc_url="/redoc" if DOCS_ENABLED else None,
    openapi_url="/openapi.json" if DOCS_ENABLED else None,
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,  # Starlette 的 CORS 中间件，在处理业务逻辑之前拦截 OPTIONS 预检请求
    allow_origins=CORS_ALLOW_ORIGINS,
    allow_credentials=True,  # 允许携带 Cookie/Authorization header；生产环境必须配置明确来源
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],  # 显式列出方法比用 ["*"] 更安全，避免 TRACE 等危险方法被允许
    allow_headers=["*"],  # 允许所有请求头，因为前端可能发送自定义 header（如 X-Request-ID 链路追踪）
)

# Setup logging and monitoring middleware
setup_logging_middleware(app)  # 在 CORS 之后注册，确保所有经过 CORS 校验的请求都被记录日志

# Setup monitoring metrics
setup_metrics(app)  # 暴露 /metrics 端点给 Prometheus 抓取，必须在路由之前设置以拦截指标请求

# Setup rate limiter
from app.middleware.rate_limiter import setup_rate_limiter  # 延迟导入避免 rate_limiter 模块在 app 创建前被加载

setup_rate_limiter(app)  # 限流中间件应在所有路由之前注册，确保每个请求都经过频率检查

# Include routers
# 所有路由统一加 /api 前缀，与非 API 资源（如 /docs、/health）区分，方便网关层做路由规则
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])  # 认证接口放在最前面，是其他所有受保护接口的前置依赖
app.include_router(chat_router, prefix="/api/chat", tags=["chat"])  # chat 是核心业务路由，前缀与功能名一致便于前端理解
app.include_router(conversations_router, prefix="/api/conversations", tags=["conversations"])  # 对话管理 CRUD，支持多轮会话的创建、列表、详情和删除

from app.api.kol import router as kol_router  # 达人搜索 API — 多条件筛选、排序、导出
app.include_router(kol_router, prefix="/api/kol", tags=["kol"])
from app.api.platforms import router as platforms_router

app.include_router(platforms_router, prefix="/api/platforms", tags=["platforms"])
app.include_router(feedback_router, prefix="/api/feedback", tags=["feedback"])  # feedback 独立路由，支持用户对对话结果的评价收集
app.include_router(companies_router, prefix="/api/admin/companies", tags=["admin"])  # admin 子路由统一用 /api/admin 前缀做权限网关隔离
if EVOLUTION_API_ENABLED:
    from app.api.evolution import router as evolution_router  # agent 进化引擎的配置和管理接口
    app.include_router(evolution_router, prefix="/api/admin/evolution", tags=["evolution"])  # evolution 标签独立，方便在 Swagger 文档中分组查看
else:
    logger.info("evolution_api_disabled")
app.include_router(knowledge_router, prefix="/api/knowledge", tags=["knowledge"])  # 知识库独立前缀，便于未来做 CDN 缓存或独立扩展
from app.api.rag import router as rag_router

app.include_router(rag_router, prefix="/api/rag", tags=["rag"])

# Add cost management API
from app.api.admin.costs import router as costs_router  # 延迟导入：cost 模块可能依赖已注册的其他路由

app.include_router(costs_router, prefix="/api/admin/costs", tags=["costs"])  # 成本管理是 admin 功能的一部分，共用 /api/admin 前缀
app.include_router(tools_router, prefix="/api/admin/tools", tags=["admin"])
app.include_router(agents_router, prefix="/api/admin/agents", tags=["admin"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])  # 同一个 router 注册两次：/api/admin/agents 给管理员，/api/agents 给普通用户

# Include task management router
from app.api import tasks as tasks_module  # 使用模块引用而非直接导入 router，避免 tasks 模块的顶层代码在 import 时执行

app.include_router(tasks_module.router, prefix="/api/tasks", tags=["tasks"])  # 异步任务管理独立路由，支持长耗时任务的提交与状态查询

# Include agent communication router
app.include_router(agent_communication_router, prefix="/api/agent")  # agent 通信不加 tags，可能是不需要在 Swagger 中公开的内部接口
app.include_router(a2a_router, prefix="/api", tags=["a2a"])

# Include workflow router
from app.workflow.api import router as workflow_router  # workflow 模块较重，延迟导入避免影响启动速度

app.include_router(workflow_router, prefix="/api/workflows")  # 工作流引擎独立路由，编排多步骤 agent 协作流程

# Include subscription router
app.include_router(subscription_router, prefix="/api/subscription", tags=["subscription"])  # 订阅管理独立路由，与计费系统对接

# Include WebSocket router
from app.ws import router as ws_router  # WebSocket 模块可能包含连接池等重量级资源，延迟导入

app.include_router(ws_router, prefix="/ws", tags=["websocket"])  # WebSocket 用 /ws 前缀而非 /api/ws，因为 WS 不是 RESTful 资源

app.include_router(dashboard_router, prefix="/api/dashboard", tags=["dashboard"])

app.include_router(admin_router, prefix="/admin", tags=["admin"])  # admin 路由直接挂 /admin，不走 /api 前缀，可能面向内部管理页面

@app.get("/")  # 根路径不设 prefix，方便负载均衡器和健康检查直接访问
async def root():
    # 返回 API 导航信息而非空响应，帮助开发者快速了解可用端点，减少看文档的次数
    """Root endpoint with comprehensive API information"""
    endpoints = {
        "health": "/health",
        "auth": "/api/auth",
        "chat": "/api/chat",
        "kol": "/api/kol",
        "knowledge": "/api/knowledge",
    }
    if DOCS_ENABLED:
        endpoints["docs"] = "/docs"
    return {
        "service": "AgentX Platform API",
        "version": "1.0.0",
        "description": "Multi-agent collaboration platform with HTTP tool services",
        "endpoints": endpoints,
        "agent_types": {  # 暴露 agent 类型信息，前端可据此动态展示不同的对话界面
            "amy": "Business specialist - KOL outreach and collaboration",
            "ben": "Data analysis specialist - Performance reporting and strategy"
        }
    }

# Global exception handlers
# 使用 @app.exception_handler 而非中间件捕获异常：异常处理器返回标准 JSON，中间件只能修改 response
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    # HTTPException 是业务逻辑主动抛出的已知异常（如 404、401），需要区分于未知 Exception 做不同处理
    """Handle HTTP exceptions with structured logging"""
    log_error(
        exc,
        context={
            "request_method": request.method,  # 记录请求方法用于分析哪些接口更容易出错
            "request_url": str(request.url),  # 完整 URL 包含 query 参数，便于复现问题
            "status_code": exc.status_code,  # 直接记录状态码，日志聚合时可按状态码分组统计
            "detail": exc.detail  # HTTPException 的 detail 通常是业务层设置的友好提示，直接透传给客户端
        }
    )

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "error": True,  # 统一 error 标志位，客户端无需判断 HTTP 状态码即可快速识别错误响应
            "message": exc.detail,
            "status_code": exc.status_code,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z"  # UTC 时间 + Z 后缀，符合 ISO 8601 标准，避免时区歧义
        }
    )

@app.exception_handler(Exception)  # 捕获所有未被 HTTPException handler 处理的异常，属于兜底策略
async def general_exception_handler(request: Request, exc: Exception):
    # 未知异常意味着代码可能有 bug，需记录完整上下文以便事后排查
    """Handle unexpected exceptions"""
    log_error(
        exc,
        context={
            "request_method": request.method,
            "request_url": str(request.url),
            "exception_type": type(exc).__name__  # 记录异常类型名，帮助快速定位是 ValueError 还是 KeyError 等
        }
    )

    return JSONResponse(
        status_code=500,  # 所有未知异常统一返回 500，不暴露内部错误细节给客户端，防止信息泄露
        content={
            "error": True,
            "message": "Internal server error",  # 对外统一文案，内部细节仅记录在服务端日志中
            "status_code": 500,
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z"
        }
    )

@app.get("/health")  # 健康检查独立于 /api 前缀，方便 K8s liveness/readiness probe 直接访问
async def health_check():
    # 分级健康检查：不仅报告"活着"，还检查关键依赖是否可用，支持 K8s 根据 degraded 状态决定是否摘流量
    """Enhanced health check endpoint"""
    checks = {}  # 字典存储各组件的健康状态，方便扩展新的检查项
    overall = "healthy"  # 默认健康，任一项检查失败则降级为 degraded

    try:
        from app.database import db  # 延迟导入 db 模块，避免数据库未初始化时导入报错
        if hasattr(db, 'get_connection'):  # 兼容两种数据库访问模式：直接连接对象或 SQLAlchemy engine
            conn = db.get_connection()
            conn.close()  # 立即关闭连接避免泄漏，仅验证连通性
        else:
            from app.database.core import get_engine  # 兜底方案：通过 SQLAlchemy engine 执行简单查询
            engine = get_engine()
            with engine.connect() as conn:  # 使用 context manager 保证连接自动归还连接池
                conn.execute("SELECT 1")  # SELECT 1 是最轻量的数据库探活查询，不依赖任何表存在
        checks["database"] = "healthy"
    except Exception as e:
        checks["database"] = f"unhealthy: {str(e)}"  # 包含错误信息用于排查，但生产环境可能需要脱敏
        overall = "degraded"  # 数据库不可用但服务还能响应 /health，属于降级而非完全不可用

    try:
        import redis  # 延迟导入，未安装 redis 包时不阻塞整个 health 检查
        redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # 默认值保证本地开发环境不配置也能运行
        r = redis.from_url(redis_url, socket_connect_timeout=2)  # 2 秒超时防止 health 检查本身因网络问题卡死
        r.ping()  # Redis PING 命令是最轻量的探活方式
        r.close()  # 手动关闭连接，因为 from_url 创建的连接不在连接池管理范围内
        checks["redis"] = "healthy"
    except Exception as e:
        checks["redis"] = f"unavailable: {str(e)}"  # Redis 不可用不标记为 unhealthy，因为 Redis 是缓存层，服务可降级运行

    try:
        milvus_host = os.getenv("MILVUS_HOST", "localhost")  # 向量数据库连接参数从环境变量读取，支持不同部署环境
        milvus_port = os.getenv("MILVUS_PORT", "19530")
        from pymilvus import connections  # 延迟导入 pymilvus，未安装时走 ImportError 分支
        connections.connect(host=milvus_host, port=milvus_port, timeout=2)
        connections.disconnect("default")  # Milvus 使用命名连接，默认连接名为 "default"，用完即断
        checks["milvus"] = "healthy"
    except ImportError:
        checks["milvus"] = "not_installed"  # 区分未安装和不可用：未安装是预期行为（轻量部署），不可用才是问题
    except Exception as e:
        checks["milvus"] = f"unavailable: {str(e)}"

    try:
        from app.tasks.worker import get_task_worker  # 检查后台任务 worker 是否在运行
        worker = get_task_worker()
        checks["task_worker"] = "running" if (worker and worker.is_running) else "stopped"
    except Exception:
        checks["task_worker"] = "unknown"  # worker 模块不存在或初始化失败时标记为 unknown，不做降级判断

    if any("unhealthy" in str(v) for v in checks.values()):  # 仅当有组件明确 unhealthy 时才降级，unavailable 不触发降级
        overall = "degraded"

    return {
        "status": overall,
        "service": "AgentX Platform API",
        "version": "1.0.0",
        "checks": checks,  # 详细检查结果返回给调用方，运维人员可据此快速定位哪个组件出了问题
        "database_type": "PostgreSQL" if os.getenv("DATABASE_URL", "").startswith("postgresql") else "SQLite"  # 推断数据库类型便于运维确认配置是否正确
    }

@app.options("/{path:path}")  # 通配所有路径的 OPTIONS 请求，避免每个路由单独处理 CORS 预检
async def options_handler(path: str, request: Request):
    # 浏览器在跨域请求前发送 OPTIONS 预检，如果后端不响应预检，浏览器会拒绝发送实际请求
    """Handle OPTIONS requests for CORS"""
    headers = {
        "Access-Control-Allow-Methods": "GET, POST, PUT, DELETE, OPTIONS",
        "Access-Control-Allow-Headers": request.headers.get("access-control-request-headers", "*"),
        "Vary": "Origin",
    }
    origin = request.headers.get("origin", "")
    if _is_origin_allowed(origin):
        headers["Access-Control-Allow-Origin"] = origin
        headers["Access-Control-Allow-Credentials"] = "true"
    elif "*" in CORS_ALLOW_ORIGINS and not _is_production():
        headers["Access-Control-Allow-Origin"] = "*"

    return JSONResponse(status_code=200, headers=headers)

if __name__ == "__main__":  # 仅当直接运行此文件时启动 uvicorn，被 gunicorn import 时不执行，避免端口冲突
    uvicorn.run(
        "app.main:app",  # 字符串引用而非直接传 app 对象，uvicorn 会在 worker 进程中重新 import 以支持热重载
        host="0.0.0.0",  # 绑定所有网卡，Docker 容器内必须用 0.0.0.0 否则外部无法访问
        port=8000,  # 默认端口 8000，FastAPI 生态的标准开发端口
        reload=not _is_production(),  # 开发环境启用热重载，生产环境必须关闭
        log_level="info"  # info 级别平衡了可观测性和日志量，debug 级别在生产中会产生过多噪音
    )
