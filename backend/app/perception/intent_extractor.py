"""
感知管道 - 意图提取器
使用 LLM 从查询中提取结构化意图，支持 7 种意图类型 + 恶意输入检测
"""
# docstring 显式声明 7+1 种能力，因为下游 Agent 需要根据意图类型做路由分发

import os
import re
from dataclasses import dataclass, field  # dataclass 减少样板代码，field 提供可变默认值的正确写法
from enum import StrEnum  # StrEnum 使得枚举值既是字符串又能保持类型安全，方便 JSON 序列化

from app.core.logging import get_logger

logger = get_logger(__name__)


def _normalize_company_id(company_id: str | int | None) -> int | None:
    if company_id in (None, ""):
        return None


def _looks_like_direct_knowledge_query(text: str) -> bool:
    """Return True for already-specific RAG/knowledge-base probes."""
    normalized = text.strip()
    if not normalized:
        return False
    if re.search(r"\bRAGLIVE-[A-Z0-9-]+\b", normalized):
        return True
    return "知识库" in normalized and any(
        marker in normalized for marker in ("唯一标记", "只根据", "根据知识")
    )
    try:
        return int(company_id)
    except (TypeError, ValueError):
        return None


class IntentType(
    StrEnum
):  # 用 StrEnum 而非 Enum 是为了 intent_type.value 直接返回字符串，无需额外转换
    SEARCH = "search"  # 搜索意图，需要调用检索工具链
    ANALYZE = "analyze"  # 分析意图，需要调用数据分析 Agent
    GENERATE = "generate"  # 生成意图，需要调用内容创作 Agent
    DELEGATE = "delegate"  # 委派意图，需要路由到其他专业 Agent
    MONITOR = "monitor"  # 监控意图，需要启动长期运行的后台任务
    KNOWLEDGE = "knowledge"  # 知识库操作意图，需要读写知识库
    GENERAL = "general"  # 兜底类型，普通对话无需特殊路由，也是 LLM 解析失败时的 safe fallback


@dataclass
class Intent:
    """结构化意图"""

    intent_type: IntentType = IntentType.GENERAL  # 默认 GENERAL，确保即使提取失败也有安全兜底
    confidence: float = 0.5  # 默认 0.5 表示"不确定"，让下游能够区分故意默认值和真实高置信度
    entities: dict = field(
        default_factory=dict
    )  # 用 field 而非 ={} 避免多个实列共享同一个 dict 对象
    sub_intents: list["Intent"] = field(
        default_factory=list
    )  # 前向引用用字符串类型，因为 Intent 类尚未定义完毕
    is_malicious: bool = False  # 默认不视为恶意，假阳性代价远大于假阴性
    raw_response: str = ""  # 保留原始 LLM 响应用于调试和审计追溯

    def to_dict(
        self,
    ) -> dict:  # 序列化为字典用于日志和 API 响应，不暴露 raw_response 避免泄露内部信息
        return {
            "intent_type": self.intent_type.value,  # .value 确保序列化后是纯字符串而非枚举对象
            "confidence": self.confidence,
            "entities": self.entities,
            "sub_intents": [s.to_dict() for s in self.sub_intents],  # 递归序列化子意图
            "is_malicious": self.is_malicious,
        }


INTENT_SYSTEM_PROMPT = """你是一个意图分析助手。请分析用户查询的意图，并返回 JSON 格式的结果。

支持的意图类型：
- search: 搜索/查询信息（如"帮我找一下最近的热门达人"）
- analyze: 分析/评估数据（如"分析上个月的销售趋势"）
- generate: 生成/创作内容（如"写一个品牌推广文案"）
- delegate: 委派任务给其他 Agent（如"让数据分析师出个周报"）
- monitor: 监控/告警（如"监控竞品价格变化"）
- knowledge: 知识库操作（如"把这份文档录入知识库"）
- general: 一般对话/闲聊（如"你好"）

对于每个查询，请返回以下 JSON：
{
  "intent_type": "类型",
  "confidence": 0.0-1.0,
  "entities": {},
  "sub_intents": [],
  "is_malicious": false
}

注意：
- entities 中提取关键实体（如 product_name, date_range, platform, target_agent 等）
- 如果查询包含明显的恶意内容（攻击性、违法请求），设置 is_malicious 为 true
- 只返回 JSON，不要添加任何解释
"""
# prompt 放在模块级而非类内部，因为它是静态配置而非实例状态，也方便非技术人员直接修改调优


class IntentExtractor:
    """使用 LLM 提取结构化意图"""

    def __init__(
        self, model_gateway=None
    ):  # 默认参数为 None 支持延迟初始化，避免在模块加载时就创建 gateaway
        self._model_gateway = model_gateway

    @staticmethod
    def _llm_enabled() -> bool:
        override = os.getenv("PERCEPTION_LLM_ENABLED")
        if override is not None:
            return override.strip().lower() in {"1", "true", "yes", "on"}
        return os.getenv("ENV", "dev").strip().lower() == "prod"

    def _heuristic_extract(self, text: str) -> Intent:
        lowered = text.lower()
        malicious_markers = [
            "<script",
            "javascript:",
            "drop table",
            "delete from",
            "__import__",
            "eval(",
        ]
        if any(marker in lowered for marker in malicious_markers):
            return Intent(
                intent_type=IntentType.GENERAL,
                confidence=0.9,
                is_malicious=True,
                raw_response="heuristic",
            )

        keyword_map = [
            (IntentType.KNOWLEDGE, ["知识库", "录入", "上传文档", "文档入库"]),
            (IntentType.MONITOR, ["监控", "告警", "预警", "盯一下"]),
            (IntentType.DELEGATE, ["委派", "交给", "让", "安排"]),
            (IntentType.GENERATE, ["生成", "写", "创作", "脚本", "文案", "报告", "周报"]),
            (IntentType.ANALYZE, ["分析", "评估", "复盘", "趋势", "roi", "转化率"]),
            (IntentType.SEARCH, ["查", "查询", "搜索", "找", "kol", "达人", "订单", "物流"]),
        ]
        for intent_type, keywords in keyword_map:
            if any(keyword in lowered or keyword in text for keyword in keywords):
                return Intent(
                    intent_type=intent_type,
                    confidence=0.65,
                    raw_response="heuristic",
                )

        return Intent(intent_type=IntentType.GENERAL, confidence=0.5, raw_response="heuristic")

    def _get_llm(
        self, company_id: str | int | None = None
    ):  # 懒加载 gateaway 的 LLM 实例，首次调用时才真正初始化
        if self._model_gateway is None:  # 延迟导入避免循环依赖，model_gateway 可能也依赖 perception
            from app.services.model_gateway import get_global_model_gateway

            self._model_gateway = get_global_model_gateway()
        return self._model_gateway.get_llm(company_id=_normalize_company_id(company_id))

    def extract(self, text: str, company_id: str | int | None = None) -> Intent:
        """
        从查询文本中提取意图

        Args:
            text: 改写后的查询文本

        Returns:
            Intent 结构化意图对象
        """
        if not text or not text.strip():  # 空输入直接返回默认意图，不浪费 LLM 调用
            return Intent(intent_type=IntentType.GENERAL, confidence=0.0)
        if _looks_like_direct_knowledge_query(text):
            logger.info("intent_extraction_fast_path_direct_knowledge_query")
            intent = self._heuristic_extract(text)
            intent.intent_type = IntentType.KNOWLEDGE
            intent.confidence = max(intent.confidence, 0.9)
            intent.raw_response = "heuristic_direct_knowledge_query"
            return intent
        if not self._llm_enabled():
            return self._heuristic_extract(text)

        try:
            llm = self._get_llm(company_id=company_id)
            from langchain_core.messages import HumanMessage, SystemMessage  # noqa: I001  # 延迟导入，不强制项目必须安装 langchain

            messages = [
                SystemMessage(
                    content=INTENT_SYSTEM_PROMPT
                ),  # SystemMessage 让 LLM 以意图分析专家身份思考
                HumanMessage(content=text),
            ]
            response = llm.invoke(messages)
            raw = (
                response.content.strip() if hasattr(response, "content") else str(response).strip()
            )  # 兼容多个 LLM 库的响应格式

            return self._parse_response(raw, text)
        except Exception as e:
            logger.warning(
                "intent_extraction_failed", error=str(e)
            )  # warning 而非 error，因为降级到 GENERAL 是可接受的
            return Intent(intent_type=IntentType.GENERAL, confidence=0.0, raw_response=str(e))

    def _parse_response(self, raw: str, original_text: str) -> Intent:
        """解析 LLM 响应为 Intent 对象"""
        import json  # 延迟导入，仅在需要解析时加载
        import re

        raw = raw.strip()

        json_match = re.search(
            r"\{[\s\S]*\}", raw
        )  # 用 [\s\S] 而非 . 是因为 . 不匹配换行，而 LLM 返回的 JSON 可能跨多行
        if json_match:  # 如果 LLM 在 JSON 前后附加了解释文本，提取出纯 JSON 部分
            raw = json_match.group(0)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            logger.warning(
                "intent_json_parse_failed", raw=raw[:200]
            )  # 只记录前 200 字符避免敏感数据日志泄露
            return Intent(
                intent_type=IntentType.GENERAL,  # 解析失败降级到通用意图，保证管线不中断
                confidence=0.0,
                raw_response=raw,
            )

        intent_type_str = data.get("intent_type", "general")  # 缺失时默认 general
        try:
            intent_type = IntentType(intent_type_str)  # 用枚举构造器验证合法性
        except ValueError:
            intent_type = IntentType.GENERAL  # 非法值降级，防止下游匹配不到 route

        confidence = float(data.get("confidence", 0.5))
        confidence = max(
            0.0, min(1.0, confidence)
        )  # clamp 到 [0,1] 区间，因为 LLM 可能返回超范围浮点数

        entities = data.get("entities", {})
        if not isinstance(entities, dict):  # LLM 可能返回数组或 null，需要类型防御
            entities = {}

        sub_intents = []  # 解析子意图列表，支持复合意图场景
        for sub in data.get("sub_intents", []):
            if isinstance(sub, dict):  # 跳过非法元素，健壮处理 LLM 的异常输出
                sub_type_str = sub.get("intent_type", "general")
                try:
                    sub_type = IntentType(sub_type_str)
                except ValueError:
                    sub_type = IntentType.GENERAL
                sub_intents.append(
                    Intent(
                        intent_type=sub_type,
                        confidence=float(sub.get("confidence", 0.5)),
                        entities=sub.get("entities", {}),
                    )
                )

        is_malicious = bool(
            data.get("is_malicious", False)
        )  # 显式 bool 转换防止 LLM 返回字符串 "false"

        logger.info(  # info 级别便于生产环境审计意图提取质量
            "intent_extracted",
            intent_type=intent_type.value,
            confidence=confidence,
            is_malicious=is_malicious,
            entity_count=len(entities),
        )

        return Intent(
            intent_type=intent_type,
            confidence=confidence,
            entities=entities,
            sub_intents=sub_intents,
            is_malicious=is_malicious,
            raw_response=raw,
        )
