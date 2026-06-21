import json  # 用于消息序列化/反序列化，JSON格式便于Redis存储和跨语言解析
import os  # 用于读取环境变量，支持不同部署环境的配置
import threading  # 用于线程安全的单例模式和锁保护

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage  # LangChain消息类型，用于构建对话上下文

from app.core.logging import get_logger  # 统一日志记录

logger = get_logger(__name__)  # 模块级logger

REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")  # 环境变量优先，本地默认值作为回退
SESSION_TTL = int(os.getenv("SESSION_TTL_SECONDS", "86400"))  # 默认24小时，平衡内存占用和用户体验
SESSION_MAX_MESSAGES = int(os.getenv("SESSION_MAX_MESSAGES", "50"))  # 最多50条消息，防止上下文过长
SESSION_MAX_TOKENS = int(os.getenv("SESSION_MAX_TOKENS", "8000"))  # 8000 tokens，适配大多数模型的上下文窗口
SESSION_SUMMARY_TTL = int(os.getenv("SESSION_SUMMARY_TTL_SECONDS", "604800"))  # 7天摘要保留，比会话历史更长

_singleton = None  # 模块级单例变量，使用None而非NoneType，避免类型检查问题
_store_lock = threading.Lock()  # 线程锁，确保并发环境下的单例安全创建


def get_session_store() -> "SessionStore":  # 双检锁单例模式，确保全局唯一SessionStore实例
    global _singleton  # 声明全局变量，避免Python将其视为局部变量
    if _singleton is None:  # 第一次检查，避免不必要的锁竞争
        with _store_lock:  # 获取锁，确保线程安全
            if _singleton is None:  # 第二次检查，防止多个线程同时通过第一次检查
                _singleton = SessionStore()  # 创建实例，Redis连接在__init__中初始化
    return _singleton


class SessionStore:  # 会话存储：支持Redis和内存两种后端，Redis不可用时自动降级为内存存储
    def __init__(self):  # 初始化会话存储，优先Redis，不可用时降级为内存
        self._redis = None  # Redis客户端实例，None表示未初始化
        self._memory: dict[str, list] = {}  # 内存回退存储，键为session_id，值为消息列表
        self._summaries: dict[str, str] = {}  # 摘要存储，键为session_id，值为摘要文本
        self._redis_available = False  # Redis可用性标志，用于后续操作判断
        self._init_redis()  # 初始化Redis连接，失败则标记不可用

    def _init_redis(self):  # 尝试连接Redis，失败则静默降级为内存存储
        try:  # 外层try包裹，Redis不可用不应阻止应用启动
            import redis as _redis  # 延迟导入，避免Redis未安装时import失败
            self._redis = _redis.from_url(REDIS_URL, socket_connect_timeout=3)  # 3秒超时，快速失败不阻塞
            self._redis.ping()  # 验证连接有效性，ping失败会抛异常
            self._redis_available = True  # 只有ping成功才标记可用
            logger.info("session_store_redis_connected", url=REDIS_URL)
        except Exception as e:  # 宽泛捕获，Redis不可用不是致命错误
            logger.warning("session_store_redis_unavailable", error=str(e))  # warning级别，因为系统仍可运行

    def _estimate_tokens(self, messages: list[BaseMessage]) -> int:  # 估算token数，避免调用tokenizer的性能开销
        """基于字符数估算 token 数（保守估算：中文 ~1.5 char/token，英文 ~4 char/token）

        使用混合估算策略：
        - 中文字符按 1.5 char/token
        - 非中文字符按 4 char/token
        - 每条消息 +4 tokens overhead（role + formatting）
        """
        total = 0
        for m in messages:  # 逐条消息累加
            content = m.content if isinstance(m.content, str) else str(m.content)  # 安全转换，防止非字符串内容
            chinese_chars = sum(1 for c in content if '\u4e00' <= c <= '\u9fff')  # 统计中文字符，使用Unicode范围
            non_chinese_chars = len(content) - chinese_chars  # 剩余字符视为非中文
            total += int(chinese_chars / 1.5) + int(non_chinese_chars / 4) + 4  # +4是每条消息的固定开销
        return max(total, len(messages))  # 至少每条消息1 token，防止空消息返回0

    def _truncate_by_tokens(self, messages: list[BaseMessage],
                             max_tokens: int) -> tuple[list[BaseMessage], list[BaseMessage]]:  # 按token预算截断，返回(保留, 被截断)
        """按 token 预算截断消息，返回 (保留的消息, 被截断的消息)

        保留最近的消息，从后往前累加 token 直到超出预算。
        """
        if not messages:  # 空列表直接返回
            return [], []

        # 从后往前找截止点
        accumulated = 0  # 累计token数
        cutoff_idx = len(messages)  # 截止索引，默认保留全部
        for i in range(len(messages) - 1, -1, -1):  # 从后往前遍历，保留最近的消息
            msg_tokens = self._estimate_tokens([messages[i]])  # 单条消息的token估算
            if accumulated + msg_tokens > max_tokens:  # 超过预算则停止
                cutoff_idx = i + 1  # 从i+1开始保留（即放弃索引0到i的消息）
                break
            accumulated += msg_tokens

        if cutoff_idx >= len(messages):  # 没有超过预算，全部保留
            return messages, []

        kept = messages[cutoff_idx:]  # 保留最近的消息
        truncated = messages[:cutoff_idx]  # 被截断的旧消息
        return kept, truncated

    def _serialize_messages(self, messages: list[BaseMessage]) -> str:  # 将LangChain消息列表序列化为JSON字符串
        result = []
        for m in messages:  # 逐个转换消息类型到角色映射
            if isinstance(m, HumanMessage):  # 使用isinstance而非type，支持子类
                role = "user"
            elif isinstance(m, SystemMessage):
                role = "system"
            else:  # 默认视为assistant，包括AIMessage和其他类型
                role = "assistant"
            result.append({"role": role, "content": m.content})  # 仅保留role和content，丢弃其他元数据
        return json.dumps(result, ensure_ascii=False)  # ensure_ascii=False保留中文，避免转义

    def _deserialize_messages(self, data: str) -> list[BaseMessage]:  # 将JSON字符串反序列化为LangChain消息列表
        result = []
        for item in json.loads(data):  # 解析JSON
            role = item.get("role", "assistant")  # 默认assistant，兼容旧数据
            if role == "user":
                result.append(HumanMessage(content=item["content"]))
            elif role == "system":
                result.append(SystemMessage(content=item["content"]))
            else:  # assistant或其他角色
                result.append(AIMessage(content=item["content"]))
        return result

    async def _summarize_truncated(self, truncated: list[BaseMessage]) -> str | None:  # 异步方法，使用LLM生成摘要，避免阻塞主线程
        """使用 LLM 将被截断的旧消息压缩成摘要，注入到上下文"""
        if not truncated:  # 没有被截断的消息，无需生成摘要
            return None

        conversation_text_parts = []  # 收集对话片段用于摘要
        for m in truncated[:20]:  # 最多取最近20条被截断消息做摘要，防止上下文过长
            role = "用户" if isinstance(m, HumanMessage) else "助手"  # 中文角色标签，便于LLM理解
            content = m.content if isinstance(m.content, str) else str(m.content)
            conversation_text_parts.append(f"{role}: {content[:300]}")  # 每条消息截取300字符，防止单条过长

        conversation_text = "\n".join(conversation_text_parts)
        if not conversation_text.strip():  # 空内容跳过
            return None

        prompt = f"""请用 2-4 句简短中文摘要以下对话历史的关键信息（核心话题、重要结论、未完成任务等）：

{conversation_text}

只输出摘要文本，不要加任何前缀或格式标记。"""  # 明确指令防止LLM输出多余内容

        try:  # 摘要生成失败不应影响正常的消息存储流程
            from langchain_core.messages import HumanMessage as HMsg  # 使用别名避免与导入的HumanMessage冲突

            from app.services.model_gateway import get_global_model_gateway  # 延迟导入，避免循环依赖

            gateway = get_global_model_gateway()  # 获取全局模型网关单例
            llm = gateway.get_llm()  # 获取默认LLM实例
            response = await llm.ainvoke([HMsg(content=prompt)])  # 异步调用LLM生成摘要
            summary = response.content.strip()
            if summary:  # 仅在有有效摘要时返回
                logger.info("session_summary_generated",
                            truncated_count=len(truncated),
                            summary_len=len(summary))
                return summary
        except Exception as e:  # 摘要生成失败不阻断主流程
            logger.warning("session_summary_generation_failed", error=str(e))

        return None  # 失败或空摘要返回None

    def _merge_summary(self, summary: str | None,
                        messages: list[BaseMessage]) -> list[BaseMessage]:  # 将摘要作为SystemMessage注入到消息列表开头
        """将摘要作为 SystemMessage 注入到消息列表开头"""
        if not summary:  # 无摘要直接返回原消息列表
            return messages
        prefix = SystemMessage(  # 使用SystemMessage，LLM会将其视为系统级上下文
            content=f"[历史会话摘要] {summary}"  # 前缀标记帮助LLM区分摘要和当前对话
        )
        return [prefix] + messages  # 摘要放在最前面，当前消息紧随其后

    def get_history(self, session_id: str) -> list[BaseMessage]:  # 获取会话历史，优先Redis，不可用时降级为内存
        """获取会话历史，按 LangChain 消息格式返回（含摘要注入）"""
        try:  # 外层try包裹，确保存储层异常不会导致应用崩溃
            summary = None
            messages = []

            if self._redis_available:  # Redis可用时优先使用Redis
                raw = self._redis.get(f"session:{session_id}")  # 使用命名空间前缀，避免key冲突
                if raw:  # 仅在有数据时反序列化
                    messages = self._deserialize_messages(raw.decode("utf-8"))  # Redis返回bytes，需要decode
                raw_summary = self._redis.get(f"session:{session_id}:summary")  # 独立的摘要key
                if raw_summary:
                    summary = raw_summary.decode("utf-8")
            else:  # Redis不可用时降级为内存存储
                messages = self._memory.get(session_id, [])
                summary = self._summaries.get(session_id)

            return self._merge_summary(summary, messages)  # 将摘要注入到消息列表开头
        except Exception as e:  # 宽泛捕获，任何存储层异常都不应中断调用链
            logger.error("session_store_get_history_error", error=str(e), session_id=session_id)
        return []  # 异常时返回空列表，确保调用方不会空指针

    async def append_exchange(self, session_id: str, human_msg: str, ai_msg: str):  # 异步方法，因为涉及LLM摘要生成
        """追加一轮对话到会话历史，使用 token 智能截断 + LLM 摘要压缩"""
        try:  # 外层try确保存储异常不影响主流程
            history = self.get_history(session_id)  # 获取现有历史
            # 去掉可能的摘要前缀消息，做纯 fact 历史
            pure_history = [m for m in history if not (  # 过滤掉摘要SystemMessage，因为新一轮会重新生成
                isinstance(m, SystemMessage) and
                m.content.startswith("[历史会话摘要]")
            )]

            pure_history.append(HumanMessage(content=human_msg))  # 追加用户消息
            pure_history.append(AIMessage(content=ai_msg))  # 追加AI回复

            summary = None
            # Token 智能截断
            estimated_tokens = self._estimate_tokens(pure_history)  # 估算当前token数
            if estimated_tokens > SESSION_MAX_TOKENS:  # 超过限制则截断
                # 保留预算的 80% 给最近消息，20% 留给摘要
                keep_budget = int(SESSION_MAX_TOKENS * 0.8)  # 80%给最近消息，保证上下文连贯性
                kept, truncated = self._truncate_by_tokens(pure_history, keep_budget)

                if truncated:  # 有被截断的消息才生成摘要
                    # 异步生成摘要
                    summary = await self._summarize_truncated(truncated)  # 将旧消息压缩为摘要

                pure_history = kept  # 替换为截断后的消息
                logger.info("session_token_truncation",
                            session_id=session_id,
                            estimated_tokens=estimated_tokens,
                            max_tokens=SESSION_MAX_TOKENS,
                            kept_count=len(kept),
                            truncated_count=len(truncated))

            # 兜底：消息数仍超限时按计数截断
            if len(pure_history) > SESSION_MAX_MESSAGES:  # 双重保护：token截断后消息数仍可能超限
                overflow = pure_history[:len(pure_history) - SESSION_MAX_MESSAGES]  # 取出超出的部分
                pure_history = pure_history[-SESSION_MAX_MESSAGES:]  # 保留最近的消息
                if not summary and overflow:  # 如果之前没有生成摘要，现在生成
                    summary = await self._summarize_truncated(overflow)

            serialized = self._serialize_messages(pure_history)  # 序列化消息
            if self._redis_available:  # Redis可用时写入Redis
                self._redis.setex(f"session:{session_id}", SESSION_TTL, serialized)  # setex同时设置值和过期时间
                if summary:  # 有摘要时单独存储
                    self._redis.setex(
                        f"session:{session_id}:summary",
                        SESSION_SUMMARY_TTL,  # 摘要TTL更长，因为摘要信息密度高
                        summary,
                    )
            else:  # Redis不可用时降级为内存存储
                self._memory[session_id] = pure_history
                if summary:
                    self._summaries[session_id] = summary
        except Exception as e:  # 宽泛捕获，存储异常不中断业务流程
            logger.error("session_store_append_error", error=str(e), session_id=session_id)

    def clear_session(self, session_id: str):  # 清除会话，支持Redis和内存两种后端
        try:
            if self._redis_available:  # Redis可用时删除Redis中的key
                self._redis.delete(f"session:{session_id}")
                self._redis.delete(f"session:{session_id}:summary")
            else:  # Redis不可用时从内存中删除
                self._memory.pop(session_id, None)  # 使用pop(None)避免KeyError
                self._summaries.pop(session_id, None)
        except Exception as e:
            logger.error("session_store_clear_error", error=str(e), session_id=session_id)

    def set_cache(self, key: str, data: str, ttl: int = 86400):  # 通用缓存接口，供其他模块使用
        try:
            if self._redis_available:  # Redis可用时使用Redis
                self._redis.setex(key, ttl, data)
            else:  # Redis不可用时复用_memory字典，但注意此时没有TTL机制
                self._memory[key] = data
        except Exception as e:
            logger.error("session_store_cache_error", error=str(e), key=key)