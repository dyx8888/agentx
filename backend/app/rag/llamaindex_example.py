"""LlamaIndex 对照检索器示例脚本  # 演示如何用 LlamaIndexRetriever 灌入文档并执行查询
LlamaIndex 对照检索器示例脚本

可独立运行：
    cd backend
    python -m app.rag.llamaindex_example

演示流程：
1. 构造 3 篇示例文档（电商运营知识）
2. 用 LlamaIndexRetriever.add_documents 灌入
3. 用 LlamaIndexRetriever.search 执行一次查询
4. 打印检索结果，展示与自研版一致的 SearchResult 结构

前置条件：
- 已安装 llama-index 和 llama-index-vector-stores-milvus
- Milvus 已启动（默认 localhost:19530）
- EmbeddingService 可用（本地模型或 API 模式）

若 llama_index 未安装，脚本会打印降级提示并安全退出。
"""

import asyncio  # 演示异步 query 接口

from app.core.logging import get_logger  # 结构化日志

logger = get_logger(__name__)  # 模块级 logger


# ═══════════════════════════════════════════════════════════════
# 示例文档：3 篇电商运营知识，模拟企业知识库内容
# ═══════════════════════════════════════════════════════════════
SAMPLE_DOCUMENTS = [
    {  # 第 1 篇：抖音电商运营
        "id": "doc_douyin_ops_001",  # 文档 ID，唯一标识
        "content": (  # 文本内容，模拟一份运营 SOP
            "抖音电商运营核心指标：GPM（千次曝光成交额）= 曝光量 × 点击率 × 转化率 × 客单价 / 1000。"
            "提升 GPM 的关键路径：优化短视频封面提升点击率，优化商品详情页提升转化率，"
            "通过组合营销（满减、赠品）提升客单价。直播间的 GPM 还需考虑停留时长和互动率。"
        ),
        "metadata": {  # 元数据，与自研版格式一致
            "source_file": "抖音电商运营SOP.pdf",  # 源文件名
            "category": "运营",  # 文档分类
            "chunk_index": 0,  # 切片序号
            "total_chunks": 1,  # 总切片数
            "source_page": 3,  # 源页码
        },
    },
    {  # 第 2 篇：小红书种草营销
        "id": "doc_xhs_seeding_001",
        "content": (
            "小红书种草营销方法论：选品 → 笔记内容 → 投流放大。"
            "选品关注「搜索热度 × 竞争密度」，优先选择搜索上升但笔记供给不足的品类。"
            "笔记内容遵循「痛点前置 + 真实体验 + 解决方案」结构，封面标题决定 70% 的点击率。"
            "投流用薯条加热测试，CTR 高于 8% 的笔记可加大投放。"
        ),
        "metadata": {
            "source_file": "小红书种草营销手册.docx",
            "category": "营销",
            "chunk_index": 0,
            "total_chunks": 1,
            "source_page": 7,
        },
    },
    {  # 第 3 篇：私域复购运营
        "id": "doc_private_domain_001",
        "content": (
            "私域复购运营三板斧：社群分层、自动化触达、会员体系。"
            "社群分层按 RFM 模型（最近购买时间、购买频次、消费金额）划分高价值/中价值/沉睡用户。"
            "自动化触达结合企业微信 + SCRM 工具，按用户行为触发精准消息。"
            "会员体系设计阶梯权益，用积分、等级、专属优惠提升复购率。"
        ),
        "metadata": {
            "source_file": "私域复购运营指南.pdf",
            "category": "运营",
            "chunk_index": 0,
            "total_chunks": 1,
            "source_page": 12,
        },
    },
]


def run_sync_example() -> None:  # 同步示例：演示 add_documents + search
    """同步示例：灌入文档并执行同步检索。"""
    # 延迟导入：保证脚本在 llama_index 未安装时也能跑到降级提示
    from .llamaindex_retriever import LLAMAINDEX_AVAILABLE, LlamaIndexRetriever  # 复用检索器

    print("\n" + "=" * 60)  # 分隔线
    print("LlamaIndex 对照检索器 —— 同步示例")  # 标题
    print("=" * 60)

    if not LLAMAINDEX_AVAILABLE:  # llama_index 未安装时降级提示
        print("[降级] llama_index 未安装，示例无法运行。")  # 提示用户
        print("安装方式: pip install llama-index llama-index-vector-stores-milvus")
        return  # 安全退出

    # 步骤 1：创建检索器实例，指定 company_id 实现多租户隔离
    print("\n[步骤1] 创建 LlamaIndexRetriever 实例 (company_id='demo_company')...")
    retriever = LlamaIndexRetriever(company_id="demo_company")  # 多租户隔离

    # 步骤 2：灌入 3 篇示例文档
    print(f"[步骤2] 灌入 {len(SAMPLE_DOCUMENTS)} 篇示例文档...")
    ok = retriever.add_documents(SAMPLE_DOCUMENTS)  # 调用与自研版对齐的接口
    print(f"  灌入结果: {'成功' if ok else '失败（已降级）'}")

    # 步骤 3：执行一次查询（同步）
    query = "如何提升抖音电商的 GPM？"  # 模拟用户提问
    print(f"\n[步骤3] 同步检索: '{query}'")
    results = retriever.search(query, top_k=3)  # 调用 search，返回 SearchResult 列表

    # 步骤 4：打印结果，展示与自研版一致的 SearchResult 结构
    print(f"\n[步骤4] 检索到 {len(results)} 条结果:")
    for i, r in enumerate(results, 1):  # 逐条打印
        print(f"\n  --- 结果 {i} ---")
        print(f"  内容: {r.content[:80]}...")  # 截断显示
        print(f"  向量分数: {r.vector_score:.4f}")  # 向量相似度
        print(f"  来源: {r.source}")  # 检索来源标记
        print(f"  源文件: {r.source_file}")  # 源文件名
        print(f"  页码: {r.source_page}")  # 源页码
        print(f"  分类: {r.metadata.get('category', 'N/A')}")  # 文档分类


async def run_async_example() -> None:  # 异步示例：演示 query 接口
    """异步示例：演示 LlamaIndex QueryEngine 风格的异步查询。"""
    from .llamaindex_retriever import LLAMAINDEX_AVAILABLE, LlamaIndexRetriever  # 延迟导入

    print("\n" + "=" * 60)
    print("LlamaIndex 对照检索器 —— 异步示例 (QueryEngine 风格)")
    print("=" * 60)

    if not LLAMAINDEX_AVAILABLE:  # 未安装降级
        print("[降级] llama_index 未安装，异步示例跳过。")
        return

    # 复用同步示例灌入的文档（同一 company_id，数据已存在）
    retriever = LlamaIndexRetriever(company_id="demo_company")  # 同一租户
    query = "小红书种草笔记怎么写？"  # 另一个查询
    print(f"\n[异步查询] '{query}'")
    results = await retriever.query(query, top_k=2)  # 异步查询接口
    print(f"\n[结果] 检索到 {len(results)} 条:")
    for i, r in enumerate(results, 1):
        print(f"  {i}. [{r.vector_score:.4f}] {r.content[:60]}...")


def main() -> None:  # 主入口
    """示例脚本主入口。"""
    print("LlamaIndex 对照检索器示例")  # 欢迎语
    print("本脚本演示用 LlamaIndex 标准框架实现与自研 HybridRetriever 可互换的检索能力。")

    # 同步示例：灌入 + 检索
    run_sync_example()  # 运行同步示例

    # 异步示例：QueryEngine 风格查询
    asyncio.run(run_async_example())  # 运行异步示例

    print("\n" + "=" * 60)
    print("示例完成。")  # 结束语
    print("对比自研 HybridRetriever：LlamaIndex 版返回相同的 SearchResult 结构，可互换。")
    print("详见 docs/求职准备/LlamaIndex对照实现说明.md")
    print("=" * 60 + "\n")


if __name__ == "__main__":  # 可独立运行入口
    main()  # 执行主函数
