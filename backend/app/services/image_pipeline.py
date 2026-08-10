"""
ImageGenerationPipeline - Multi-stage image generation for visual designer agent

Pipeline stages:
1. Requirement Analysis -> determine visual style direction
2. Style Reference Retrieval -> multimodal RAG via Milvus
3. Subject Generation -> product main image via SD/DALL-E
4. Background Fusion -> scene background integration
5. Text Overlay -> deterministic text rendering
6. Compliance Check -> ad law + platform rules
7. Multi-format Export -> multi-platform multi-size output
"""  # 视觉设计Agent的多阶段图像生成流水线，将复杂设计任务拆解为7个可独立执行的阶段

from dataclasses import dataclass, field  # dataclass用于请求和结果数据载体，field用于可变默认值
from enum import StrEnum  # 使用StrEnum，因为阶段名称和尺寸规格需要以字符串形式传输和存储


class PipelineStage(StrEnum):  # 流水线阶段枚举，按顺序排列，每个阶段依赖前一个阶段的输出
    ANALYSIS = "analysis"  # 需求分析：确定设计方向和风格
    STYLE_RETRIEVAL = "style_retrieval"  # 风格参考检索：从向量库中检索相似设计
    SUBJECT_GEN = "subject_generation"  # 主体生成：生成产品主图
    BACKGROUND = "background_fusion"  # 背景融合：将产品融入场景背景
    TEXT_OVERLAY = "text_overlay"  # 文字叠加：添加卖点文案
    COMPLIANCE = "compliance_check"  # 合规检查：广告法+平台规则审查
    EXPORT = "multi_format_export"  # 多格式导出：适配各平台尺寸


class PlatformSize(StrEnum):  # 各平台的标准尺寸枚举，作为常量引用而非硬编码字符串
    DOUYIN_MAIN = "800x800"  # 抖音主图：正方形
    DOUYIN_DETAIL = "750xN"  # 抖音详情页：宽度固定，高度自适应
    TAOBAO_MAIN = "800x800"  # 淘宝主图：正方形
    TAOBAO_WHITE = "800x800_white"  # 淘宝白底图：纯白背景
    PINDUODUO_MAIN = "750x750"  # 拼多多主图：正方形
    XIAOHONGSHU_COVER = "1080x1440"  # 小红书封面：竖版
    LIVE_COVER = "750x1000"  # 直播封面：竖版


@dataclass  # 使用dataclass，因为ImageDesignRequest是纯数据载体
class ImageDesignRequest:  # 图像设计请求，包含所有设计参数
    product_name: str  # 产品名称，必填
    product_category: str  # 产品类别，用于合规检查和风格参考
    platform: str  # 目标平台，用于确定输出尺寸
    design_type: str  # 设计类型（主图/详情页/封面）
    brand_colors: list[str] = field(default_factory=list)  # 品牌色，使用field避免可变默认值
    brand_font: str = "\u9ed8\u8ba4\u5b57\u4f53"  # 品牌字体，默认系统字体
    style_preference: str = "modern_clean"  # 风格偏好，默认现代简约
    sell_points: list[str] = field(default_factory=list)  # 卖点文案列表
    reference_images: list[str] = field(default_factory=list)  # 参考图片URL列表
    target_sizes: list[str] = field(default_factory=list)  # 目标尺寸列表


@dataclass  # 使用dataclass，因为PipelineResult是纯数据载体
class PipelineResult:  # 每个阶段的执行结果，统一格式便于流水线编排
    stage: PipelineStage  # 当前阶段标识
    success: bool  # 执行是否成功
    output: dict = field(default_factory=dict)  # 阶段输出数据，使用field避免可变默认值
    error: str = ""  # 错误信息，仅失败时有值
    artifacts: list[str] = field(default_factory=list)  # 产物列表（如生成的图片URL）


class ImageGenerationPipeline:  # 图像生成流水线编排器，协调7个阶段的有序执行
    """Multi-stage deterministic image generation pipeline coordinator."""

    PLATFORM_SIZE_MAP: dict[str, dict[str, list[str]]] = {  # 类级别配置，平台→设计类型→尺寸列表的映射；使用嵌套字典，因为不同平台的设计类型不同
        "douyin": {  # 抖音平台
            "main_image": ["800x800"],  # 主图永远是正方形
            "detail_page": ["750x1334"],  # 详情页竖版长图
            "cover": ["1080x1920"],  # 封面竖版
        },
        "taobao": {  # 淘宝平台
            "main_image": ["800x800", "800x800_white"],  # 主图需要普通版和白底图两个版本
            "detail_page": ["750x1000"],
            "cover": ["800x800"],
        },
        "pinduoduo": {  # 拼多多平台
            "main_image": ["750x750"],
            "detail_page": ["750x1000"],
            "cover": ["750x750"],
        },
        "xiaohongshu": {  # 小红书平台
            "main_image": ["1080x1440"],  # 小红书主图就是竖版
            "cover": ["1080x1440"],
        },
    }

    COMPLIANCE_RULES: dict[str, list[str]] = {  # 类级别合规规则，按类别分组；广告法+平台规则
        "general": [  # 通用规则，适用于所有类别
            "\u7981\u6b62\u4f7f\u7528\u7edd\u5bf9\u5316\u7528\u8bed\uff1a\u6700\u3001\u7b2c\u4e00\u3001\u5706\u5bb6\u7ea7\u3001\u6c38\u4e45",
            "\u7981\u6b62\u865a\u5047\u5ba3\u4f20\uff1a\u4f2a\u79d1\u5b66\u3001\u5938\u5927\u6548\u679c\u3001\u5f15\u7528\u672a\u8bc1\u5b9e\u6570\u636e",
            "\u7981\u6b62\u8d23\u6027\u7edf\u8ba1\u6570\u636e\u672a\u6807\u660e\u6765\u6e90",
            "\u4ef7\u683c\u4fe1\u606f\u5fc5\u987b\u51c6\u786e\u65e0\u8bef",
        ],
        "beauty": [  # 美妆类特殊规则
            "\u4e0d\u80fd\u4f7f\u7528\u6ca1\u6709\u5907\u6848\u7684\u4eba\u4f53\u529f\u6548/\u6539\u5584\u8bcd\u6c47",
            "\u9700\u6807\u6ce8\u201c\u6548\u679c\u56e0\u4eba\u800c\u5f02\u201d",
            "\u7279\u6b8a\u5316\u5986\u54c1\u9700\u6807\u6ce8\u6ce8\u610f\u4e8b\u9879",
        ],
        "food": [  # 食品类特殊规则
            "\u9700\u6807\u6ce8\u751f\u4ea7\u65e5\u671f\u548c\u4fdd\u8d28\u671f",
            "\u4e0d\u80fd\u5ba3\u4f20\u533b\u7597/\u4fdd\u5065\u529f\u6548",
            "\u98df\u54c1\u751f\u4ea7\u8bb8\u53ef\u8bc1\u7f16\u53f7\u5fc5\u987b\u663e\u793a",
        ],
        "supplement": [  # 保健品类特殊规则
            "\u4e0d\u80fd\u5ba3\u79f0\u66ff\u4ee3\u836f\u54c1",
            "\u4e0d\u80fd\u5ba3\u79f0\u6cbb\u7597\u6548\u679c",
            "\u5fc5\u987b\u6807\u6ce8\u201c\u672c\u54c1\u4e0d\u80fd\u66ff\u4ee3\u836f\u54c1\u201d",
        ],
    }

    def __init__(self):  # 初始化流水线，不需要外部参数，配置全部来自类级别常量
        self._current_stage: PipelineStage | None = None  # 当前执行阶段，None表示未开始
        self._results: dict[PipelineStage, PipelineResult] = {}  # 阶段结果字典，键为阶段枚举，用于追溯每个阶段的输出

    def analyze_requirements(self, request: ImageDesignRequest) -> PipelineResult:  # 阶段1：需求分析，拆解设计参数为目标尺寸和风格方向
        self._current_stage = PipelineStage.ANALYSIS  # 更新当前阶段，用于外部监控

        sizes = self.PLATFORM_SIZE_MAP.get(request.platform, {}).get(request.design_type, ["800x800"])  # 从平台尺寸映射中获取，默认800x800作为兜底

        output = {  # 构建分析输出，包含所有后续阶段需要的信息
            "design_direction": request.style_preference,
            "brand_colors": request.brand_colors or ["#000000", "#FFFFFF"],  # 默认黑白配色，确保品牌色缺失时不会出错
            "brand_font": request.brand_font,
            "sell_points": request.sell_points[:3],  # 最多取3个卖点，避免文案过多
            "target_sizes": sizes,
            "platform": request.platform,
            "design_type": request.design_type,
            "category": request.product_category,
        }

        result = PipelineResult(stage=PipelineStage.ANALYSIS, success=True, output=output)  # 分析阶段通常不会失败
        self._results[PipelineStage.ANALYSIS] = result  # 存储结果，供后续阶段和run_full_pipeline使用
        return result

    def retrieve_style_references(self, category: str, style_preference: str,
                                   brand_colors: list[str]) -> PipelineResult:  # 阶段2：风格参考检索，当前为占位实现
        self._current_stage = PipelineStage.STYLE_RETRIEVAL

        query_embedding = {  # 构建检索查询，准备用于Milvus多模态检索
            "category": category,
            "style": style_preference,
            "colors": brand_colors,
        }

        result = PipelineResult(  # 占位实现，返回空引用列表
            stage=PipelineStage.STYLE_RETRIEVAL,
            success=True,
            output={
                "query": query_embedding,
                "reference_count": 0,
                "references": [],
                "note": "\u5f85\u96c6\u6210Milvus+CLIP\u540e\u5b9e\u73b0\u591a\u6a21\u6001RAG\u68c0\u7d22",  # 明确标注占位，避免误用
            },
        )
        self._results[PipelineStage.STYLE_RETRIEVAL] = result
        return result

    def generate_subject_image(self, product_name: str, design_direction: str,
                                dimensions: str = "800x800") -> PipelineResult:  # 阶段3：主体生成，当前为占位，待集成SD/DALL-E API
        self._current_stage = PipelineStage.SUBJECT_GEN

        prompt_template = (  # 构建SD/DALL-E的prompt模板，中英文混合以提高生成质量
            f"\u7535\u5546\u4ea7\u54c1\u4e3b\u56fe\uff0c{product_name}\uff0c"
            f"\u98ce\u683c{design_direction}\uff0c\u5c3a\u5bf8{dimensions}\uff0c"
            "\u4e13\u4e1a\u4ea7\u54c1\u6444\u5f71\uff0c\u767d\u8272\u80cc\u666f\uff0c\u5546\u4e1a\u7ea7\u8d28\u91cf"  # 固定后缀，确保生成风格一致
        )

        result = PipelineResult(
            stage=PipelineStage.SUBJECT_GEN,
            success=True,
            output={
                "prompt": prompt_template,
                "generated_image_url": "",  # 空URL，待实际生成后填充
                "note": "\u5f85\u96c6\u6210Stable Diffusion/DALL-E API\u540e\u5b9e\u73b0\u751f\u6210",
            },
        )
        self._results[PipelineStage.SUBJECT_GEN] = result
        return result

    def fuse_background(self, subject_url: str, scene_type: str = "lifestyle") -> PipelineResult:  # 阶段4：背景融合，默认lifestyle场景
        self._current_stage = PipelineStage.BACKGROUND

        result = PipelineResult(
            stage=PipelineStage.BACKGROUND,
            success=True,
            output={
                "scene_type": scene_type,
                "fused_image_url": "",
                "note": "\u5f85\u96c6\u6210\u56fe\u50cf\u878d\u5408\u670d\u52a1\u540e\u5b9e\u73b0",
            },
        )
        self._results[PipelineStage.BACKGROUND] = result
        return result

    def apply_text_overlay(self, image_url: str, sell_points: list[str],
                            brand_colors: list[str], brand_font: str) -> PipelineResult:  # 阶段5：文字叠加，确定性渲染
        self._current_stage = PipelineStage.TEXT_OVERLAY

        overlay_config = {  # 文字叠加配置，确定性渲染参数
            "sell_points": sell_points,
            "primary_color": brand_colors[0] if brand_colors else "#000000",  # 取第一个品牌色，默认黑色
            "font": brand_font,
            "max_lines": 3,  # 最多3行文字，避免遮挡产品主体
            "position": "center_left",  # 左中对齐，电商设计惯例
            "font_size": "adaptive",  # 自适应字号，根据图片尺寸调整
            "text_shadow": True,  # 文字阴影，提高可读性
        }

        result = PipelineResult(
            stage=PipelineStage.TEXT_OVERLAY,
            success=True,
            output={
                "overlay_config": overlay_config,
                "result_image_url": "",
                "note": "\u786e\u5b9a\u6027\u6e32\u67d3\uff0c\u5f85\u56fe\u50cf\u751f\u6210\u540e\u6267\u884c",  # 确定性渲染，不需要AI
            },
        )
        self._results[PipelineStage.TEXT_OVERLAY] = result
        return result

    def check_compliance(self, text_content: str, product_category: str) -> PipelineResult:  # 阶段6：合规检查，基于关键词和规则
        self._current_stage = PipelineStage.COMPLIANCE

        violations = []  # 违规项列表
        warnings = []  # 警告项列表

        general_rules = self.COMPLIANCE_RULES.get("general", [])  # 获取通用规则
        for _rule in general_rules:  # 遍历通用规则（当前未使用rule变量，仅用于触发违规检查）
            for keyword in ["\u6700", "\u7b2c\u4e00", "\u5706\u5bb6\u7ea7", "\u6c38\u4e45", "\u5168\u7f51", "\u552f\u4e00"]:  # 广告法禁用语关键词
                if keyword in text_content:  # 简单子串匹配
                    violations.append(f"\u8fdd\u89c4\u7528\u8bed\uff1a\u542b\u6709\u7981\u7528\u8bcd\u201c{keyword}\u201d")

        category_rules = self.COMPLIANCE_RULES.get(product_category, [])  # 获取品类规则
        for rule in category_rules:  # 品类规则作为警告提示
            warnings.append(f"\u7c7b\u76ee\u89c4\u8303\u63d0\u9192\uff1a{rule}")

        success = len(violations) == 0  # 无违规项才算合规

        result = PipelineResult(
            stage=PipelineStage.COMPLIANCE,
            success=success,  # 有违规时success为False，但流水线仍继续执行
            output={
                "passed": success,
                "violations": violations,
                "warnings": warnings,
                "recommendation": "\u5408\u89c4\uff0c\u53ef\u5bfc\u51fa" if success else "\u4e0d\u5408\u89c4\uff0c\u9700\u4fee\u6539\u540e\u91cd\u65b0\u68c0\u6d4b",
            },
        )
        self._results[PipelineStage.COMPLIANCE] = result
        return result

    def export_formats(self, image_url: str, sizes: list[str], platforms: list[str] = None) -> PipelineResult:  # 阶段7：多格式导出，生成各平台尺寸
        self._current_stage = PipelineStage.EXPORT

        export_list = []  # 导出列表
        for size in sizes:  # 遍历所有尺寸
            for platform in (platforms or ["douyin"]):  # 默认导出抖音格式，确保至少有一个平台
                export_list.append({
                    "platform": platform,
                    "size": size,
                    "format": "webp",  # 使用webp格式，兼顾质量和文件大小
                    "quality": 90,  # 90%质量，平衡视觉和文件大小
                    "download_url": "",  # 空URL，待实际生成
                })

        result = PipelineResult(
            stage=PipelineStage.EXPORT,
            success=True,
            output={
                "exports": export_list,
                "total_formats": len(export_list),
                "note": "\u5f85\u56fe\u50cf\u751f\u6210\u5b8c\u6210\u540e\u5bfc\u51fa",
            },
            artifacts=[e["download_url"] for e in export_list],  # 产物列表
        )
        self._results[PipelineStage.EXPORT] = result
        return result

    def run_full_pipeline(self, request: ImageDesignRequest) -> dict:  # 编排执行全部7个阶段，串联各阶段输入输出
        self._results = {}  # 重置结果，确保每次运行都是全新的

        analysis = self.analyze_requirements(request)  # 阶段1：需求分析
        if not analysis.success:  # 分析失败则终止流水线，因为后续阶段依赖分析结果
            return {"success": False, "stage": PipelineStage.ANALYSIS, "error": analysis.error}

        self.retrieve_style_references(  # 阶段2：风格检索（即使失败也不终止，因为后续阶段可以降级运行）
            request.product_category,
            request.style_preference,
            request.brand_colors,
        )

        sizes = analysis.output.get("target_sizes", ["800x800"])  # 从分析结果中获取目标尺寸
        primary_size = sizes[0]  # 取第一个尺寸作为主图尺寸

        subject = self.generate_subject_image(  # 阶段3：主体生成
            request.product_name,
            analysis.output.get("design_direction", "modern_clean"),  # 使用分析阶段确定的风格方向
            primary_size,
        )

        self.fuse_background(subject.output.get("generated_image_url", ""))  # 阶段4：背景融合
        self.apply_text_overlay(  # 阶段5：文字叠加
            subject.output.get("generated_image_url", ""),
            request.sell_points,
            request.brand_colors,
            request.brand_font,
        )

        compliance = self.check_compliance(  # 阶段6：合规检查
            ", ".join(request.sell_points),  # 将卖点列表合并为单个字符串进行检查
            request.product_category,
        )

        export = self.export_formats(  # 阶段7：多格式导出
            subject.output.get("generated_image_url", ""),
            request.target_sizes or sizes,  # 优先使用用户指定尺寸，否则使用分析阶段确定的尺寸
        )

        return {  # 返回完整的流水线执行摘要
            "success": compliance.success,  # 整体成功与否取决于合规检查
            "stages_completed": len(self._results),  # 完成的阶段数
            "stages": {s.value: r.__dict__ for s, r in self._results.items()},  # 所有阶段结果，用__dict__序列化
            "compliance_passed": compliance.success,
            "exports": len(export.output.get("exports", [])),  # 导出格式数量
        }
