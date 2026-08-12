"""
Prompt 版本管理器
提供 Prompt 元数据注册、版本查询、占位符填充功能

文档依据: 4.docx - AI应用系统设计
  - Prompt 5对象版本模型:
    prompt_template: 模板基本信息
    prompt_version: 具体内容+变量定义+模型参数
    prompt_release: 版本发布到环境/租户/流量
    prompt_run: 每次调用绑定版本+变量摘要
    prompt_eval_result: 版本在评测集上的结果
  - 灰度发布: 按租户/用户比例/场景开关选择 Prompt 版本
  - 快速回滚: 线上效果变差时切回稳定版本
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

PROMPT_VERSION = "2.0.0"
PROMPT_UPDATED = "2026-06-20"
PROMPT_CHANGELOG = """
v2.0.0 (2026-06-20): 升级为5对象版本模型，支持灰度发布和快速回滚
v1.0.0 (2026-05-29): 初始版本，PromptMeta + PromptRegistry + PromptLoader
"""


class PromptEnvironment(StrEnum):
    """发布环境"""

    DEV = "dev"
    STAGING = "staging"
    PRODUCTION = "production"


class PromptStatus(StrEnum):
    """Prompt状态"""

    DRAFT = "draft"
    REVIEW = "review"
    PUBLISHED = "published"
    ARCHIVED = "archived"
    ROLLED_BACK = "rolled_back"


class ReleaseStrategy(StrEnum):
    """发布策略"""

    ALL = "all"  # 全量发布
    CANARY = "canary"  # 灰度发布(按比例)
    BY_TENANT = "by_tenant"  # 按租户发布
    BY_SCENE = "by_scene"  # 按场景发布


# ============ 5对象版本模型 ============
# 文档依据: 4.docx - Prompt 5对象版本模型


@dataclass
class PromptTemplate:
    """prompt_template: 模板基本信息

    文档依据: 4.docx - prompt_template 核心表
    """

    template_id: str  # 模板唯一ID
    name: str  # 模板名称
    scene: str  # 适用场景
    type: str  # 类型: system/user/assistant
    status: PromptStatus = PromptStatus.DRAFT
    description: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PromptVersion:
    """prompt_version: 具体内容+变量定义+模型参数

    文档依据: 4.docx - prompt_version 核心表
    """

    version_id: str  # 版本唯一ID
    template_id: str  # 关联模板ID
    version_number: str  # 版本号 (如: 1.2.0)
    content: str  # Prompt内容(含变量占位符)
    variables_schema: dict = field(default_factory=dict)  # 变量定义JSON Schema
    model_params: dict = field(default_factory=dict)  # 模型参数(temperature, max_tokens等)
    created_by: str = ""  # 创建人
    change_description: str = ""  # 变更说明
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PromptRelease:
    """prompt_release: 版本发布到环境/租户/流量

    文档依据: 4.docx - prompt_release 核心表
    支持灰度发布: 按租户/用户比例/场景开关选择 Prompt 版本
    """

    release_id: str  # 发布唯一ID
    version_id: str  # 关联版本ID
    template_id: str  # 关联模板ID
    environment: PromptEnvironment = PromptEnvironment.DEV
    strategy: ReleaseStrategy = ReleaseStrategy.ALL
    traffic_ratio: float = 1.0  # 流量比例(0.0~1.0), 灰度发布时使用
    tenant_ids: list[str] = field(default_factory=list)  # 按租户发布时的租户列表
    scene_codes: list[str] = field(default_factory=list)  # 按场景发布时的场景列表
    is_active: bool = True
    released_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    released_by: str = ""


@dataclass
class PromptRun:
    """prompt_run: 每次调用绑定版本+变量摘要

    文档依据: 4.docx - prompt_run 核心表
    注意: 仅存变量摘要、Hash、Token和关联ID，不含完整用户输入(安全考量)
    """

    run_id: str  # 调用唯一ID
    template_id: str  # 关联模板ID
    version_id: str  # 关联版本ID
    release_id: str = ""  # 关联发布ID
    variables_hash: str = ""  # 变量摘要的MD5 Hash
    input_tokens: int = 0  # 输入Token数
    output_tokens: int = 0  # 输出Token数
    model_name: str = ""  # 使用的模型名称
    latency_ms: float = 0.0  # 调用延迟
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PromptEvalResult:
    """prompt_eval_result: 版本在评测集上的结果

    文档依据: 4.docx - prompt_eval_result 核心表
    """

    eval_id: str  # 评测结果唯一ID
    version_id: str  # 关联版本ID
    eval_dataset: str  # 评测数据集名称
    metrics: dict = field(default_factory=dict)  # 评测指标(Context Recall, Faithfulness等)
    total_cases: int = 0  # 总用例数
    passed_cases: int = 0  # 通过用例数
    pass_rate: float = 0.0  # 通过率
    avg_latency_ms: float = 0.0  # 平均延迟
    avg_cost_usd: float = 0.0  # 平均成本
    created_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())


@dataclass
class PromptMeta:
    module_name: str
    version: str
    updated: str
    changelog: str


class PromptRegistry:
    """Prompt注册中心 - 支持5对象版本模型查询"""

    _prompts: dict[str, PromptMeta] = field(default_factory=dict)

    def __init__(self):
        self._prompts = {}
        # 5对象版本模型存储
        self._templates: dict[str, PromptTemplate] = {}
        self._versions: dict[str, list[PromptVersion]] = {}  # template_id → versions
        self._releases: dict[str, list[PromptRelease]] = {}  # template_id → releases
        self._runs: dict[str, list[PromptRun]] = {}  # template_id → recent runs
        self._eval_results: dict[str, list[PromptEvalResult]] = {}  # version_id → results

    def register(self, module_name: str, version: str, updated: str, changelog: str) -> None:
        self._prompts[module_name] = PromptMeta(
            module_name=module_name,
            version=version,
            updated=updated,
            changelog=changelog.strip(),
        )

    def get(self, module_name: str) -> PromptMeta | None:
        return self._prompts.get(module_name)

    def list_all(self) -> list[PromptMeta]:
        return list(self._prompts.values())

    def get_version_summary(self) -> dict[str, Any]:
        items = []
        for meta in self._prompts.values():
            items.append(
                {
                    "module": meta.module_name,
                    "version": meta.version,
                    "updated": meta.updated,
                }
            )
        return {"prompts": sorted(items, key=lambda x: x["module"])}

    # ============ 5对象版本模型操作 ============
    # 文档依据: 4.docx

    def register_template(self, template: PromptTemplate) -> str:
        """注册Prompt模板"""
        self._templates[template.template_id] = template
        self._versions.setdefault(template.template_id, [])
        self._releases.setdefault(template.template_id, [])
        return template.template_id

    def add_version(self, version: PromptVersion) -> str:
        """添加Prompt版本"""
        if version.template_id not in self._templates:
            raise ValueError(f"Template {version.template_id} not found")
        self._versions[version.template_id].append(version)
        return version.version_id

    def get_latest_version(self, template_id: str) -> PromptVersion | None:
        """获取最新版本"""
        versions = self._versions.get(template_id, [])
        if not versions:
            return None
        return versions[-1]

    def get_version(self, template_id: str, version_number: str) -> PromptVersion | None:
        """获取指定版本"""
        for v in self._versions.get(template_id, []):
            if v.version_number == version_number:
                return v
        return None

    def create_release(self, release: PromptRelease) -> str:
        """创建发布 - 支持灰度发布策略"""
        if release.template_id not in self._templates:
            raise ValueError(f"Template {release.template_id} not found")
        self._releases[release.template_id].append(release)
        return release.release_id

    def get_active_release(
        self, template_id: str, tenant_id: str = "", scene_code: str = ""
    ) -> PromptRelease | None:
        """获取当前生效的发布 - 支持灰度路由

        文档依据: 4.docx - 灰度发布: 按租户/场景选择版本
        """
        releases = self._releases.get(template_id, [])
        active = [r for r in releases if r.is_active]

        # 优先匹配灰度策略
        for r in active:
            if r.strategy == ReleaseStrategy.BY_TENANT and tenant_id in r.tenant_ids:
                return r
            if r.strategy == ReleaseStrategy.BY_SCENE and scene_code in r.scene_codes:
                return r
            if r.strategy == ReleaseStrategy.CANARY and r.traffic_ratio < 1.0:
                return r

        # 回退到全量发布
        for r in active:
            if r.strategy == ReleaseStrategy.ALL:
                return r

        # 返回最新的活跃发布
        return active[-1] if active else None

    def rollback(self, template_id: str, target_version_id: str) -> PromptRelease | None:
        """快速回滚到指定版本

        文档依据: 4.docx - 快速回滚: 线上效果变差时切回稳定版本
        """
        # 停用当前所有活跃发布
        for r in self._releases.get(template_id, []):
            r.is_active = False

        # 创建回滚发布
        rollback_release = PromptRelease(
            release_id=f"rollback_{template_id}_{datetime.utcnow().timestamp()}",
            version_id=target_version_id,
            template_id=template_id,
            environment=PromptEnvironment.PRODUCTION,
            strategy=ReleaseStrategy.ALL,
            traffic_ratio=1.0,
            is_active=True,
            released_by="rollback",
        )
        self._releases[template_id].append(rollback_release)
        return rollback_release

    def record_run(self, run: PromptRun) -> str:
        """记录Prompt调用"""
        self._runs.setdefault(run.template_id, [])
        self._runs[run.template_id].append(run)
        # 保留最近1000条
        if len(self._runs[run.template_id]) > 1000:
            self._runs[run.template_id] = self._runs[run.template_id][-1000:]
        return run.run_id

    def record_eval_result(self, result: PromptEvalResult) -> str:
        """记录评测结果"""
        self._eval_results.setdefault(result.version_id, [])
        self._eval_results[result.version_id].append(result)
        return result.eval_id

    def get_eval_results(self, version_id: str) -> list[PromptEvalResult]:
        """获取指定版本的评测结果"""
        return self._eval_results.get(version_id, [])


prompt_registry = PromptRegistry()


class PromptLoader:
    @staticmethod
    def fill_placeholders(template: str, **kwargs) -> str:
        result = template
        for key, value in kwargs.items():
            result = result.replace(f"{{{key}}}", str(value))
        return result

    @staticmethod
    def render_prompt(
        template: PromptTemplate,
        version: PromptVersion,
        variables: dict,
        rag_context: str = "",
        memory_context: str = "",
    ) -> str:
        """渲染完整Prompt - 文档依据: 4.docx

        按顺序注入:
        1. 模板内容 + 变量替换
        2. Memory上下文 (用户偏好/背景)
        3. RAG上下文 (证据资料)
        使用明确的分区标签隔离，防止注入
        """
        # 1. 基础模板 + 变量替换
        rendered = PromptLoader.fill_placeholders(version.content, **variables)

        # 2. 注入Memory上下文 (用户背景区)
        if memory_context:
            rendered += f"\n\n<!-- USER_BACKGROUND_START -->\n{memory_context}\n<!-- USER_BACKGROUND_END -->"

        # 3. 注入RAG上下文 (证据资料区)
        if rag_context:
            rendered += f"\n\n<!-- EVIDENCE_START -->\n{rag_context}\n<!-- EVIDENCE_END -->"

        return rendered
