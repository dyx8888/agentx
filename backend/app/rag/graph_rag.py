"""# GraphRAG 模块，知识图谱增强检索，用实体关系推理补全纯向量检索的不足
GraphRAG - 知识图谱增强检索  # GraphRAG = Graph + RAG，在向量检索基础上增加结构化关系推理
使用轻量级 NetworkX 知识图谱实现实体关系推理  # 选择 NetworkX 而非 Neo4j 等图数据库，降低部署复杂度，适合中小规模场景

v2 改进：  # 借鉴 RAG-Anything 的实体关系抽取思路
- retrieve() 从纯关键词匹配升级为 LLM 驱动的实体抽取 + 语义匹配
- 新增 _extract_query_entities() 方法，使用 LLM 从查询中提取实体
- 保留关键词匹配作为快速路径，LLM 抽取作为语义兜底
"""

import json  # 用于序列化实体属性、解析 LLM 返回的 JSON

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger

try:  # NetworkX 是可选依赖，未安装时系统仍可运行但图谱功能降级
    import networkx as nx  # 轻量级图计算库，内存中构建和查询知识图谱

    NETWORKX_AVAILABLE = True  # 标记可用，后续代码通过此变量判断是否走降级路径
except ImportError:  # NetworkX 未安装时的降级策略
    NETWORKX_AVAILABLE = False  # 标记不可用
    logger.warning(
        "networkx_not_installed_graphrag_disabled"
    )  # 一次性告警，启动时就知道图谱功能不可用

# 语义匹配阈值：实体名称与查询词的相似度低于此值时忽略
SEMANTIC_MATCH_THRESHOLD = 0.5


class KnowledgeGraph:  # 电商领域知识图谱，使用 NetworkX 有向多重图存储实体和关系
    """电商领域知识图谱"""  # 轻量级实现，适合中小规模电商场景

    def __init__(self):  # 初始化图谱
        self.graph = (
            nx.MultiDiGraph() if NETWORKX_AVAILABLE else None
        )  # MultiDiGraph 支持多重边，同一对实体可有多种关系
        self._entity_index: dict[str, str] = {}  # 名称 → 实体 ID 的倒排索引，O(1) 查找实体

    def add_entity(
        self,
        entity_id: str,
        entity_type: str,  # 添加实体节点
        name: str,
        properties: dict = None,
    ):  # properties 可选，存储额外属性
        """添加实体节点"""  # 实体是图谱的基本单元
        if not self.graph:  # NetworkX 不可用时静默跳过
            return
        self.graph.add_node(  # 添加到 NetworkX 图
            entity_id,  # 唯一标识符
            type=entity_type,  # 实体类型：platform/content_type/metric/agent_role
            name=name,  # 实体名称，用于展示
            properties=json.dumps(
                properties or {}
            ),  # JSON 序列化存储，NetworkX 节点属性需要可序列化
        )
        self._entity_index[name.lower()] = entity_id  # 小写化索引，实现大小写不敏感的实体查找

    def add_relation(
        self,
        source_id: str,
        target_id: str,  # 添加关系边
        relation_type: str,
        weight: float = 1.0,
    ):  # weight 用于排序，默认 1.0
        """添加关系边"""  # 关系连接两个实体
        if not self.graph:  # 降级跳过
            return
        self.graph.add_edge(  # 添加有向边
            source_id,
            target_id,  # 从源实体到目标实体
            type=relation_type,  # 关系类型：supports/creates/analyzes/optimizes 等
            weight=weight,  # 权重，用于排序时优先展示重要关系
        )

    def find_entity(self, name: str) -> str | None:  # 按名称查找实体 ID
        return self._entity_index.get(name.lower())  # 小写化匹配，返回 None 表示未找到

    def get_neighbors(
        self,
        entity_id: str,
        depth: int = 1,  # BFS 获取邻居，depth 控制探索深度
        relation_types: list[str] = None,
    ) -> list[dict]:  # relation_types 可选过滤关系类型
        """获取实体邻居（关系推理）"""  # BFS 遍历，逐层探索
        if not self.graph:  # 降级检查
            return []

        if entity_id not in self.graph:  # 实体不存在
            return []

        results = []  # 收集所有邻居关系
        visited = {entity_id}  # BFS 已访问集合，避免重复遍历
        frontier = {entity_id}  # BFS 当前层节点集合

        for _ in range(depth):  # 按深度逐层探索
            next_frontier = set()  # 下一层节点集合
            for node in frontier:  # 遍历当前层每个节点
                for neighbor in self.graph.neighbors(node):  # 获取节点的所有出边邻居
                    if neighbor in visited:  # 已访问过则跳过，避免环路
                        continue
                    visited.add(neighbor)  # 标记已访问
                    next_frontier.add(neighbor)  # 加入下一层

                    edges = self.graph.get_edge_data(
                        node, neighbor
                    )  # 获取所有边数据（MultiDiGraph 可能有多条边）
                    for _key, edge_data in edges.items():  # 遍历每条边
                        if (
                            relation_types and edge_data.get("type") not in relation_types
                        ):  # 按类型过滤
                            continue
                        results.append(
                            {  # 记录邻居信息
                                "entity_id": neighbor,  # 邻居实体 ID
                                "entity_name": self.graph.nodes[neighbor].get(
                                    "name", ""
                                ),  # 邻居名称
                                "entity_type": self.graph.nodes[neighbor].get(
                                    "type", ""
                                ),  # 邻居类型
                                "relation": edge_data.get("type", ""),  # 关系类型
                                "weight": edge_data.get("weight", 1.0),  # 关系权重
                                "depth": depth,  # 当前深度（注意：这里用的是外层 depth，实际应为当前层数）
                            }
                        )

            frontier = next_frontier  # 进入下一层

        return results  # 返回所有邻居关系

    def get_related_context(
        self, entity_name: str, depth: int = 2
    ) -> str:  # 获取实体相关的文本上下文
        """获取实体相关的上下文"""  # 转为 LLM 可读的文本格式
        entity_id = self.find_entity(entity_name)  # 先查找实体
        if not entity_id:  # 实体不存在
            return ""

        neighbors = self.get_neighbors(entity_id, depth=depth)  # 获取邻居关系
        if not neighbors:  # 无邻居
            return ""

        parts = [f"\n【知识图谱 - {entity_name} 相关关系】"]  # 用中文方括号标记，格式统一
        added = set()  # 去重集合，同一实体可能通过不同路径重复出现
        for n in sorted(neighbors, key=lambda x: x["weight"], reverse=True):  # 按权重降序排列
            key = n["entity_id"]  # 去重键
            if key in added:  # 已出现过
                continue
            added.add(key)  # 标记为已添加
            parts.append(  # 格式：关系类型 → 实体名 (类型, 深度)
                f"  {n['relation']} → {n['entity_name']} ({n['entity_type']}, 深度={n['depth']})"
            )

        return "\n".join(parts)  # 拼接为文本


class GraphRAGRetriever:  # GraphRAG 检索引擎，对外的统一入口
    """GraphRAG 检索引擎"""  # 封装知识图谱 + LLM 实体提取 + 动态扩展

    def __init__(self, kg: KnowledgeGraph = None):  # 允许注入自定义图谱
        self.kg = kg or KnowledgeGraph()  # 未注入时使用默认图谱
        self._init_ecommerce_kg()  # 初始化电商领域基础知识图谱

    def _init_ecommerce_kg(self):  # 初始化电商领域基础知识图谱
        """初始化电商领域基础知识图谱"""  # 硬编码电商领域核心实体和关系，作为推理的基础
        entities = [  # 实体定义：(ID, 类型, 名称, 属性)
            ("platform_douyin", "platform", "抖音", {"category": "short_video"}),  # 平台类实体
            ("platform_xiaohongshu", "platform", "小红书", {"category": "social"}),
            ("platform_taobao", "platform", "淘宝", {"category": "ecommerce"}),
            ("platform_pdd", "platform", "拼多多", {"category": "ecommerce"}),
            ("content_short_video", "content_type", "短视频", {}),  # 内容类型实体
            ("content_live", "content_type", "直播", {}),
            ("content_article", "content_type", "文章", {}),
            ("metric_gmv", "metric", "GMV", {"formula": "销售额总计"}),  # 指标类实体
            ("metric_roi", "metric", "ROI", {"formula": "收益/投入"}),
            ("metric_ctr", "metric", "点击率", {"formula": "点击数/曝光数"}),
            ("metric_cvr", "metric", "转化率", {"formula": "成交数/点击数"}),
            ("metric_cpa", "metric", "单次获客成本", {"formula": "总花费/获客数"}),
            ("role_brand_bd", "agent_role", "品牌商务", {}),  # Agent 角色实体
            ("role_content_op", "agent_role", "内容运营", {}),
            ("role_data_analyst", "agent_role", "数据分析", {}),
            ("role_customer_service", "agent_role", "客服专员", {}),
            ("role_warehouse", "agent_role", "仓储物流", {}),
            ("role_designer", "agent_role", "视觉设计", {}),
            ("role_product_selector", "agent_role", "供应链选品师", {}),
            ("role_ad_delivery", "agent_role", "智能投流专员", {}),
        ]

        for eid, etype, name, props in entities:  # 批量添加实体
            self.kg.add_entity(eid, etype, name, props)

        relations = [  # 关系定义：(源实体ID, 目标实体ID, 关系类型)
            ("platform_douyin", "content_short_video", "supports"),  # 平台支持的内容类型
            ("platform_douyin", "content_live", "supports"),
            ("platform_xiaohongshu", "content_article", "supports"),
            ("platform_xiaohongshu", "content_short_video", "supports"),
            ("platform_taobao", "content_live", "supports"),
            ("role_brand_bd", "platform_douyin", "works_on"),  # Agent 角色与平台的关系
            ("role_content_op", "content_short_video", "creates"),  # Agent 角色创建的内容类型
            ("role_content_op", "content_live", "creates"),
            ("role_data_analyst", "metric_gmv", "analyzes"),  # 数据分析师关注的指标
            ("role_data_analyst", "metric_roi", "analyzes"),
            ("role_data_analyst", "metric_ctr", "analyzes"),
            ("role_data_analyst", "metric_cvr", "analyzes"),
            ("role_ad_delivery", "metric_roi", "optimizes"),  # 投流专员优化的指标
            ("role_ad_delivery", "metric_cpa", "controls"),
            ("role_product_selector", "platform_douyin", "researches"),  # 选品师研究的平台
            ("role_product_selector", "platform_taobao", "researches"),
        ]

        for src, tgt, rel in relations:  # 批量添加关系
            self.kg.add_relation(src, tgt, rel)

    def retrieve(self, query: str, depth: int = 2, use_llm: bool = True) -> str:  # 核心检索方法
        """根据查询提取知识图谱关系。

        v2 改进：支持 LLM 驱动的实体抽取 + 语义匹配，也保留关键词匹配作为快速路径。

        Args:
            query: 用户查询
            depth: BFS 探索深度
            use_llm: 是否使用 LLM 进行实体抽取（默认 True），False 时回退到关键词匹配

        Returns:
            知识图谱关系上下文字符串
        """
        results = []  # 收集匹配结果

        # 策略 1: 关键词快速匹配（始终执行，作为兜底）
        query_lower = query.lower()
        entity_names = self._get_all_entity_names()

        for name in entity_names:
            if name.lower() in query_lower:
                ctx = self.kg.get_related_context(name, depth=depth)
                if ctx:
                    results.append(ctx)

        # 策略 2: LLM 驱动的实体抽取 + 语义匹配（v2 新增）
        if use_llm and not results:  # 关键词匹配无结果时才使用 LLM，避免冗余调用
            extracted_entities = self._extract_query_entities(query)
            if extracted_entities:
                for entity_name in extracted_entities:
                    # 使用语义匹配找到最相似的知识图谱实体
                    matched = self._find_best_match_entity(entity_name)
                    if matched:
                        ctx = self.kg.get_related_context(matched, depth=depth)
                        if ctx and ctx not in results:
                            results.append(ctx)

        if len(results) > 3:  # 限制最多 3 个实体结果，避免 Prompt 过长
            results = results[:3]

        return "\n".join(results)  # 拼接所有结果

    def _get_all_entity_names(self) -> list[str]:  # 获取图谱中所有实体名称
        """获取知识图谱中所有实体的名称列表"""
        if not self.kg.graph:
            return []
        names = []
        for _node_id, data in self.kg.graph.nodes(data=True):
            name = data.get("name", "")
            if name:
                names.append(name)
        return names

    def _find_best_match_entity(self, query_entity: str) -> str | None:  # 语义匹配最佳实体
        """使用嵌入相似度找到与查询实体最匹配的知识图谱实体。

        Args:
            query_entity: LLM 从查询中提取的实体名

        Returns:
            匹配到的实体名称，无匹配时返回 None
        """
        entity_names = self._get_all_entity_names()
        if not entity_names:
            return None

        # 优先精确匹配
        query_lower = query_entity.lower()
        for name in entity_names:
            if name.lower() == query_lower:
                return name

        # 子串匹配
        for name in entity_names:
            if name.lower() in query_lower or query_lower in name.lower():
                return name

        # 嵌入相似度匹配（兜底）
        try:
            from app.rag.embedding_service import get_embedding_service

            emb_service = get_embedding_service()
            query_vec = emb_service.encode_single(query_entity)
            entity_vecs = emb_service.encode(entity_names)

            # 计算余弦相似度（向量已归一化，内积即为余弦相似度）
            similarities = query_vec @ entity_vecs.T
            best_idx = int(similarities.argmax())
            best_score = float(similarities[best_idx])

            if best_score >= SEMANTIC_MATCH_THRESHOLD:
                logger.info(
                    "graphrag_semantic_match",
                    query_entity=query_entity,
                    matched=entity_names[best_idx],
                    score=round(best_score, 3),
                )
                return entity_names[best_idx]
        except Exception as e:
            logger.warning("graphrag_semantic_match_failed", error=str(e))

        return None

    def _extract_query_entities(self, query: str) -> list[str]:  # 使用 LLM 从查询中提取实体名
        """使用 LLM 从查询中提取电商领域实体名称。
        借鉴 RAG-Anything 的实体关系抽取思路，但轻量化：只抽取实体名，不抽取关系。

        Args:
            query: 用户查询

        Returns:
            提取到的实体名称列表
        """
        try:
            from app.services.model_gateway import get_global_model_gateway

            model_gateway = get_global_model_gateway()
            llm = model_gateway.get_llm()

            prompt = (
                "从以下用户查询中提取电商领域相关的实体名称。\n"
                "只返回实体名称，用逗号分隔。不要返回其他内容。\n\n"
                "## 实体类型（仅供参考）\n"
                "平台、内容类型、指标、角色、产品、品牌\n\n"
                "## 查询\n"
                f"{query}\n\n"
                "## 实体名称（逗号分隔）\n"
            )
            response = llm.invoke(prompt)
            content = response.content if hasattr(response, "content") else str(response)
            content = content.strip().strip('"').strip("'")

            # 按逗号分割并清理
            entities = [e.strip() for e in content.split(",") if e.strip()]
            if entities:
                logger.info("graphrag_llm_entities_extracted", query=query[:50], entities=entities)
            return entities
        except Exception as e:
            logger.warning("graphrag_entity_extraction_failed", error=str(e))
            return []

    def extract_entities_from_text(self, text: str) -> dict:  # 使用 LLM 从文本中提取实体和关系
        """使用 LLM 从文本中提取实体和关系"""  # 动态扩展知识图谱的关键方法
        try:  # LLM 调用可能失败，需要降级
            from app.services.model_gateway import get_global_model_gateway  # 延迟导入

            model_gateway = get_global_model_gateway()  # 获取模型网关
            llm = model_gateway.get_llm()  # 获取 LLM 实例

            prompt = (  # 构造提取 Prompt，明确要求 JSON 格式输出
                "从以下文本中提取电商领域相关的实体和关系，以 JSON 格式返回。\n\n"
                "## 实体类型\n"  # 定义实体类型约束
                "platform, content_type, metric, agent_role, product, company\n\n"
                "## 关系类型\n"  # 定义关系类型约束
                "supports, creates, analyzes, optimizes, controls, researches, "
                "works_on, competes_with, belongs_to\n\n"
                "## 文本\n"
                f"{text[:2000]}\n\n"  # 截断到 2000 字符，控制 token 消耗
                "## 返回格式\n"
                "只返回 JSON，不要其他内容：\n"  # 强调只返回 JSON，避免 LLM 输出额外文本
                '{{"entities": [{{"name": "实体名", "type": "实体类型"}}], '
                '"relations": [{{"source": "源实体名", "target": "目标实体名", "type": "关系类型"}}]}}'
            )
            response = llm.invoke(prompt)  # 调用 LLM
            content = (
                response.content if hasattr(response, "content") else str(response)
            )  # 兼容不同 LLM 接口

            import re  # 延迟导入

            json_match = re.search(
                r"\{[\s\S]*\}", content
            )  # 正则提取 JSON 块，兼容 LLM 可能在 JSON 外输出额外文本
            if json_match:  # 提取到 JSON
                data = json.loads(json_match.group())  # 解析 JSON
                return data  # 返回提取结果
        except Exception as e:  # LLM 调用失败时的降级
            logger.warning("entity_extraction_failed", error=str(e))  # 记录警告
        return {"entities": [], "relations": []}  # 降级返回空结果

    def add_dynamic_entities(self, text: str):  # 从文本中动态提取并添加实体到图谱
        """从文本中提取并动态添加实体到知识图谱"""  # 实现知识图谱的自动扩展
        extracted = self.extract_entities_from_text(text)  # LLM 提取实体和关系
        if not extracted:  # 提取失败
            return

        added_count = 0  # 成功添加的实体计数
        for entity in extracted.get("entities", []):  # 遍历提取的实体
            name = entity.get("name", "")  # 实体名
            etype = entity.get("type", "")  # 实体类型
            if not name or not etype:  # 必要字段缺失则跳过
                continue
            eid = f"dynamic_{etype}_{name.replace(' ', '_').lower()}"  # 生成动态实体 ID：dynamic_类型_名称
            existing = self.kg.find_entity(name)  # 检查是否已存在
            if existing:  # 已存在则用已有 ID 更新
                self.kg.add_entity(existing, etype, name)
            else:  # 不存在则新增
                self.kg.add_entity(eid, etype, name)
                added_count += 1

        for relation in extracted.get("relations", []):  # 遍历提取的关系
            src_name = relation.get("source", "")  # 源实体名
            tgt_name = relation.get("target", "")  # 目标实体名
            rel_type = relation.get("type", "")  # 关系类型
            if not src_name or not tgt_name or not rel_type:  # 必要字段缺失则跳过
                continue
            src_id = self.kg.find_entity(src_name)  # 查找源实体 ID
            tgt_id = self.kg.find_entity(tgt_name)  # 查找目标实体 ID
            if src_id and tgt_id:  # 两个实体都存在时才添加关系
                self.kg.add_relation(src_id, tgt_id, rel_type)

        if added_count > 0:  # 有新实体添加时才记录日志
            logger.info("dynamic_entities_added", count=added_count)


_graph_rag: GraphRAGRetriever | None = None  # 模块级单例，全局共享知识图谱


def get_graph_rag() -> GraphRAGRetriever:  # 工厂函数，保证全局单例
    global _graph_rag  # 声明修改全局变量
    if _graph_rag is None:  # 首次调用时创建
        _graph_rag = GraphRAGRetriever()  # 创建并初始化电商领域知识图谱
    return _graph_rag  # 返回单例
