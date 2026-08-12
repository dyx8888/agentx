# ==========================================
# 邮件发送工具模块
# ==========================================
# 基于 Python 标准库 smtplib + email.mime 实现，无需额外第三方依赖。
# SMTP 配置从环境变量读取，未配置时降级跳过（不抛异常），用于：
#   - 密码找回（auth_router.forgot_password）
#   - 注册验证邮件（未来扩展）
#   - 其他需要通知用户的场景
#
# 环境变量：
#   SMTP_HOST      — SMTP 服务器地址（如 smtp.gmail.com / smtp.qq.com）
#   SMTP_PORT      — SMTP 端口（默认 587，STARTTLS 标准端口）
#   SMTP_USER      — 登录账号
#   SMTP_PASSWORD  — 登录密码或授权码（QQ/163 等需用授权码）
#   SMTP_FROM      — 发件人地址（未设置时默认同 SMTP_USER）
#   SMTP_USE_TLS   — 是否启用 STARTTLS 加密（默认 true）
#                     端口 465 时可设为 false 走隐式 SSL（SMTPS）
# """

import asyncio
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from app.core.logging import get_logger

logger = get_logger(__name__)


def _read_smtp_config() -> dict | None:
    """读取 SMTP 环境变量配置。

    Returns:
        配置字典；任一必填项缺失则返回 None，调用方应据此降级跳过发送。
    """
    host = os.getenv("SMTP_HOST")
    port = int(os.getenv("SMTP_PORT", "587"))
    user = os.getenv("SMTP_USER")
    password = os.getenv("SMTP_PASSWORD")
    # 发件人默认同登录账号，避免未配置 SMTP_FROM 时报错
    from_addr = os.getenv("SMTP_FROM") or user
    # SMTP_USE_TLS 默认 true：587 端口标准做法是 STARTTLS
    use_tls = os.getenv("SMTP_USE_TLS", "true").lower() in ("true", "1", "yes", "on")

    # 必填项校验：缺少任意一项都无法发送，返回 None 触发降级
    if not all([host, user, password, from_addr]):
        return None
    return {
        "host": host,
        "port": port,
        "user": user,
        "password": password,
        "from": from_addr,
        "use_tls": use_tls,
    }


def _strip_html(html: str) -> str:
    """粗略去除 HTML 标签，生成纯文本兜底内容（保证不支持 HTML 的客户端可读）。"""
    # 先把 <br> / </p> 等块级标签转成换行，再去除剩余标签
    text = re.sub(r"(?i)<\s*br\s*/?\s*>", "\n", html)
    text = re.sub(r"(?i)</\s*(p|div|tr)\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


def _build_message(from_addr: str, to: str, subject: str, body: str, html: bool) -> MIMEMultipart:
    """构建 MIME 邮件。

    HTML 邮件同时附纯文本 alternative，提升送达率与兼容性。
    """
    # alternative 类型：客户端按优先级选择展示 HTML 或纯文本
    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject

    if html:
        # HTML 在前、纯文本在后（RFC 建议先简后繁，客户端取最后一个能渲染的）
        msg.attach(MIMEText(_strip_html(body), "plain", "utf-8"))
        msg.attach(MIMEText(body, "html", "utf-8"))
    else:
        msg.attach(MIMEText(body, "plain", "utf-8"))
    return msg


def _send_sync(cfg: dict, to: str, subject: str, body: str, html: bool) -> bool:
    """同步发送邮件（应在 executor 线程中调用，避免阻塞事件循环）。

    端口 465 且未启用 STARTTLS 时走隐式 SSL（SMTPS）；其余情况走 SMTP + STARTTLS。
    """
    msg = _build_message(cfg["from"], to, subject, body, html)

    # 统一设置 30s 超时，避免网络异常时协程长时间挂起
    if cfg["port"] == 465 and not cfg["use_tls"]:
        # 隐式 SSL 连接（SMTPS，常见于 465 端口）
        with smtplib.SMTP_SSL(cfg["host"], cfg["port"], timeout=30) as server:
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [to], msg.as_string())
    else:
        # 普通连接 + STARTTLS 升级（587 端口标准流程）
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=30) as server:
            # STARTTLS：在发送认证前将明文连接升级为 TLS 加密，防止凭证被中间人截获
            if cfg["use_tls"]:
                server.starttls()
            server.login(cfg["user"], cfg["password"])
            server.sendmail(cfg["from"], [to], msg.as_string())
    return True


async def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """异步发送邮件。

    用 run_in_executor 包装同步 smtplib 调用，避免阻塞 FastAPI 事件循环。
    发送失败时记录 error 日志但**不抛异常**，返回 False，由调用方决定后续行为。
    未配置 SMTP 时同样返回 False（降级跳过）。

    安全设计：调用方（如密码找回）无需 try/except 包裹本函数，即便邮件发送失败
    也能继续返回对用户一致的响应，避免通过响应差异泄露邮箱是否存在（防枚举）。

    Args:
        to: 收件人邮箱地址
        subject: 邮件主题
        body: 邮件正文（纯文本或 HTML）
        html: body 是否为 HTML，默认 False（纯文本）

    Returns:
        True 发送成功；False 未配置 SMTP 或发送失败。
    """
    cfg = _read_smtp_config()
    if cfg is None:
        # 未配置 SMTP：降级跳过，不阻塞业务流程
        logger.warning("email_send_skipped_no_smtp_config", to=to)
        return False

    loop = asyncio.get_event_loop()
    try:
        # 同步 SMTP 调用放入线程池执行，避免阻塞协程
        return await loop.run_in_executor(None, _send_sync, cfg, to, subject, body, html)
    except Exception as e:
        # 关键：发送失败仅记录日志，不向上抛异常
        # 密码找回等流程即便邮件失败也要给用户一致响应，避免泄露邮箱是否存在
        logger.error(
            "email_send_failed",
            to=to,
            subject=subject,
            smtp_host=cfg["host"],
            smtp_port=cfg["port"],
            error=str(e),
        )
        return False
