"""
Skill 注册表与匹配引擎
启动时只加载元数据，命中后按需加载完整 SKILL.md
v2: 支持语义匹配、动态加载、知识库关联
"""
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import yaml

from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class SkillMeta:
    """Skill 元数据（启动时加载，极小）"""
    name: str
    agent_name: str
    title: str
    description: str
    trigger_keywords: list[str]
    skill_path: str
    enabled: bool = True
    # 6C.1: 扩展字段
    prompt_template: str = ""  # 自定义 System Prompt 模板
    knowledge_base_ids: list[str] = field(default_factory=list)  # 关联的 Milvus collection 名称
    # 7.2: embedding 缓存
    embedding: Optional[list[float]] = None  # 预计算的 embedding 向量


# 语义匹配阈值
SIMILARITY_THRESHOLD = 0.6
# 语义匹配 top-k
MATCH_TOP_K = 3


class SkillRegistry:
    """Skill 注册表单例"""
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._skills: dict[str, SkillMeta] = {}
            cls._instance._loaded_contents: dict[str, str] = {}
            cls._instance._embedding_cache: dict[str, list[float]] = {}
            cls._instance._watcher_thread: Optional[threading.Thread] = None
            cls._instance._watcher_stop = threading.Event()
            cls._instance._config_path: Optional[str] = None
        return cls._instance

    def register(self, meta: SkillMeta):
        self._skills[meta.name] = meta

    def load_from_config(self, config_path: str = None):
        """从 skills_config.yaml 加载所有 Skill 元数据"""
        if config_path is None:
            config_path = os.path.join(
                os.path.dirname(__file__), '..', '..', 'config', 'skills_config.yaml'
            )
        self._config_path = config_path
        with open(config_path, encoding='utf-8') as f:
            config = yaml.safe_load(f)

        for skill_cfg in config.get('skills', []):
            meta = SkillMeta(
                name=skill_cfg['name'],
                agent_name=skill_cfg['agent_name'],
                title=skill_cfg['title'],
                description=skill_cfg['description'],
                trigger_keywords=skill_cfg.get('trigger_keywords', []),
                skill_path=skill_cfg['skill_path'],
                enabled=skill_cfg.get('enabled', True),
                prompt_template=skill_cfg.get('prompt_template', ''),
                knowledge_base_ids=skill_cfg.get('knowledge_base_ids', []),
            )
            self.register(meta)

        # 预计算 embedding 向量
        self._precompute_embeddings()

        logger.info("skill_registry_loaded", skill_count=len(self._skills))

    # ── 语义匹配 (Phase 7) ──────────────────────────────────

    def _precompute_embeddings(self):
        """为每个 SKILL 预计算 embedding 向量，存储在 _skill_embeddings 缓存中"""
        try:
            from app.services.model_gateway import ModelGateway
            model_gateway = ModelGateway()
            embeddings_model = model_gateway.get_embeddings()

            for skill_name, skill in self._skills.items():
                if not skill.enabled:
                    continue
                # 将 title + description + keywords 组合为文本
                text = f"{skill.title}. {skill.description}. {' '.join(skill.trigger_keywords)}"
                try:
                    embedding = embeddings_model.embed_query(text)
                    skill.embedding = embedding
                    self._embedding_cache[skill_name] = embedding
                    logger.debug("skill_embedding_computed", skill=skill_name)
                except Exception as e:
                    logger.warning("skill_embedding_failed", skill=skill_name, error=str(e))
        except Exception as e:
            logger.warning("skill_embedding_precompute_unavailable", error=str(e),
                           suggestion="Embedding 模型不可用，将使用关键词匹配降级")

    def match_skill(self, user_message: str, agent_name: str) -> Optional[SkillMeta]:
        """
        语义匹配 + 关键词匹配混合策略。
        优先使用 embedding 语义匹配，降级为关键词匹配。

        Returns:
            最佳匹配的 SkillMeta，无匹配返回 None
        """
        # 过滤出目标 agent 的已启用 skills
        candidates = [
            s for s in self._skills.values()
            if s.agent_name == agent_name and s.enabled
        ]
        if not candidates:
            return None

        # 尝试语义匹配
        if self._embedding_cache:
            try:
                return self._semantic_match(user_message, candidates)
            except Exception as e:
                logger.warning("semantic_match_failed", error=str(e),
                               suggestion="降级为关键词匹配")

        # 降级：关键词匹配
        return self._keyword_match(user_message, candidates)

    def _semantic_match(self, user_message: str, candidates: list[SkillMeta]) -> Optional[SkillMeta]:
        """使用 embedding 语义匹配"""
        from app.services.model_gateway import ModelGateway
        model_gateway = ModelGateway()
        embeddings_model = model_gateway.get_embeddings()

        # 用户查询计算 embedding
        query_embedding = embeddings_model.embed_query(user_message)

        # 计算余弦相似度
        scores = []
        for skill in candidates:
            if skill.embedding:
                similarity = self._cosine_similarity(query_embedding, skill.embedding)
                scores.append((skill, similarity))
            else:
                scores.append((skill, 0.0))

        # 按相似度降序排序
        scores.sort(key=lambda x: x[1], reverse=True)

        # 取 top-3，检查阈值
        top_candidates = scores[:MATCH_TOP_K]
        best_skill, best_score = top_candidates[0]

        if best_score >= SIMILARITY_THRESHOLD:
            logger.info("skill_semantic_match",
                        skill=best_skill.name,
                        score=round(best_score, 3),
                        top3=[(s.name, round(sc, 3)) for s, sc in top_candidates])
            return best_skill

        logger.debug("skill_no_match",
                     best_score=round(best_score, 3),
                     threshold=SIMILARITY_THRESHOLD)
        return None

    def _keyword_match(self, user_message: str, candidates: list[SkillMeta]) -> Optional[SkillMeta]:
        """关键词匹配（降级方案）"""
        best_match = None
        best_score = 0

        for skill in candidates:
            score = 0
            msg_lower = user_message.lower()
            for kw in skill.trigger_keywords:
                if kw.lower() in msg_lower:
                    score += 1

            for word in skill.title.split():
                if word.lower() in msg_lower:
                    score += 0.5

            if score > best_score:
                best_score = score
                best_match = skill

        return best_match if best_score > 0 else None

    @staticmethod
    def _cosine_similarity(a: list[float], b: list[float]) -> float:
        """计算余弦相似度"""
        import math
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(x * x for x in b))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot / (norm_a * norm_b)

    # ── 动态加载 (Phase 6C.2) ────────────────────────────────

    def start_watcher(self, interval_seconds: int = 30):
        """
        启动文件监听线程，定期检查 skills_config.yaml 变化。
        支持热加载新技能，无需重启服务。

        Args:
            interval_seconds: 检查间隔（秒）
        """
        if self._watcher_thread and self._watcher_thread.is_alive():
            return

        self._watcher_stop.clear()
        self._watcher_thread = threading.Thread(
            target=self._watcher_loop,
            args=(interval_seconds,),
            daemon=True,
            name="skill-watcher",
        )
        self._watcher_thread.start()
        logger.info("skill_watcher_started", interval=interval_seconds)

    def stop_watcher(self):
        """停止文件监听"""
        self._watcher_stop.set()
        if self._watcher_thread:
            self._watcher_thread.join(timeout=5)
        logger.info("skill_watcher_stopped")

    def _watcher_loop(self, interval_seconds: int):
        """文件监听循环"""
        last_mtime = 0
        if self._config_path:
            try:
                last_mtime = os.path.getmtime(self._config_path)
            except OSError:
                pass

        while not self._watcher_stop.is_set():
            self._watcher_stop.wait(interval_seconds)
            if self._watcher_stop.is_set():
                break

            if not self._config_path:
                continue

            try:
                current_mtime = os.path.getmtime(self._config_path)
                if current_mtime > last_mtime:
                    last_mtime = current_mtime
                    logger.info("skill_config_changed", path=self._config_path)
                    self._reload()
            except OSError:
                continue

    def _reload(self):
        """热加载：重新读取配置，保留已加载的 content 缓存"""
        old_contents = dict(self._loaded_contents)
        self._skills.clear()
        self._embedding_cache.clear()
        self.load_from_config(self._config_path)
        self._loaded_contents = old_contents
        logger.info("skill_reload_complete", skill_count=len(self._skills))

    def load_skill_content(self, skill_name: str) -> str:
        """按需加载完整 SKILL.md 内容"""
        if skill_name in self._loaded_contents:
            return self._loaded_contents[skill_name]

        skill = self._skills.get(skill_name)
        if not skill:
            return ""

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        full_path = os.path.join(base_dir, skill.skill_path)

        try:
            with open(full_path, encoding='utf-8') as f:
                content = f.read()
        except FileNotFoundError:
            logger.warning("skill_file_not_found", path=full_path)
            content = ""

        self._loaded_contents[skill_name] = content
        return content

    def get_skill_prompt(self, skill_name: str) -> str:
        """获取格式化的 Skill Prompt（附在 System Prompt 后面）"""
        skill = self._skills.get(skill_name)
        if not skill:
            return ""

        content = self.load_skill_content(skill_name)
        if not content:
            return ""

        # 使用 prompt_template 或默认模板
        if skill.prompt_template:
            template = skill.prompt_template
            # 替换变量
            template = template.replace("{title}", skill.title)
            template = template.replace("{description}", skill.description)
            template = template.replace("{content}", content)
            return f"\n\n{template}"

        return f"\n\n## 当前任务指南（Skill）\n{content}\n\n请严格按照以上流程执行。"

    def get_knowledge_base_ids(self, skill_name: str) -> list[str]:
        """获取 Skill 关联的知识库 ID"""
        skill = self._skills.get(skill_name)
        if not skill:
            return []
        return skill.knowledge_base_ids


skill_registry = SkillRegistry()